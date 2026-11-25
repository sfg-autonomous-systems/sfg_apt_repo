#!/usr/bin/env python3
"""Build the internal Debian packages defined in src/<package>/ that are missing from the releases.

Internal packages are owned by this repository, e.g. sfg-rosdep-index. Each src/<package>/
directory is a raw dpkg-deb tree with a DEBIAN/control file. Every package is built once and
belongs to the common release, which is published into every distribution.

A package is only built if its canonical filename is missing from its release, see
scripts/package_storage.py. Built packages are written to build/<release name>/. With --upload,
they are uploaded to their releases afterwards.

Usage:
    build_internal_packages.py --branch <branch> [--upload] [--diff-base <commit> --diff-head <commit>]

--branch is the branch of this repository: "main" uses the production releases, every other
branch the test releases. The optional commit range is used to warn when a package source changed
without a version bump. The GitHub CLI reads its token from GH_TOKEN.
"""

import argparse
import io
import shutil
import subprocess
import sys
from pathlib import Path

from debian_package import (
    InvalidPackageError,
    build_package,
    package_filename,
    read_control_file,
)
from package_storage import (
    COMMON_RELEASE_NAME,
    PackageStore,
    ReleaseError,
    upload_packages,
)

REPOSITORY_DIRECTORY = Path(__file__).resolve().parent.parent
SOURCE_DIRECTORY = REPOSITORY_DIRECTORY / "src"
BUILD_DIRECTORY = REPOSITORY_DIRECTORY / "build"


def source_changed(source_directory: Path, diff_base: str, diff_head: str) -> bool:
    if not diff_base or not diff_head:
        return False
    result = subprocess.run(
        ["git", "diff", "--quiet", diff_base, diff_head, "--", str(source_directory)],
        cwd=REPOSITORY_DIRECTORY,
        capture_output=True,
        check=False,
    )
    # Exit code 1 means there are differences; other codes (e.g. an unknown commit) are ignored.
    return result.returncode == 1


def build_packages(
    store: PackageStore, diff_base: str = "", diff_head: str = ""
) -> dict[str, list[Path]]:
    """Build every missing package and return the built package files per release name.

    The optional commit range is only used to warn about source changes without a version bump.
    """
    if BUILD_DIRECTORY.exists():
        shutil.rmtree(BUILD_DIRECTORY)

    built: dict[str, list[Path]] = {}
    for source_directory in sorted(
        path for path in SOURCE_DIRECTORY.iterdir() if path.is_dir()
    ):
        control = read_control_file(source_directory / "DEBIAN" / "control")
        release = store.release(COMMON_RELEASE_NAME)
        filename = package_filename(
            control["Package"], control["Version"], control["Architecture"]
        )

        # The content is unknown before building, so any asset with this label counts as existing.
        check = release.check_package(filename, None)
        if check.exists:
            if source_changed(source_directory, diff_base, diff_head):
                print(
                    f"Warning: '{source_directory.relative_to(REPOSITORY_DIRECTORY)}' changed, but "
                    f"'{filename}' already exists. Bump the version to release the changes."
                )
            continue
        if message := check.blocking_error():
            raise ReleaseError(message)

        print(f"Building package '{filename}' for '{release.tag}'.")
        output_filepath = BUILD_DIRECTORY / release.name / filename
        build_package(source_directory, output_filepath)
        built.setdefault(release.name, []).append(output_filepath)

    print(f"Built {sum(map(len, built.values()))} package(s) into '{BUILD_DIRECTORY}'.")
    return built


def main() -> None:
    # Keep log lines in order when stdout is a pipe, as in GitHub Actions.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--branch",
        required=True,
        help="Branch of this repository: 'main' uses the production releases, others the test ones.",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload the built packages to their releases.",
    )
    parser.add_argument(
        "--diff-base", default="", help="Start of the changed commit range."
    )
    parser.add_argument(
        "--diff-head", default="", help="End of the changed commit range."
    )
    arguments = parser.parse_args()

    try:
        store = PackageStore.for_branch(arguments.branch)
        built = build_packages(store, arguments.diff_base, arguments.diff_head)
        if arguments.upload:
            for release_name, filepaths in built.items():
                upload_packages(store, release_name, filepaths)
    except (ReleaseError, InvalidPackageError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
