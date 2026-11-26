#!/usr/bin/env python3
"""Manual end-to-end test of scripts/package_storage.py against real GitHub releases.

The unit tests use a fake of the GitHub releases; this script checks the same rules against
GitHub itself. It uses the library directly, because the CLIs are fixed to the production
repository and the uploader app. It is not run by CI or by unittest discovery.

Every run uses its own tag prefix "e2e-<timestamp>-", so runs never interfere with each other.
The releases are left in place for inspection; delete them by hand when no longer needed.

Run it against a temporary repository created only for this test, e.g.
sfg-autonomous-systems/release-asset-name-test; it needs no content and can be deleted afterwards.
Requires dpkg-deb and the GitHub CLI with a token that can write releases of the test
repository, e.g. in an ubuntu:24.04 container:
    GH_TOKEN=... python3 tests/e2e_release_storage.py \\
        --repository sfg-autonomous-systems/release-asset-name-test

Assets are uploaded with that token, so its login is the trusted uploader. It is read from the
token unless --trusted-uploader is given.
"""

import argparse
import io
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from debian_package import build_package, sha256
from package_storage import (
    COMMON_RELEASE_NAME,
    REPOSITORY,
    TRUSTED_UPLOADER,
    GitHubReleaseClient,
    PackageStore,
    ReleaseError,
    download_packages,
    upload_packages,
)


