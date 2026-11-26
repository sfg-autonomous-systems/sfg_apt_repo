"""Tests for scripts/build_internal_packages.py with the real src/ packages and a fake of the releases.

Building packages requires dpkg-deb, so run the tests on Ubuntu:
    python3 -m unittest discover -s tests
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPOSITORY_DIRECTORY = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_DIRECTORY / "scripts"))

import build_internal_packages
from package_storage import COMMON_RELEASE_NAME, PackageStore, upload_packages
from test_package_storage import FakeGitHubReleaseClient


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

    def test_builds_packages_into_common(self) -> None:
        built = build_internal_packages.build_packages(self.store)
        self.assertEqual(
            {
                release_name: [path.name for path in paths]
                for release_name, paths in built.items()
            },
            {COMMON_RELEASE_NAME: ["sfg-rosdep-index_1.0.0_all.deb"]},
        )

    def test_existing_versions_are_not_rebuilt(self) -> None:
        built = build_internal_packages.build_packages(self.store)
        for release_name, paths in built.items():
            upload_packages(self.store, release_name, paths)

        self.assertEqual(build_internal_packages.build_packages(self.store), {})


if __name__ == "__main__":
    unittest.main()
