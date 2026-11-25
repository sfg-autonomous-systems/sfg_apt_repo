"""Helpers for Debian package files and dpkg-deb trees."""

import hashlib
import subprocess
from pathlib import Path

REQUIRED_FIELDS = ("Package", "Version", "Architecture")


class InvalidPackageError(Exception):
    """A Debian package or package tree is invalid. The message is meant for the user."""


def package_filename(package: str, version: str, architecture: str) -> str:
    """Return the canonical filename "<Package>_<Version>_<Architecture>.deb"."""
    return f"{package}_{version}_{architecture}.deb"


def control_field(filepath: Path, field: str) -> str:
    """Read a field from the control file of a built Debian package."""
    result = subprocess.run(
        ["dpkg-deb", "--field", str(filepath), field],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise InvalidPackageError(
            f"'{filepath}' is not a valid Debian package: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def canonical_name(filepath: Path) -> str:
    """Return the canonical filename of a built Debian package, read from its control file."""
    fields = [control_field(filepath, field) for field in REQUIRED_FIELDS]
    if not all(fields):
        raise InvalidPackageError(
            f"'{filepath}' has no Package, Version or Architecture field."
        )
    return package_filename(*fields)


def read_control_file(control_filepath: Path) -> dict[str, str]:
    """Read the single-line fields of a DEBIAN/control file in a package tree.

    Raises InvalidPackageError if the file is missing or lacks Package, Version or Architecture.
    """
    if not control_filepath.is_file():
        raise InvalidPackageError(f"'{control_filepath}' does not exist.")
    fields = {}
    for line in control_filepath.read_text().splitlines():
        if line and not line[0].isspace() and ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    if not all(fields.get(field) for field in REQUIRED_FIELDS):
        raise InvalidPackageError(
            f"'{control_filepath}' must define Package, Version and Architecture."
        )
    return fields


def build_package(tree: Path, output_filepath: Path) -> None:
    """Build a Debian package from a dpkg-deb tree, with files owned by root."""
    output_filepath.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["dpkg-deb", "--root-owner-group", "--build", str(tree), str(output_filepath)],
        check=True,
    )


def sha256(filepath: Path) -> str:
    with open(filepath, "rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()
