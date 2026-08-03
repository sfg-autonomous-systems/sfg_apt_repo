# SFG APT Repo

This repository hosts the official APT packages for SFG Autonomous Systems. The packages contained in this repository are generated via GitHub Actions and hosted via GitHub Pages.

## For Users: Adding this Repository to Your System

To install software from this repository, you need to add our public GPG key and configure APT to pull from our GitHub Pages site:

```bash
# Install prerequisites.
sudo apt update && sudo apt install -y curl gpg
# Add the GPG signing key.
curl -fsSL "https://sfg-autonomous-systems.github.io/sfg_apt_repo/sfg-apt-repo-public.gpg" | sudo gpg --dearmor -o "/usr/share/keyrings/sfg-apt-repo.gpg"
# Add the APT repository.
echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/sfg-apt-repo.gpg] https://sfg-autonomous-systems.github.io/sfg_apt_repo $(lsb_release -cs) main" | sudo tee "/etc/apt/sources.list.d/sfg-apt-repo.list"
# Update package lists.
sudo apt update
```

## For Developers: Publishing Packages

> [!important]
> This repository is completely automated. **Do not commit `.deb` files manually.**

To publish a package to this repository, your worker repository must build the package, upload it as a temporary artifact, and then call this repository's reusable GitHub Action workflow. 

### Prerequisites

Your repository must have access to the following organization-level secrets:
* `SFG_APT_REPO_UPLOADER_APP_ID`
* `SFG_APT_REPO_UPLOADER_APP_PRIVATE_KEY`

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
      package_artifact_name: built-deb-packages # Must match the upload name above.
      distribution: jammy                       # Target distro (e.g. 'jammy' or 'noble').
    secrets:
      SFG_APT_REPO_UPLOADER_APP_ID: ${{ secrets.SFG_APT_REPO_UPLOADER_APP_ID }}
      SFG_APT_REPO_UPLOADER_APP_PRIVATE_KEY: ${{ secrets.SFG_APT_REPO_UPLOADER_APP_PRIVATE_KEY }}
```

## For Admins: Setup Instructions

This repository relies on a custom GitHub App to securely authenticate and commit new `.deb` packages automatically.

### Setup the GitHub App

1. Navigate to the organization's **Settings** > **Developer settings** > **GitHub Apps**.
2. Click **New GitHub App** and configure the following properties:
    | Setting                                     | Value                                                    |
    | ------------------------------------------- | -------------------------------------------------------- |
    | **GitHub App name**                         | `sfg-apt-repo-uploader`                                  |
    | **Homepage URL**                            | `https://github.com/sfg-autonomous-systems/sfg_apt_repo` |
    | **Webhook > Active**                        | Unchecked                                                |
    | **Permissions > Repository permissions**    | Set **Contents** to **Read and write**                   |
    | **Where can this GitHub App be installed?** | `Only on this account`                                   |
3. Click **Create GitHub App**.
4. On the resulting page, copy the **App ID** from the **About** section and save it temporarily.
5. Scroll down to **Private keys** and click **Generate a private key**. A `.pem` file will download to your machine.

### Configure Organization Secrets

> [!important]
> Once the organization secret is created, delete the downloaded `.pem` file. If the key is ever lost or compromised, do not attempt to recover it; generate a new key and update the secret instead.

1. Navigate to the organization's **Settings** > **Secrets and variables** > **Actions** and add the following secrets:
    | Name                           | Value                                                                 |
    | ------------------------------ | --------------------------------------------------------------------- |
    | `SFG_APT_REPO_UPLOADER_APP_ID` | Paste the app ID copied previously.                                   |
    | `SFG_APT_REPO_UPLOADER_APP_PRIVATE_KEY` | Paste the **entire** contents of the downloaded `.pem` file. |
2. Under **Repository access**, ensure these secrets are accessible by this repository as well as any other worker repositories that will be calling the upload workflow.

### Allow `sfg-apt-repo-uploader` to Commit the Protected Main Branch

As outlined in our [access and security policy](https://github.com/sfg-autonomous-systems/sfg_docs/blob/main/docs/access_and_security_policy.md), the branch named `main` (among others) cannot be pushed to directly. To allow the GitHub App to commit new packages, you must explicitly allow it to bypass this protection:

1. Navigate to this organization's **Settings** > **Repository** > **Rulesets** and click on the ruleset that was imported as part of the access and security policy.
2. Under **Bypass list** click **Add bypass** and select the `sfg-apt-repo-uploader` app.

### Install the App

> [!note]
> The GitHub App itself only needs to be installed on the repository it pushes to, not the repositories that trigger the workflow.

1. Navigate back to the organization's **Settings** > **Developer settings** > **GitHub Apps** and click on **Edit** next to the `sfg-apt-repo-uploader` app.
2. In the left sidebar, click **Install App**.
3. Click **Install** next to the `sfg-autonomous-systems` organization.
4. Under **Repository access** check **Only select repositories** and explicitly select `sfg_apt_repo`.
5. Click **Install**.

### Configure GPG Repository Signing

> [!important]
> Once the GPG key is generated and the secret is created, delete the private key from your local machine. If the key is ever lost or compromised, do not attempt to recover it; generate a new key and update the secret instead.

Aptly requires a passphrase-less GPG key to sign the repository automatically during the GitHub Actions deployment.

1. Run the following on a secure local machine to generate a GPG key:
    ```bash
    cat > key-config <<EOF
        %echo Generating a standard key
        Key-Type: default
        Subkey-Type: default
        Name-Real: SFG APT Repo
        Name-Email: projekt-sfg-autonomous-systems@hs-esslingen.de
        Expire-Date: 0
        %no-protection
        %commit
        %echo done
    EOF

    gpg --batch --generate-key "key-config"
    rm "key-config"
    ```
2. Run `gpg --list-secret-keys --keyid-format=long` and note down the 16-character key ID.
3. Run `gpg --armor --export-secret-keys <YOUR_KEY_ID>` and copy the GPG private key.
4. Navigate to this repository's **Settings** > **Secrets and variables** > **Actions** and add the following secrets:
    | Name              | Value                    |
    | ----------------- | ------------------------ |
    | `GPG_KEY_ID`      | The 16-character key ID. |
    | `GPG_PRIVATE_KEY` | The GPG private key.     |