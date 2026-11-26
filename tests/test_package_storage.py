"""Tests for scripts/package_storage.py with an in-memory fake of the GitHub releases.

The fake behaves like GitHub as verified by tests/e2e_release_storage.py:
asset names are sanitized ("~" and ":" become "."), labels are kept as given, every asset has a
SHA-256 digest, and uploading an existing asset name fails.

Building test packages requires dpkg-deb, so run the tests on Ubuntu:
    python3 -m unittest discover -s tests
"""

import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import package_storage
from debian_package import sha256
from package_storage import (
    COMMON_RELEASE_NAME,
    TRUSTED_UPLOADER,
    GitHubReleaseAsset,
    PackageStatus,
    PackageStore,
    ReleaseApi,
    ReleaseError,
    download_packages,
    github_release_asset_name,
    release_name_of_distribution,
    tag_prefix_of_branch,
    upload_packages,
)


class FakeGitHubReleaseClient(ReleaseApi):
    def __init__(self) -> None:
        self.corrupted_assets: set[str] = set()
        # Assets uploaded by someone other than the uploader app, keyed by (tag, asset name).
        self.uploaders: dict[tuple[str, str], str] = {}
        self.releases: dict[
            str, dict[str, tuple[str, bytes]]
        ] = {}  # tag -> asset name -> (label, content)
        self.uploads = 0

    def release_tags(self) -> list[str]:
        return list(self.releases)

    def release_id(self, tag: str) -> int | None:
        return list(self.releases).index(tag) if tag in self.releases else None

    def assets(self, release_id: int) -> list[GitHubReleaseAsset]:
        tag = list(self.releases)[release_id]
        return [
            GitHubReleaseAsset(
                name=name,
                label=label,
                digest=f"sha256:{hashlib.sha256(content).hexdigest()}",
                uploader=self.uploaders.get((tag, name), TRUSTED_UPLOADER),
            )
            for name, (label, content) in self.releases[tag].items()
        ]

    def create_release(self, tag: str) -> None:
        self.releases[tag] = {}

    def upload(self, tag: str, files: list[tuple[Path, str]]) -> None:
        if tag not in self.releases:
            raise ReleaseError("release not found")
        for filepath, label in files:
            name = github_release_asset_name(filepath.name)
            if name in self.releases[tag]:
                raise ReleaseError(
                    f"asset under the same name already exists: [{name}]"
                )
            self.releases[tag][name] = (label, filepath.read_bytes())
        self.uploads += 1

    def download(self, tag: str, directory: Path) -> None:
        for name, (_, content) in self.releases[tag].items():
            if name in self.corrupted_assets:
                content = b"corrupted"
            (directory / name).write_bytes(content)


