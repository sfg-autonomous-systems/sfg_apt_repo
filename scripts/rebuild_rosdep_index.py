#!/usr/bin/env python3
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml


def main() -> None:
    packages_directory = Path(__file__).parent.parent / "packages"
    rosdep_index: dict[str, Any] = {}

    if not packages_directory.exists():
        return

    for distribution_directory in packages_directory.iterdir():
        if not distribution_directory.is_dir():
            continue

        distribution_name = distribution_directory.name

        for package_file in distribution_directory.glob("*.deb"):
            try:
                output = subprocess.check_output(
                    ["dpkg-deb", "-f", str(package_file), "Package"], text=True
                )
                apt_package = output.strip()
            except subprocess.CalledProcessError:
                continue

            match = re.match(r"^ros-[a-z]+-(.*)$", apt_package)

            if not match:
                continue

            ros_package = match.group(1).replace("-", "_")

            if ros_package not in rosdep_index:
                rosdep_index[ros_package] = {
                    "ubuntu": {},
                    "debian": {},
                }

            rosdep_index[ros_package]["ubuntu"][distribution_name] = [apt_package]
            rosdep_index[ros_package]["debian"][distribution_name] = [apt_package]

    output_directory = Path(__file__).parent.parent / "github-pages"
    output_directory.mkdir(parents=True, exist_ok=True)

    with open(output_directory / "rosdep_rules.yaml", "w") as file:
        yaml.dump(rosdep_index, file, default_flow_style=False)


if __name__ == "__main__":
    main()
