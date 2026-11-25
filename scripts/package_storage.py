"""Store Debian packages as GitHub release assets.

Packages are stored in one release per release name:

    common          Packages installable on every distribution, published into all of them.
    <distribution>  Packages for one Ubuntu distribution, e.g. jammy or noble.

Each release is a PackageRelease; all releases with the same tag prefix form a PackageStore. A
release's tag is its name with the store's tag prefix, e.g. "jammy" or "test-jammy".

GitHub sanitizes asset names ("~" and ":" become "."), so each asset's label holds the exact
canonical filename "<Package>_<Version>_<Architecture>.deb" and identifies the package. Content
is compared with the asset digest (SHA-256). Existing assets are never overwritten.

Anyone with write access to the repository can upload release assets, so only assets uploaded by
the uploader app are trusted: they block conflicting uploads and are the only ones published.

Runs on the branch "main" use the production releases. Every other branch, including an unknown
one, uses releases with the "test-" tag prefix, e.g. "test-jammy".

The GitHub CLI reads its token from GH_TOKEN.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from debian_package import InvalidPackageError, canonical_name, sha256

COMMON_RELEASE_NAME = "common"
ALL_DISTRIBUTIONS = "all"
TEST_TAG_PREFIX = "test-"
PRODUCTION_BRANCH = "main"
REPOSITORY = "sfg-autonomous-systems/sfg_apt_repo"
# GitHub shows uploads made with a GitHub App's token as "<app slug>[bot]".
TRUSTED_UPLOADER = "sfg-apt-repo-uploader[bot]"
ASSET_LIMIT = 1000
ASSET_WARNING_THRESHOLD = 900
RELEASE_NAME_PATTERN = re.compile(r"^[a-z]+$")


class ReleaseError(Exception):
    """A release operation failed. The message is meant for the user."""


@dataclass(frozen=True)
class GitHubReleaseAsset:
    name: str
    label: str
    digest: str
    uploader: str


def github_release_asset_name(filename: str) -> str:
    """Return the name GitHub stores for an uploaded filename."""
    return filename.replace("~", ".").replace(":", ".")


class PackageStatus(Enum):
    """Where a package stands relative to the assets of one release.

    The package is identified by its canonical filename, which is stored as the asset label.
    Only NEW allows an upload; IDENTICAL is skipped; the others block the upload.
    """

    # Neither the label nor the sanitized asset name exists yet: the package can be uploaded.
    NEW = "new"
    # The label exists with the same SHA-256, e.g. on a workflow retry: skip the upload.
    IDENTICAL = "identical"
    # The label exists with different content, e.g. a rebuild of the same version: the version
    # must be bumped, because a published package version must never change.
    DIFFERENT = "different"
    # Another package's label maps to the same sanitized asset name, e.g. "1.0.0~jammy1" and
    # "1.0.0.jammy1": GitHub can't store both, so a different version must be chosen.
    COLLISION = "collision"
    # An asset with the same sanitized name exists but has no label, so it wasn't uploaded by CI
    # and can't be identified.
    UNLABELED = "unlabeled"
    # An asset with this label or sanitized name was uploaded by someone other than the uploader
    # app, e.g. by hand. It must be removed before the package can be uploaded.
    UNTRUSTED = "untrusted"


@dataclass(frozen=True)
class PackageCheck:
    """Result of comparing a package with the assets of one release.

    Attributes:
        status: How the package relates to the release's assets.
        release_tag: Tag of the release that was checked, e.g. "test-jammy".
        package_filename: Canonical filename of the package, which is also its asset label, e.g.
            "foo_1.0.0~jammy_amd64.deb".
        conflicting_asset: For COLLISION, UNLABELED and UNTRUSTED, the existing asset in the way:
            its label, or its name if it has no label. Empty otherwise.
        uploader: For UNTRUSTED, the login of whoever uploaded the conflicting asset.
    """

    status: PackageStatus
    release_tag: str
    package_filename: str
    conflicting_asset: str = ""
    uploader: str = ""

    @property
    def exists(self) -> bool:
        """Whether an asset with the package's label exists, with any content."""
        return self.status in (PackageStatus.IDENTICAL, PackageStatus.DIFFERENT)

    def blocking_error(self) -> str | None:
        """Return the error message if this result prevents an upload, otherwise None."""
        package, tag = self.package_filename, self.release_tag
        if self.status == PackageStatus.DIFFERENT:
            return (
                f"'{package}' already exists in '{tag}' with different content. "
                "You must increment the version in your 'DEBIAN/control' file."
            )
        if self.status == PackageStatus.COLLISION:
            return (
                f"'{package}' collides with '{self.conflicting_asset}' in '{tag}': "
                f"GitHub stores both as '{github_release_asset_name(package)}'. "
                "Choose a different version."
            )
        if self.status == PackageStatus.UNLABELED:
            return (
                f"'{tag}' has the unlabeled asset '{self.conflicting_asset}' with the "
                f"same name as '{package}'. Assets must only be uploaded by CI."
            )
        if self.status == PackageStatus.UNTRUSTED:
            return (
                f"'{tag}' has an asset for '{package}' that was uploaded by "
                f"'{self.uploader}', not by CI. Delete it before uploading."
            )
        return None


