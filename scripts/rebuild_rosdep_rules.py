#!/usr/bin/env python3
"""Generate rosdep rules and validate rosdep source list entries.

The script scans packages/<ubuntu-distro>/*.deb, reads each Debian package
name, and converts ROS package names such as ros-humble-sfg-utils into a
rosdep key named sfg_utils under the humble distribution. The Ubuntu package
mapping is written to github-pages/rosdep/<ros-distro>.yaml. Matching
rosdep rules from rosdep/<ros-distro>.yaml files are merged into those
generated rules before they are written.

The script also validates that the rosdep source list contains entries for
each ROS distribution with generated rosdep rules.

References:
    Rosdep sources list format: https://docs.ros.org/en/independent/api/rosdep/html/sources_list.html
    Rosdep YAML format: https://docs.ros.org/en/independent/api/rosdep/html/rosdep_yaml_format.html
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
    item is added only once. For other value types, an error is raised if the
    key already exists in the target.
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
            if key in target:
                raise ValueError(f"Key '{key}' already exists in target dictionary")
            target[key] = value


def discover_ros_deb_packages(packages_directory: Path) -> list[RosDebPackage]:
    rosdep_rules: list[RosDebPackage] = []

    if not packages_directory.exists():
        return rosdep_rules

    for ubuntu_distro_directory in packages_directory.iterdir():
        if not ubuntu_distro_directory.is_dir():
            continue

        for package_filepath in ubuntu_distro_directory.glob("*.deb"):
            # Read the package name from Debian metadata instead of relying on
            # the filename, which may include version and architecture suffixes.
            try:
                output = subprocess.check_output(
                    ["dpkg-deb", "-f", package_filepath.as_posix(), "Package"],
                    text=True,
                )
                apt_package = output.strip()
            except subprocess.CalledProcessError:
                print(f"Error: Failed to read package name from {package_filepath}.")
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
                ubuntu_distro=ubuntu_distro_directory.name
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

        print(f"Adding rosdep rule for {pkg.ubuntu_distro}: {pkg.ros_package} -> {pkg.apt_package}")
        rosdep_rules[pkg.ros_distro][pkg.ros_package]["ubuntu"][pkg.ubuntu_distro] = [pkg.apt_package]

    # Only merge rules from rosdep folder for distros with discovered Debian packages.
    for ros_distro in rosdep_rules:
        custom_rules_path = Path(__file__).parent / f"rosdep/{ros_distro}.yaml"
        if custom_rules_path.is_file():
            with open(custom_rules_path) as file:
                custom_rules = yaml.safe_load(file) or {}
            try:
                merge_rules(rosdep_rules[ros_distro], custom_rules)
                print(f"Merged custom rosdep rules for {ros_distro} from {custom_rules_path}")
            except ValueError as e:
                print(f"Error: {e}")
                print(f"Conflict in custom rules file {custom_rules_path}")
                sys.exit(1)

    output_directory = Path(__file__).parent.parent / "github-pages/rosdep"
    output_directory.mkdir(parents=True, exist_ok=True)

    rosdep_source_list_path = (
        Path(__file__).parent.parent
        / "src/sfg-rosdep-index/etc/ros/rosdep/sources.list.d/10-sfg-rosdep-index.list"
    )
    if not rosdep_source_list_path.is_file():
        print(f"Error: The file {rosdep_source_list_path} does not exist.")
        sys.exit(1)

    rosdep_source_list = ""
    with open(rosdep_source_list_path, "r") as file:
        rosdep_source_list = "".join(file.readlines())

    # Every discovered ROS distribution must have a matching rosdep entry.
    for ros_distro in rosdep_rules.keys():
        if ros_distro not in rosdep_source_list:
            print(f"Error: The rosdep source list does not contain an entry for {ros_distro}.")
            print(f"Add the following line to {rosdep_source_list_path}:")
            print(f"yaml https://sfg-autonomous-systems.github.io/sfg_apt_repo/rosdep/{ros_distro}.yaml {ros_distro}")
            sys.exit()

    for ros_distro in rosdep_rules:
        # Generate one rosdep rules file per ROS distribution because
        # rosdep selects the matching entry by its distribution tag.
        with open(output_directory / f"{ros_distro}.yaml", "w") as file:
            yaml.dump(rosdep_rules[ros_distro], file)
            print(f"Generated rosdep rules for {ros_distro}")


if __name__ == "__main__":
    main()
