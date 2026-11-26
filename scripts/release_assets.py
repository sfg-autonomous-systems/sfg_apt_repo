#!/usr/bin/env python3
"""Upload Debian packages to the package releases, or download them for publishing.

See scripts/package_storage.py for how packages are stored and validated.

Usage:
    release_assets.py --branch <branch> upload <distribution|all> <package.deb>...
    release_assets.py --branch <branch> download <packages directory>
    release_assets.py --branch <branch> list-distributions

--branch is the branch of this repository the workflow runs on: "main" uses the production
releases, every other branch the test releases. The GitHub CLI reads its token from GH_TOKEN.
"""

import argparse
import io
import sys
from pathlib import Path

from debian_package import InvalidPackageError
from package_storage import (
    PackageStore,
    ReleaseError,
    download_packages,
    release_name_of_distribution,
    upload_packages,
)


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
    subparsers = parser.add_subparsers(dest="command", required=True)
    upload_parser = subparsers.add_parser(
        "upload", help="Upload packages to a distribution or to all."
    )
    upload_parser.add_argument(
        "distribution", help="Ubuntu codename, or 'all' for the common release."
    )
    upload_parser.add_argument("packages", nargs="+", type=Path)
    download_parser = subparsers.add_parser(
        "download", help="Download all packages for publishing."
    )
    download_parser.add_argument("packages_directory", type=Path)
    subparsers.add_parser(
        "list-distributions", help="Print the distributions with a release."
    )
    arguments = parser.parse_args()

    try:
        store = PackageStore.for_branch(arguments.branch)
        if arguments.command == "upload":
            release_name = release_name_of_distribution(arguments.distribution)
            upload_packages(store, release_name, arguments.packages)
        elif arguments.command == "download":
            download_packages(store, arguments.packages_directory)
        elif arguments.command == "list-distributions":
            print("\n".join(store.distributions()))
    except (ReleaseError, InvalidPackageError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
