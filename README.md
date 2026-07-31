# SFG APT Repo

This repository hosts the official APT packages for SFG Autonomous Systems. The repository is automatically generated and hosted via GitHub Pages.

## For Users: Adding this Repository to Your System

To install software from this repository, you need to add our public GPG key and configure APT to pull from our GitHub Pages site.

1. **Install Prerequisites**
    ```bash
    sudo apt update
    sudo apt install -y curl gpg
    ```

2. **Add the GPG Signing Key**
    ```bash
    curl -fsSL "https://sfg-autonomous-systems.github.io/sfg_apt_repo/sfg-apt-repo-public.gpg" | sudo gpg --dearmor -o "/usr/share/keyrings/sfg-apt-repo.gpg"
    ```

3. **Add the APT Repository**
    ```bash
    echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/sfg-apt-repo.gpg] https://sfg-autonomous-systems.github.io/sfg_apt_repo $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/sfg-apt-repo.list
    ```

4. **Update Package Lists**
    ```bash
    sudo apt update
    ```

## For Developers: Publishing Packages

> [!important]
> This repository is completely automated. **Do not commit `.deb` files manually.**

To publish a package to this repository, your worker repository must build the package, upload it as a temporary artifact, and then call this repository's reusable GitHub Action workflow. 

### Prerequisites

Your repository must have access to the `SFG_APT_REPO_PAT`.

### Example GitHub Actions Workflow

Add the following structure to `.github/workflows/example_workflow.yaml` inside your own repository:

```yaml
name: Example Workflow

on:
  push:
    tags:
      - 'v*.*.*'  # Example: Trigger on version tags.

jobs:
  build:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      
      # 1. Build package(s)...
      # run: ...
      
      # 2. Upload the built .deb file as a temporary artifact.
      - name: Upload Package Artifact
        uses: actions/upload-artifact@v4
        with:
          name: built-deb-packages  # An arbitrary upload name for the artifact.
          path: ./*.deb             # Path to your generated .deb files.
          retention-days: 1         # Only needed temporarily for the next job.

  publish:
    needs: build
    # 3. Call the reusable workflow in the APT repository.
    uses: sfg-autonomous-systems/sfg_apt_repo/.github/workflows/upload_packages.yaml@main
    with:
      package_artifact_name: 'built-deb-packages' # Must match the upload name above.
      distribution: 'jammy'                       # Target distro (e.g. 'jammy' or 'noble').
    secrets:
      SFG_APT_REPO_PAT: ${{ secrets.SFG_APT_REPO_PAT }}
```