class EndToEndTest:
    def __init__(
        self, repository: str, trusted_uploader: str, work_directory: Path
    ) -> None:
        self.repository = repository
        self.api = GitHubReleaseClient(repository)
        self.tag_prefix = f"e2e-{datetime.now(UTC):%Y%m%d%H%M%S}-"
        self.store = PackageStore(self.api, self.tag_prefix, trusted_uploader)
        self.trusted_uploader = trusted_uploader
        self.work_directory = work_directory
        self.failures: list[str] = []

    # Helpers.

    def build(self, package: str, version: str, content: str) -> Path:
        """Build a small Architecture: all package; different content gives a different digest."""
        tree = self.work_directory / "trees" / f"{package}_{version}_{content}"
        (tree / "DEBIAN").mkdir(parents=True)
        (tree / "DEBIAN" / "control").write_text(
            f"Package: {package}\nVersion: {version}\nArchitecture: all\n"
            "Maintainer: SFG <sfg@example.com>\nDescription: End-to-end test package\n"
        )
        document = tree / "usr" / "share" / "doc" / package / "content"
        document.parent.mkdir(parents=True)
        document.write_text(f"{content}\n")
        # Ignore the build user's umask, which dpkg-deb would reject for DEBIAN/.
        for path in [tree, *tree.rglob("*")]:
            path.chmod(0o755 if path.is_dir() else 0o644)
        output = self.work_directory / "debs" / content / f"{package}_{version}_all.deb"
        build_package(tree, output)
        return output

    def labels(self, release_name: str) -> list[str]:
        release = self.store.release(release_name)
        release_id = self.api.release_id(release.tag)
        if release_id is None:
            return []
        return sorted(asset.label for asset in self.api.assets(release_id))

    def check(self, description: str, condition: bool, details: str = "") -> None:
        print(f"{'PASS' if condition else 'FAIL'}: {description}")
        if not condition:
            self.failures.append(description)
            if details:
                print(f"      {details}")

    def expect_error(
        self, description: str, expected: str, action: Callable[[], object]
    ) -> None:
        try:
            action()
        except ReleaseError as error:
            self.check(
                description,
                expected in str(error),
                f"expected '{expected}' in: {error}",
            )
        else:
            self.check(description, False, "no error was raised")

    # Scenarios, in order; later ones build on the releases of earlier ones.

    def run(self) -> None:
        print(f"Repository '{self.repository}', tag prefix '{self.tag_prefix}'.\n")
        tilde = self.build("e2e-tilde", "1.0.0~jammy", "a")
        demo = self.build("e2e-demo", "1.0.0", "a")
        demo_changed = self.build("e2e-demo", "1.0.0", "b")
        extra = self.build("e2e-extra", "1.0.0", "a")
        dot = self.build("e2e-tilde", "1.0.0.jammy", "a")
        noble = self.build("e2e-noble", "1.0.0", "a")
        common = self.build("e2e-common", "1.0.0", "a")
        unlabeled = self.build("e2e-unlabeled", "1.0.0~noble", "a")

        upload_packages(self.store, "jammy", [tilde, demo])
        jammy = self.store.release("jammy")
        release_id = self.api.release_id(jammy.tag)
        assets = self.api.assets(release_id) if release_id is not None else []
        self.check(
            "Upload creates the release and labels assets with their canonical filename",
            sorted(asset.label for asset in assets)
            == ["e2e-demo_1.0.0_all.deb", "e2e-tilde_1.0.0~jammy_all.deb"],
            str(assets),
        )
        self.check(
            "GitHub sanitizes '~' in the asset name",
            "e2e-tilde_1.0.0.jammy_all.deb" in [asset.name for asset in assets],
        )
        by_label = {asset.label: asset for asset in assets}
        self.check(
            "Assets have the SHA-256 digest and the uploader of the uploaded file",
            by_label.get("e2e-demo_1.0.0_all.deb") is not None
            and by_label["e2e-demo_1.0.0_all.deb"].digest == f"sha256:{sha256(demo)}"
            and by_label["e2e-demo_1.0.0_all.deb"].uploader == self.trusted_uploader,
            str(by_label.get("e2e-demo_1.0.0_all.deb")),
        )

        upload_packages(self.store, "jammy", [tilde, demo])
        self.check(
            "Uploading identical packages again is skipped",
            len(self.labels("jammy")) == 2,
        )

        self.expect_error(
            "Same version with different content fails",
            "increment the version",
            lambda: upload_packages(self.store, "jammy", [demo_changed, extra]),
        )
        self.check(
            "A failed validation uploads none of the packages",
            "e2e-extra_1.0.0_all.deb" not in self.labels("jammy"),
        )

        self.expect_error(
            "A different package with the same sanitized asset name fails",
            "collides with",
            lambda: upload_packages(self.store, "jammy", [dot]),
        )

        upload_packages(self.store, "noble", [noble])
        upload_packages(self.store, COMMON_RELEASE_NAME, [common])
        self.check(
            "Packages are uploaded to the distribution and common releases",
            self.labels("noble") == ["e2e-noble_1.0.0_all.deb"]
            and self.labels(COMMON_RELEASE_NAME) == ["e2e-common_1.0.0_all.deb"],
        )
        self.expect_error(
            "A common package must not also be stored in a distribution release",
            "not both",
            lambda: upload_packages(self.store, "noble", [common]),
        )
        self.expect_error(
            "A distribution package must not also be stored in the common release",
            "not both",
            lambda: upload_packages(self.store, COMMON_RELEASE_NAME, [demo]),
        )

        packages_directory = self.work_directory / "packages"
        download_packages(self.store, packages_directory)
        downloaded = {
            directory.name: sorted(path.name for path in directory.iterdir())
            for directory in packages_directory.iterdir()
        }
        self.check(
            "Download restores canonical filenames and adds common packages everywhere",
            downloaded
            == {
                "jammy": [
                    "e2e-common_1.0.0_all.deb",
                    "e2e-demo_1.0.0_all.deb",
                    "e2e-tilde_1.0.0~jammy_all.deb",
                ],
                "noble": ["e2e-common_1.0.0_all.deb", "e2e-noble_1.0.0_all.deb"],
            },
            str(downloaded),
        )
        self.check(
            "Downloaded packages match the uploaded files",
            sha256(packages_directory / "jammy" / "e2e-tilde_1.0.0~jammy_all.deb")
            == sha256(tilde),
        )
        jammy_common = packages_directory / "jammy" / "e2e-common_1.0.0_all.deb"
        noble_common = packages_directory / "noble" / "e2e-common_1.0.0_all.deb"
        self.check(
            "Common packages are hard links, not copies",
            jammy_common.stat().st_ino == noble_common.stat().st_ino,
        )

        # The same releases, seen by a store that only trusts the uploader app, as in CI.
        app_store = PackageStore(self.api, self.tag_prefix, TRUSTED_UPLOADER)
        self.expect_error(
            "Uploading over an asset of another uploader fails",
            "not by CI",
            lambda: upload_packages(app_store, "jammy", [tilde]),
        )
        self.expect_error(
            "Downloading assets of another uploader fails",
            "were not uploaded by",
            lambda: download_packages(app_store, self.work_directory / "untrusted"),
        )

        # Upload an asset without a label, as a manual upload would. It bypasses the store, so a new
        # store is needed that does not use the cached asset lists, as a new CI run would.
        subprocess.run(
            [
                "gh",
                "release",
                "upload",
                self.store.release("noble").tag,
                str(unlabeled),
                "--repo",
                self.repository,
            ],
            check=True,
        )
        fresh_store = PackageStore(self.api, self.tag_prefix, self.trusted_uploader)
        self.expect_error(
            "Uploading over an unlabeled asset with the same name fails",
            "unlabeled asset",
            lambda: upload_packages(fresh_store, "noble", [unlabeled]),
        )
        self.expect_error(
            "Downloading an unlabeled asset fails",
            "has no label",
            lambda: download_packages(fresh_store, self.work_directory / "unlabeled"),
        )


def main() -> None:
    # Keep log lines in order when stdout is a pipe.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--repository",
        required=True,
        help="Temporary test repository, e.g. sfg-autonomous-systems/release-asset-name-test.",
    )
    parser.add_argument(
        "--trusted-uploader",
        help="Login of the token's user (default: read from the token).",
    )
    arguments = parser.parse_args()
    if arguments.repository == REPOSITORY:
        parser.error(
            f"Refusing to run against the production repository '{REPOSITORY}'."
        )
    if not os.environ.get("GH_TOKEN"):
        print("Warning: GH_TOKEN is not set; the GitHub CLI uses its stored login.")

    trusted_uploader = (
        arguments.trusted_uploader
        or subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )

    with tempfile.TemporaryDirectory() as work_directory:
        test = EndToEndTest(
            arguments.repository, trusted_uploader, Path(work_directory)
        )
        test.run()

    print(f"\nReleases with the prefix '{test.tag_prefix}' are left in place.")
    if test.failures:
        print(f"{len(test.failures)} check(s) failed.")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