class ReleaseApi(ABC):
    """The release operations used by PackageStore and PackageRelease.

    Implemented by GitHubReleaseClient and by the test fake FakeGitHubReleaseClient.

    A subclass that misses one of the methods can't be instantiated, so the test fake can't
    silently drift from the real client.
    """

    @abstractmethod
    def release_tags(self) -> list[str]:
        """Return the tags of all releases."""

    @abstractmethod
    def release_id(self, tag: str) -> int | None:
        """Return the ID of a release, or None if it does not exist."""

    @abstractmethod
    def assets(self, release_id: int) -> list[GitHubReleaseAsset]:
        """Return all assets of a release."""

    @abstractmethod
    def create_release(self, tag: str) -> None:
        """Create a release and its tag."""

    @abstractmethod
    def upload(self, tag: str, files: list[tuple[Path, str]]) -> None:
        """Upload files with labels. Must never overwrite existing assets."""

    @abstractmethod
    def download(self, tag: str, directory: Path) -> None:
        """Download all package assets of a release into a directory."""


class GitHubReleaseClient(ReleaseApi):
    """Release operations of the GitHub CLI for one repository."""

    def __init__(self, repository: str) -> None:
        self.repository = repository

    def _run(self, *arguments: str) -> str:
        result = subprocess.run(
            ["gh", *arguments], capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise ReleaseError(
                f"'gh {arguments[0]} {arguments[1]}' failed: {result.stderr.strip()}"
            )
        return result.stdout

    def release_tags(self) -> list[str]:
        output = self._run(
            "release",
            "list",
            "--repo",
            self.repository,
            "--limit",
            "1000",
            "--json",
            "tagName",
        )
        return [release["tagName"] for release in json.loads(output)]

    def release_id(self, tag: str) -> int | None:
        """Return the ID of a release, or None if it does not exist."""
        result = subprocess.run(
            ["gh", "api", f"repos/{self.repository}/releases/tags/{tag}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return int(json.loads(result.stdout)["id"])
        if "HTTP 404" in result.stderr:
            return None
        raise ReleaseError(f"Could not read release '{tag}': {result.stderr.strip()}")

    def assets(self, release_id: int) -> list[GitHubReleaseAsset]:
        # With --paginate and --jq, every asset is printed as one JSON object per line.
        output = self._run(
            "api",
            "--paginate",
            f"repos/{self.repository}/releases/{release_id}/assets?per_page=100",
            "--jq",
            ".[]",
        )
        return [
            GitHubReleaseAsset(
                name=item["name"],
                label=item.get("label") or "",
                digest=item.get("digest") or "",
                uploader=(item.get("uploader") or {}).get("login") or "",
            )
            for item in map(json.loads, output.splitlines())
        ]

    def create_release(self, tag: str) -> None:
        self._run(
            "release",
            "create",
            tag,
            "--repo",
            self.repository,
            "--title",
            tag,
            "--latest=false",
            "--notes",
            f"Debian package storage for '{tag}' of the SFG APT repository. "
            "Maintained by CI; do not upload or delete assets manually.",
        )

    def upload(self, tag: str, files: list[tuple[Path, str]]) -> None:
        """Upload files with labels. Never overwrites: --clobber is intentionally not used."""
        self._run(
            "release",
            "upload",
            tag,
            "--repo",
            self.repository,
            *(f"{filepath}#{label}" for filepath, label in files),
        )

    def download(self, tag: str, directory: Path) -> None:
        self._run(
            "release",
            "download",
            tag,
            "--repo",
            self.repository,
            "--dir",
            str(directory),
            "--pattern",
            "*.deb",
        )


def tag_prefix_of_branch(branch: str) -> str:
    """Return the tag prefix for a branch of this repository: none for main, "test-" otherwise."""
    return "" if branch == PRODUCTION_BRANCH else TEST_TAG_PREFIX


class PackageRelease:
    """One GitHub release holding packages for one Ubuntu version, e.g. "jammy".

    The release "common" is the exception: it holds packages for all Ubuntu versions.

    Its asset list is read once and cached until the release is changed through this object.
    """

    def __init__(self, store: "PackageStore", name: str) -> None:
        self.store = store
        self.name = name
        self.tag = f"{store.tag_prefix}{name}"
        self._assets: list[GitHubReleaseAsset] | None = None

    def assets(self) -> list[GitHubReleaseAsset]:
        """Return the assets of the release, or an empty list if it does not exist yet."""
        if self._assets is None:
            release_id = self.store.api.release_id(self.tag)
            self._assets = (
                [] if release_id is None else self.store.api.assets(release_id)
            )
        return self._assets

    def check_package(self, filename: str, digest: str | None) -> PackageCheck:
        """Compare a package with the assets of the release.

        A digest of None means the content is unknown, e.g. before building; an existing label then
        counts as DIFFERENT.
        """
        assets = self.assets()
        stored_name = github_release_asset_name(filename)
        for asset in assets:
            matches = asset.label == filename or asset.name == stored_name
            if matches and asset.uploader != self.store.trusted_uploader:
                return PackageCheck(
                    PackageStatus.UNTRUSTED,
                    self.tag,
                    filename,
                    conflicting_asset=asset.label or asset.name,
                    uploader=asset.uploader,
                )

        for asset in assets:
            if asset.label == filename:
                if digest is not None and asset.digest == f"sha256:{digest}":
                    return PackageCheck(PackageStatus.IDENTICAL, self.tag, filename)
                return PackageCheck(PackageStatus.DIFFERENT, self.tag, filename)

        for asset in assets:
            if asset.name == stored_name:
                if not asset.label:
                    return PackageCheck(
                        PackageStatus.UNLABELED,
                        self.tag,
                        filename,
                        conflicting_asset=asset.name,
                    )
                return PackageCheck(
                    PackageStatus.COLLISION,
                    self.tag,
                    filename,
                    conflicting_asset=asset.label,
                )

        return PackageCheck(PackageStatus.NEW, self.tag, filename)

    def ensure_exists(self) -> None:
        """Create this release on GitHub if it does not exist yet, so assets can be added.

        Creates only the one release this object stands for, e.g. "jammy", "common" or on test
        branches "test-jammy". A release is created on the first upload of a package to it.
        """
        if self.store.api.release_id(self.tag) is None:
            print(f"Creating release '{self.tag}'.")
            self.store.api.create_release(self.tag)
            self._assets = None

    def upload(self, files: list[tuple[Path, str]]) -> None:
        """Upload files with labels. Never overwrites existing assets."""
        try:
            self.store.api.upload(self.tag, files)
        finally:
            self._assets = None

    def download(self, directory: Path) -> list[Path]:
        """Download the packages into a directory, named by their labels and verified by digest."""
        directory.mkdir(parents=True, exist_ok=True)
        assets = [asset for asset in self.assets() if asset.name.endswith(".deb")]
        if not assets:
            return []

        # Refuse to publish anything that didn't come through CI, before downloading anything.
        trusted_uploader = self.store.trusted_uploader
        untrusted = [
            f"'{asset.name}' (uploaded by '{asset.uploader}')"
            for asset in assets
            if asset.uploader != trusted_uploader
        ]
        if untrusted:
            raise ReleaseError(
                f"'{self.tag}' has assets that were not uploaded by '{trusted_uploader}': "
                f"{', '.join(untrusted)}. Delete them; only packages uploaded by CI are published."
            )

        filepaths = []
        with tempfile.TemporaryDirectory() as download_directory:
            self.store.api.download(self.tag, Path(download_directory))
            for asset in assets:
                if not asset.label:
                    raise ReleaseError(
                        f"Asset '{asset.name}' in '{self.tag}' has no label. Assets must only be "
                        "uploaded by CI."
                    )
                downloaded_filepath = Path(download_directory) / asset.name
                if f"sha256:{sha256(downloaded_filepath)}" != asset.digest:
                    raise ReleaseError(
                        f"Asset '{asset.name}' in '{self.tag}' does not match its digest "
                        f"'{asset.digest}'."
                    )
                filepath = directory / asset.label
                shutil.move(downloaded_filepath, filepath)
                filepaths.append(filepath)

        print(f"Downloaded {len(filepaths)} package(s) from '{self.tag}'.")
        return filepaths


class PackageStore:
    """All package releases of either the production or the test setup.

    Production (branch main): the releases "common", "jammy", "noble", ...
    Test (every other branch): the same releases with "test-" in front, e.g. "test-jammy". The
    tag prefix ("" or "test-") is the only difference, so test runs never touch production.

    Each release is a PackageRelease.
    """

    def __init__(
        self,
        api: ReleaseApi,
        tag_prefix: str,
        trusted_uploader: str = TRUSTED_UPLOADER,
    ) -> None:
        self.api = api
        self.tag_prefix = tag_prefix
        self.trusted_uploader = trusted_uploader
        self._releases: dict[str, PackageRelease] = {}

    @classmethod
    def for_branch(cls, branch: str) -> "PackageStore":
        """Return the store of this repository's releases for a branch of this repository."""
        return cls(GitHubReleaseClient(REPOSITORY), tag_prefix_of_branch(branch))

    def release(self, name: str) -> PackageRelease:
        """Return the release with a name, e.g. "jammy" or "common". It may not exist yet."""
        validate_release_name(name)
        if name not in self._releases:
            self._releases[name] = PackageRelease(self, name)
        return self._releases[name]

    def distributions(self) -> list[str]:
        """Return the names of all distribution releases, i.e. every release except "common"."""
        pattern = re.compile(rf"^{re.escape(self.tag_prefix)}([a-z]+)$")
        names = [
            match.group(1)
            for match in map(pattern.match, self.api.release_tags())
            if match
        ]
        return sorted(name for name in names if name != COMMON_RELEASE_NAME)


def validate_release_name(release_name: str) -> None:
    if not RELEASE_NAME_PATTERN.match(release_name):
        raise ReleaseError(
            f"Invalid release name '{release_name}'. Use a lowercase distribution codename or "
            f"'{COMMON_RELEASE_NAME}'."
        )


def release_name_of_distribution(distribution: str) -> str:
    """Map a submitted distribution to its release name: "all" means the common release."""
    if distribution == ALL_DISTRIBUTIONS:
        return COMMON_RELEASE_NAME
    if distribution == COMMON_RELEASE_NAME or not RELEASE_NAME_PATTERN.match(
        distribution
    ):
        raise ReleaseError(
            f"Invalid distribution '{distribution}'. Use a lowercase Ubuntu codename (e.g. jammy) "
            f"or '{ALL_DISTRIBUTIONS}'."
        )
    return distribution


def upload_packages(
    store: PackageStore, release_name: str, filepaths: list[Path]
) -> None:
    """Upload Debian packages to a release of the store.

    Every package is validated before anything is uploaded:
      - It must be a valid Debian package; it is uploaded under its canonical
        filename, which is also its label.
      - An asset with the same label and SHA-256 is skipped, so workflow retries succeed.
      - An asset with the same label but different content fails: the version must be bumped.
      - A different package with the same asset name after GitHub sanitization fails.
      - The same package must not be stored both in the common release and in a distribution
        release, because both are published into the same distribution.
    """
    release = store.release(release_name)
    if not filepaths:
        raise ReleaseError(f"No packages to upload to '{release.tag}'.")

    # Packages of the common release are published into every distribution and vice versa.
    if release_name == COMMON_RELEASE_NAME:
        other_releases = [store.release(name) for name in store.distributions()]
    else:
        other_releases = [store.release(COMMON_RELEASE_NAME)]

    errors: list[str] = []
    seen: dict[str, Path] = {}
    to_upload: list[tuple[Path, str]] = []

    for filepath in filepaths:
        try:
            filename = canonical_name(filepath)
        except InvalidPackageError as error:
            errors.append(str(error))
            continue

        if filename in seen:
            errors.append(f"'{filepath}' and '{seen[filename]}' are both '{filename}'.")
            continue
        seen[filename] = filepath

        digest = sha256(filepath)
        check = release.check_package(filename, digest)
        if check.status == PackageStatus.IDENTICAL:
            print(
                f"Skipping '{filename}': it already exists in '{release.tag}' with identical "
                "content."
            )
            continue
        if message := check.blocking_error():
            errors.append(message)
            continue

        overlapping_tags = [
            other.tag
            for other in other_releases
            if other.check_package(filename, digest).exists
        ]
        if overlapping_tags:
            errors.append(
                f"'{filename}' already exists in {', '.join(map(repr, overlapping_tags))}. A "
                f"package must be stored either in '{store.release(COMMON_RELEASE_NAME).tag}' or "
                "in distribution releases, not both."
            )
            continue

        to_upload.append((filepath, filename))

    if errors:
        details = "\n".join(f"  - {error}" for error in errors)
        raise ReleaseError(
            f"{len(errors)} package(s) failed validation. Nothing was uploaded to "
            f"'{release.tag}'.\n{details}"
        )

    if not to_upload:
        print(f"No new packages to upload to '{release.tag}'.")
        return

    release.ensure_exists()
    asset_count = len(release.assets()) + len(to_upload)
    if asset_count > ASSET_LIMIT:
        raise ReleaseError(
            f"'{release.tag}' would exceed GitHub's limit of {ASSET_LIMIT} assets per release. "
            "Prune old package versions first."
        )

    print(f"Uploading {len(to_upload)} package(s) to '{release.tag}':")
    with tempfile.TemporaryDirectory() as staging_directory:
        # Upload under the canonical filename, so the stored asset name matches the
        # label as closely as GitHub allows.
        staged: list[tuple[Path, str]] = []
        for filepath, filename in to_upload:
            print(f"  {filename}")
            staged_filepath = Path(staging_directory) / filename
            shutil.copyfile(filepath, staged_filepath)
            staged.append((staged_filepath, filename))
        try:
            release.upload(staged)
        except ReleaseError as error:
            raise ReleaseError(
                f"{error}\nRe-run to retry; packages that were already uploaded are skipped."
            ) from error

    if asset_count >= ASSET_WARNING_THRESHOLD:
        print(
            f"Warning: '{release.tag}' has {asset_count} of at most {ASSET_LIMIT} assets. "
            "Prune old package versions."
        )


def download_packages(store: PackageStore, packages_directory: Path) -> None:
    """Recreate packages/<distribution>/ from the releases of the store.

    The common packages are hard-linked into every distribution directory.
    """
    distributions = store.distributions()
    if not distributions:
        raise ReleaseError(
            f"No distribution releases found for prefix '{store.tag_prefix}'."
        )

    if packages_directory.exists():
        shutil.rmtree(packages_directory)
    common = store.release(COMMON_RELEASE_NAME)
    with tempfile.TemporaryDirectory(dir=packages_directory.parent) as common_directory:
        common_filepaths = common.download(Path(common_directory))
        for distribution in distributions:
            release = store.release(distribution)
            distribution_directory = packages_directory / distribution
            release.download(distribution_directory)
            for common_filepath in common_filepaths:
                target_filepath = distribution_directory / common_filepath.name
                if target_filepath.exists():
                    raise ReleaseError(
                        f"'{common_filepath.name}' exists in both '{common.tag}' and "
                        f"'{release.tag}'."
                    )
                os.link(common_filepath, target_filepath)
            print(
                f"Added {len(common_filepaths)} common package(s) to '{distribution_directory}'."
            )
