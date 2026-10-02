#!/usr/bin/env python3
"""Generate rosdep rules and the rosdep source list for the APT repository.

The script scans packages/<ubuntu-distro>/*.deb, reads each Debian package
name, and converts ROS package names such as ros-humble-sfg-utils into a
rosdep key named sfg_utils under the humble distribution. The Ubuntu package
mapping is written to github-pages/rosdep_rules_<ros-distro>.yaml. Matching
custom_rosdep_rules_<ros-distro>.yaml files are merged into those generated
rules before they are written.

The source list file installed by the sfg-rosdep-index package is regenerated
with one entry per ROS distribution. Each entry has the form::

        yaml <rules-url> <ros-distro>

The final field is the distribution tag used by rosdep to select the matching
rules source. The YAML files contain rosdep keys and their installers, for
example an Ubuntu APT mapping::

        sfg_utils:
            ubuntu:
                noble:
                    - ros-jazzy-sfg-utils

References:
        Rosdep sources list format:
        https://docs.ros.org/en/independent/api/rosdep/html/sources_list.html
        Rosdep YAML format:
        https://docs.ros.org/en/independent/api/rosdep/html/rosdep_yaml_format.html
"""

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class RosDebPackage:
    ros_package: str
    ros_distro: str
    apt_package: str
    ubuntu_distro: str


def merge_rules(target: dict[str, Any], source: dict[str, Any]) -> None:
    """Merge custom rules into generated rules in place.

    Nested dictionaries are merged recursively so existing sections are
    preserved. Matching lists are combined in their original order, and each
    item is added only once. For other value types, the source value replaces
    the value already present in the target.
    """

    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge_rules(target[key], value)
        elif isinstance(value, list) and isinstance(target.get(key), list):
            # Merge lists in order while avoiding duplicate entries.
            for item in value:
                if item not in target[key]:
                    target[key].append(item)
        else:
            target[key] = value


def discover_ros_deb_packages(packages_directory: Path) -> list[RosDebPackage]:
    rosdep_rules: list[RosDebPackage] = []

    if not packages_directory.exists():
        return rosdep_rules

    for ubuntu_distro_dir in packages_directory.iterdir():
        if not ubuntu_distro_dir.is_dir():
            continue

        for package_filepath in ubuntu_distro_dir.glob("*.deb"):
            # Read the package name from Debian metadata instead of relying on
            # the filename, which may include version and architecture suffixes.
            try:
                output = subprocess.check_output(
                    ["dpkg-deb", "-f", package_filepath.as_posix(), "Package"],
                    text=True,
                )
                apt_package = output.strip()
            except subprocess.CalledProcessError:
                print(f"Error: Failed to read package name from {package_filepath}")
                sys.exit(1)

            match = re.match(r"^ros-([a-z]+)-(.*)$", apt_package)
            if not match:
                continue

            ros_distro = match.group(1)
            # rosdep keys use underscores while Debian package names use hyphens.
            ros_package = match.group(2).replace("-", "_")

            rosdep_rules.append(RosDebPackage(
                ros_package=ros_package,
                ros_distro=ros_distro,
                apt_package=apt_package,
                ubuntu_distro=ubuntu_distro_dir.name
            ))
    return rosdep_rules


def main() -> None:
    packages_directory = Path(__file__).parent.parent / "packages"
    rosdep_rules: dict[str, Any] = {}

    for pkg in discover_ros_deb_packages(packages_directory):
        if pkg.ros_distro not in rosdep_rules:
            rosdep_rules[pkg.ros_distro] = {}

        if pkg.ros_package not in rosdep_rules[pkg.ros_distro]:
            rosdep_rules[pkg.ros_distro][pkg.ros_package] = {"ubuntu": {}}

        print(f"Adding rosdep rule for {pkg.ros_package} on {pkg.ubuntu_distro}: {pkg.apt_package}")
        rosdep_rules[pkg.ros_distro][pkg.ros_package]["ubuntu"][pkg.ubuntu_distro] = [pkg.apt_package]

    # Only merge custom rules for distros with discovered Debian packages.
    # Custom-only distros are intentionally not published for now.
    for ros_distro in rosdep_rules:
        custom_rules_path = Path(__file__).parent / f"custom_rosdep_rules_{ros_distro}.yaml"
        if custom_rules_path.exists():
            with open(custom_rules_path) as file:
                custom_rules = yaml.safe_load(file) or {}
            merge_rules(rosdep_rules[ros_distro], custom_rules)
            print(f"Merged custom rosdep rules for {ros_distro} from {custom_rules_path}")

    output_directory = Path(__file__).parent.parent / "github-pages"
    output_directory.mkdir(parents=True, exist_ok=True)

    rosdep_source_list_path = (
        Path(__file__).parent.parent
        / "src/sfg-rosdep-index/etc/ros/rosdep/sources.list.d/10-sfg-rosdep-index.list"
    )
    if not rosdep_source_list_path.is_file():
        print(f"Error: The file {rosdep_source_list_path} does not exist.")
        sys.exit(1)

    rosdep_source_list = ""
    for ros_distro in rosdep_rules:
        # Generate one rosdep rules file and one source list entry per ROS distribution because
        # rosdep selects the matching entry by its distribution tag.
        with open(output_directory / f"rosdep_rules_{ros_distro}.yaml", "w") as file:
            yaml.dump(rosdep_rules[ros_distro], file)
            print(f"Generated rosdep rules for {ros_distro} at 'rosdep_rules_{ros_distro}.yaml'")

        rosdep_source_list += (
            "yaml https://sfg-autonomous-systems.github.io/sfg_apt_repo/"
            f"rosdep_rules_{ros_distro}.yaml {ros_distro}\n"
        )
        print(f"Added rosdep source list entry for {ros_distro}")

    with open(rosdep_source_list_path, "w") as file:
        file.write(rosdep_source_list)
        print(f"Generated rosdep source list at '{rosdep_source_list_path}'")


if __name__ == "__main__":
    main()