@unittest.skipUnless(
    shutil.which("dpkg-deb"), "dpkg-deb is required to build test packages"
)
class PackageStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory)
        self.api = FakeGitHubReleaseClient()
        self.store = PackageStore(self.api, tag_prefix="test-")

    def build(self, package: str, version: str, description: str = "test") -> Path:
        tree = self.directory / "trees" / f"{package}_{version}_{description}"
        (tree / "DEBIAN").mkdir(parents=True)
        (tree / "DEBIAN" / "control").write_text(
            f"Package: {package}\nVersion: {version}\nArchitecture: all\n"
            f"Maintainer: Test <test@example.com>\nDescription: {description}\n"
        )
        output = self.directory / "debs" / description / f"{package}_{version}_all.deb"
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["dpkg-deb", "--root-owner-group", "--build", str(tree), str(output)],
            check=True,
            capture_output=True,
        )
        return output

    def labels(self, tag: str) -> set[str]:
        return {label for label, _ in self.api.releases.get(tag, {}).values()}

    def test_test_branches_use_test_prefix(self) -> None:
        self.assertEqual(tag_prefix_of_branch("main"), "")
        self.assertEqual(tag_prefix_of_branch("feature"), "test-")
        self.assertEqual(tag_prefix_of_branch(""), "test-")
        self.assertEqual(
            PackageStore(self.api, tag_prefix="").release("jammy").tag, "jammy"
        )
        self.assertEqual(self.store.release("jammy").tag, "test-jammy")

    def test_distributions_exclude_common_and_other_prefixes(self) -> None:
        for tag in (
            "common",
            "jammy",
            "test-common",
            "test-jammy",
            "test-noble",
            "v1.0",
        ):
            self.api.create_release(tag)
        self.assertEqual(self.store.distributions(), ["jammy", "noble"])
        self.assertEqual(
            PackageStore(self.api, tag_prefix="").distributions(), ["jammy"]
        )

    def test_upload_creates_release_and_labels_with_canonical_name(self) -> None:
        package = self.build("demo", "1.0.0~jammy1")
        upload_packages(self.store, "jammy", [package])
        self.assertEqual(self.labels("test-jammy"), {"demo_1.0.0~jammy1_all.deb"})
        self.assertIn("demo_1.0.0.jammy1_all.deb", self.api.releases["test-jammy"])

    def test_upload_renames_to_canonical_name(self) -> None:
        package = self.build("demo", "1.0.0")
        renamed = package.with_name("whatever.deb")
        package.rename(renamed)
        upload_packages(self.store, "jammy", [renamed])
        self.assertEqual(self.labels("test-jammy"), {"demo_1.0.0_all.deb"})

    def test_identical_resubmission_is_skipped(self) -> None:
        package = self.build("demo", "1.0.0")
        upload_packages(self.store, "jammy", [package])
        upload_packages(self.store, "jammy", [package])
        self.assertEqual(self.api.uploads, 1)

    def test_same_version_with_different_content_fails(self) -> None:
        upload_packages(self.store, "jammy", [self.build("demo", "1.0.0", "first")])
        with self.assertRaises(ReleaseError):
            upload_packages(
                self.store, "jammy", [self.build("demo", "1.0.0", "rebuilt")]
            )

    def test_sanitized_name_collision_fails(self) -> None:
        upload_packages(self.store, "jammy", [self.build("demo", "1.0.0~jammy1")])
        with self.assertRaises(ReleaseError):
            upload_packages(self.store, "jammy", [self.build("demo", "1.0.0.jammy1")])
        self.assertEqual(self.api.uploads, 1)

    def test_unlabeled_asset_with_same_name_fails(self) -> None:
        self.api.create_release("test-jammy")
        self.api.releases["test-jammy"]["demo_1.0.0_all.deb"] = (
            "",
            b"manual upload",
        )
        with self.assertRaises(ReleaseError):
            upload_packages(self.store, "jammy", [self.build("demo", "1.0.0")])

    def test_package_in_common_cannot_be_added_to_distribution(self) -> None:
        self.api.create_release("test-jammy")
        package = self.build("demo", "1.0.0")
        upload_packages(self.store, COMMON_RELEASE_NAME, [package])
        with self.assertRaises(ReleaseError):
            upload_packages(self.store, "jammy", [package])

    def test_package_in_distribution_cannot_be_added_to_common(self) -> None:
        package = self.build("demo", "1.0.0")
        upload_packages(self.store, "noble", [package])
        with self.assertRaises(ReleaseError):
            upload_packages(self.store, COMMON_RELEASE_NAME, [package])

    def test_one_invalid_package_blocks_the_whole_upload(self) -> None:
        broken = self.directory / "broken.deb"
        broken.write_text("not a package")
        with self.assertRaises(ReleaseError):
            upload_packages(self.store, "jammy", [self.build("demo", "1.0.0"), broken])
        self.assertEqual(self.api.uploads, 0)

    def test_duplicate_package_in_one_submission_fails(self) -> None:
        package = self.build("demo", "1.0.0")
        copy = self.directory / "copy.deb"
        shutil.copyfile(package, copy)
        with self.assertRaises(ReleaseError):
            upload_packages(self.store, "jammy", [package, copy])

    def test_asset_limit(self) -> None:
        self.api.create_release("test-jammy")
        for index in range(package_storage.ASSET_LIMIT):
            self.api.releases["test-jammy"][f"filler_{index}.deb"] = (
                f"filler_{index}.deb",
                b"",
            )
        with self.assertRaises(ReleaseError):
            upload_packages(self.store, "jammy", [self.build("demo", "1.0.0")])

    def test_invalid_release_name_fails(self) -> None:
        with self.assertRaises(ReleaseError):
            upload_packages(self.store, "Jammy-1", [self.build("demo", "1.0.0")])

    def test_release_name_of_distribution(self) -> None:
        self.assertEqual(release_name_of_distribution("all"), COMMON_RELEASE_NAME)
        self.assertEqual(release_name_of_distribution("jammy"), "jammy")
        for invalid in ("common", "Jammy", "jammy-1", ""):
            with self.assertRaises(ReleaseError):
                release_name_of_distribution(invalid)

    def test_download_restores_canonical_names_and_adds_common_packages(self) -> None:
        upload_packages(self.store, "jammy", [self.build("demo", "1.0.0~jammy1")])
        upload_packages(self.store, "noble", [self.build("demo", "1.0.0~noble1")])
        common = self.build("shared", "2.0.0")
        upload_packages(self.store, COMMON_RELEASE_NAME, [common])

        packages_directory = self.directory / "packages"
        download_packages(self.store, packages_directory)

        self.assertEqual(
            sorted(
                str(path.relative_to(packages_directory))
                for path in packages_directory.rglob("*.deb")
            ),
            [
                "jammy/demo_1.0.0~jammy1_all.deb",
                "jammy/shared_2.0.0_all.deb",
                "noble/demo_1.0.0~noble1_all.deb",
                "noble/shared_2.0.0_all.deb",
            ],
        )
        self.assertEqual(
            sha256(packages_directory / "noble" / "shared_2.0.0_all.deb"),
            sha256(common),
        )

    def test_download_detects_corrupted_asset(self) -> None:
        upload_packages(self.store, "jammy", [self.build("demo", "1.0.0")])
        self.api.corrupted_assets.add("demo_1.0.0_all.deb")
        with self.assertRaises(ReleaseError):
            download_packages(self.store, self.directory / "packages")

    def test_manually_uploaded_asset_blocks_upload(self) -> None:
        package = self.build("demo", "1.0.0")
        upload_packages(self.store, "jammy", [package])
        self.api.uploaders[("test-jammy", "demo_1.0.0_all.deb")] = "someone"

        check = self.store.release("jammy").check_package("demo_1.0.0_all.deb", None)
        self.assertEqual(check.status, PackageStatus.UNTRUSTED)
        self.assertEqual(check.uploader, "someone")
        # Even identical content is refused, because the existing asset can't be trusted.
        with self.assertRaises(ReleaseError):
            upload_packages(self.store, "jammy", [package])

    def test_manually_uploaded_asset_with_sanitized_name_blocks_upload(self) -> None:
        self.api.create_release("test-jammy")
        self.api.releases["test-jammy"]["demo_1.0.0.jammy1_all.deb"] = (
            "demo_1.0.0.jammy1_all.deb",
            b"manual upload",
        )
        self.api.uploaders[("test-jammy", "demo_1.0.0.jammy1_all.deb")] = "someone"

        check = self.store.release("jammy").check_package(
            "demo_1.0.0~jammy1_all.deb", None
        )
        self.assertEqual(check.status, PackageStatus.UNTRUSTED)

    def test_download_refuses_manually_uploaded_asset(self) -> None:
        upload_packages(self.store, "jammy", [self.build("demo", "1.0.0")])
        self.api.uploaders[("test-jammy", "demo_1.0.0_all.deb")] = "someone"
        with self.assertRaises(ReleaseError):
            download_packages(self.store, self.directory / "packages")

    def test_trusted_uploader_can_be_configured(self) -> None:
        store = PackageStore(self.api, tag_prefix="test-", trusted_uploader="tester")
        self.api.create_release("test-jammy")
        self.api.releases["test-jammy"]["demo_1.0.0_all.deb"] = (
            "demo_1.0.0_all.deb",
            b"",
        )
        self.api.uploaders[("test-jammy", "demo_1.0.0_all.deb")] = "tester"
        check = store.release("jammy").check_package("demo_1.0.0_all.deb", None)
        self.assertEqual(check.status, PackageStatus.DIFFERENT)

    def test_check_package_without_digest_treats_existing_label_as_different(
        self,
    ) -> None:
        upload_packages(self.store, "jammy", [self.build("demo", "1.0.0")])
        self.assertEqual(
            self.store.release("jammy")
            .check_package("demo_1.0.0_all.deb", None)
            .status,
            PackageStatus.DIFFERENT,
        )
        self.assertEqual(
            self.store.release("jammy")
            .check_package("demo_2.0.0_all.deb", None)
            .status,
            PackageStatus.NEW,
        )


if __name__ == "__main__":
    unittest.main()
