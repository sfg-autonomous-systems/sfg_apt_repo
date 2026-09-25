#!/usr/bin/env python3
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml


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


def main() -> None:
    packages_directory = Path(__file__).parent.parent / "packages"
    rosdep_rules: dict[str, Any] = {}

    if not packages_directory.exists():
        return

    for distribution_directory in packages_directory.iterdir():
        if not distribution_directory.is_dir():
            continue

        distribution_name = distribution_directory.name

        for package_filepath in distribution_directory.glob("*.deb"):
            try:
                output = subprocess.check_output(
                    ["dpkg-deb", "-f", package_filepath.as_posix(), "Package"],
                    text=True,
                )
                apt_package = output.strip()
            except subprocess.CalledProcessError:
                continue

            match = re.match(r"^ros-[a-z]+-(.*)$", apt_package)

            if not match:
                continue

            ros_package = match.group(1).replace("-", "_")

            if ros_package not in rosdep_rules:
                rosdep_rules[ros_package] = {"ubuntu": {}}

            print(f"Adding rosdep rule for {ros_package} on {distribution_name}: {apt_package}")
            rosdep_rules[ros_package]["ubuntu"][distribution_name] = [apt_package]

    custom_rules_filepath = Path(__file__).parent / "custom_rosdep_rules.yaml"
    if custom_rules_filepath.exists():
        with open(custom_rules_filepath) as file:
            custom_rules = yaml.safe_load(file) or {}
        merge_rules(rosdep_rules, custom_rules)

    # split generating rules and publishing
    output_directory = Path(__file__).parent.parent / "github-pages"
    output_directory.mkdir(parents=True, exist_ok=True)

    with open(output_directory / "rosdep_rules.yaml", "w") as file:
        yaml.dump(rosdep_rules, file)


if __name__ == "__main__":
    main()
