"""Tests for scripts/build_internal_packages.py with the real src/ packages and a fake of the releases.

Building packages requires dpkg-deb, so run the tests on Ubuntu:
    python3 -m unittest discover -s tests
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPOSITORY_DIRECTORY = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_DIRECTORY / "scripts"))

import build_internal_packages
from package_storage import COMMON_RELEASE_NAME, PackageStore, upload_packages
from test_package_storage import FakeGitHubReleaseClient


def control_field(filepath: Path, field: str) -> str:
    return subprocess.run(
        ["dpkg-deb", "--field", str(filepath), field],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def extract(filepath: Path, member: str) -> bytes:
    content = subprocess.run(
        ["dpkg-deb", "--fsys-tarfile", str(filepath)], capture_output=True, check=True
    ).stdout
    return subprocess.run(
        ["tar", "-xO", member], input=content, capture_output=True, check=True
    ).stdout


@unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb is required to build packages")
class BuildInternalPackagesTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)

        original_build_directory = build_internal_packages.BUILD_DIRECTORY
        build_internal_packages.BUILD_DIRECTORY = directory / "build"
        self.addCleanup(
            setattr,
            build_internal_packages,
            "BUILD_DIRECTORY",
            original_build_directory,
        )

        self.api = FakeGitHubReleaseClient()
        for tag in ("test-jammy", "test-noble"):
            self.api.create_release(tag)
        self.store = PackageStore(self.api, tag_prefix="test-")

    def built_names(self, built: dict[str, list[Path]]) -> dict[str, list[str]]:
        return {
            release_name: sorted(path.name for path in paths)
            for release_name, paths in built.items()
        }

    def test_builds_distribution_specific_and_common_packages(self) -> None:
        names = self.built_names(build_internal_packages.build_packages(self.store))

        self.assertEqual(names["jammy"], ["sfg-apt-source_1.0.0~jammy_all.deb"])
        self.assertEqual(names["noble"], ["sfg-apt-source_1.0.0~noble_all.deb"])
        self.assertEqual(names[COMMON_RELEASE_NAME], ["sfg-rosdep-index_1.0.0_all.deb"])

    def test_placeholder_and_version_are_replaced(self) -> None:
        built = build_internal_packages.build_packages(self.store)
        package = built["noble"][0]

        self.assertEqual(control_field(package, "Version"), "1.0.0~noble")
        sources = extract(
            package, "./etc/apt/sources.list.d/sfg-apt-repo.sources"
        ).decode()
        self.assertIn("Suites: noble\n", sources)
        self.assertNotIn(build_internal_packages.PLACEHOLDER, sources)

    def test_preinst_checks_the_distribution(self) -> None:
        built = build_internal_packages.build_packages(self.store)
        package = built["jammy"][0]

        control_directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, control_directory)
        subprocess.run(
            ["dpkg-deb", "--control", str(package), str(control_directory)],
            check=True,
        )
        preinst = control_directory / "preinst"
        self.assertTrue(preinst.stat().st_mode & 0o111, "preinst must be executable")
        content = preinst.read_text()
        self.assertIn('"${UBUNTU_CODENAME}" != "jammy"', content)
        self.assertNotIn(build_internal_packages.PLACEHOLDER, content)

    def test_keyring_is_shipped_unchanged(self) -> None:
        built = build_internal_packages.build_packages(self.store)
        keyring = "usr/share/keyrings/sfg-apt-repo.gpg"
        self.assertEqual(
            extract(built["jammy"][0], f"./{keyring}"),
            (REPOSITORY_DIRECTORY / "src" / "sfg-apt-source" / keyring).read_bytes(),
        )

    def test_existing_versions_are_not_rebuilt(self) -> None:
        built = build_internal_packages.build_packages(self.store)
        for release_name, paths in built.items():
            upload_packages(self.store, release_name, paths)

        self.assertEqual(build_internal_packages.build_packages(self.store), {})

    def test_new_distribution_only_gets_distribution_specific_packages(self) -> None:
        built = build_internal_packages.build_packages(self.store)
        for release_name, paths in built.items():
            upload_packages(self.store, release_name, paths)

        self.api.create_release("test-resolute")
        names = self.built_names(build_internal_packages.build_packages(self.store))
        self.assertEqual(names, {"resolute": ["sfg-apt-source_1.0.0~resolute_all.deb"]})


if __name__ == "__main__":
    unittest.main()
