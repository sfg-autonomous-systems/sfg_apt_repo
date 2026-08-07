#!/usr/bin/env python3
import os
import sys
from pathlib import Path

index_template = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Directory Listing</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.5.0/github-markdown.css">
  <style>
    .markdown-body { box-sizing: border-box; min-width: 200px; max-width: 800px; margin: 0 auto; padding: 45px; }
    .markdown-body ul { list-style: none; }
    .markdown-body li { font-family: monospace; }
  </style>
</head>
<body class="markdown-body">
  <h1>SFG APT Repo</h1>
  <p>This repository hosts the official APT packages for <a href="https://github.com/sfg-autonomous-systems">SFG Autonomous Systems</a>. View the <a href="https://github.com/sfg-autonomous-systems/sfg_apt_repo#for-users-adding-this-repository-to-your-system">documentation</a> to learn how to add this repository to your system.</p>
  <h2>Directory Listing</h2>
  <ul>
    {{ index_contents }}
  </ul>
</body>
</html>"""


def main(base_directory: Path) -> None:
    base_directory = base_directory.resolve()

    for root, directories, files in os.walk(base_directory):
        current_directory = Path(root)
        directories.sort()
        files.sort()
        list_items = []

        if current_directory != base_directory:
            list_items.append('<li>📁 <a href="../">../</a></li>')

        for directory in directories:
            list_items.append(f'<li>📁 <a href="{directory}/">{directory}/</a></li>')

        for file in [file for file in files if file != "index.html"]:
            list_items.append(f'<li>📄 <a href="{file}">{file}</a></li>')

        with open(current_directory / "index.html", "w") as index_file:
            index_file.write(
                index_template.replace(
                    "{{ index_contents }}", "\n    ".join(list_items)
                )
            )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
