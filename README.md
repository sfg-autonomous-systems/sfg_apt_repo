# SFG APT Repo

This repository hosts the official APT packages for SFG Autonomous Systems. The packages contained in this repository are generated via GitHub Actions and hosted via GitHub Pages.

## For Users: Adding This Repository to Your System

### Add the APT Repository

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

### Configure `rosdep`

If you are developing ROS packages that depend on custom SFG packages, you need to tell `rosdep` where to find our custom dependency rules. We provide a helper package that automatically configures this for you. Run the following commands to install the index and update your local `rosdep` cache:

```bash
# Install the custom rosdep index.
sudo apt install -y sfg-rosdep-index
# Update rosdep so it fetches our custom rules.
rosdep update
```

Once completed, you can use `rosdep install` in your workspaces as usual, and it will automatically resolve our custom `ros-*` APT packages!

## For Developers: Publishing Packages

> [!important]
> This repository is completely automated. **Do not commit package files manually.**

To publish a package to this repository, your worker repository must build the package, and then call this repository's GitHub Action to securely submit it.

### Prerequisites

Your repository must have access to the following organization-level secrets:
* `SFG_APT_REPO_DISPATCHER_APP_ID`
* `SFG_APT_REPO_DISPATCHER_APP_PRIVATE_KEY`

### Example GitHub Actions Workflow

Add the following structure to `.github/workflows/build_and_submit_packages.yaml` inside your own repository:

```yaml
name: Build and Submit Package(s)

on:
  push:
    branches: [main]
    tags: [v*.*.*]

permissions:
  attestations: write
  contents: read
  id-token: write

jobs:
  build:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      
      # 1. Build your package(s)...
      # run: ...
      
      # 2. Submit the built package(s) to the SFG APT repository.
      - name: Submit Package(s)
        uses: sfg-autonomous-systems/sfg_apt_repo/.github/actions/submit_packages@main
        with:
          dispatcher_app_id: ${{ secrets.SFG_APT_REPO_DISPATCHER_APP_ID }}
          dispatcher_app_private_key: ${{ secrets.SFG_APT_REPO_DISPATCHER_APP_PRIVATE_KEY }}
          distribution: jammy
          path: ./*.deb
```

## For Admins: Setup Instructions

This repository relies on a two-app architecture. This ensures worker repositories can request a package upload, but only the central repository has the cryptographic authority to download, verify, and commit the packages.

### Set Up the Dispatcher App `sfg-apt-repo-dispatcher`

1. Navigate to the organization's **Settings** > **Developer settings** > **GitHub Apps**.
2. Click **New GitHub App** and configure the following properties:
    | Setting                                     | Value                                                    |
    | ------------------------------------------- | -------------------------------------------------------- |
    | **GitHub App name**                         | `sfg-apt-repo-dispatcher`                                |
    | **Homepage URL**                            | `https://github.com/sfg-autonomous-systems/sfg_apt_repo` |
    | **Webhook > Active**                        | Unchecked                                                |
    | **Permissions > Repository permissions**    | Set **Actions** to **Read and write**.                   |
    | **Where can this GitHub App be installed?** | `Only on this account`                                   |
3. Click **Create GitHub App**.
4. Save the **App ID** and generate a **Private key** (`.pem` file).
5. In the left sidebar, click **Install App** and install it **only** on this repository.
6. Navigate to the organization's **Settings** > **Secrets and variables** > **Actions** and add the following organization secrets:
    | Name                                      | Value                                                        | Repository access |
    | ----------------------------------------- | ------------------------------------------------------------ | ----------------- |
    | `SFG_APT_REPO_DISPATCHER_APP_ID`          | Paste the app ID copied previously.                          | All repositories  |
    | `SFG_APT_REPO_DISPATCHER_APP_PRIVATE_KEY` | Paste the **entire** contents of the downloaded `.pem` file. | All repositories  |
7. Delete the downloaded `.pem` file.

### Set Up the Uploader App (`sfg-apt-repo-uploader`)

1. Navigate to the organization's **Settings** > **Developer settings** > **GitHub Apps**.
2. Click **New GitHub App** and configure the following properties:
    | Setting                                     | Value                                                                        |
    | ------------------------------------------- | ---------------------------------------------------------------------------- |
    | **GitHub App name**                         | `sfg-apt-repo-uploader`                                                      |
    | **Homepage URL**                            | `https://github.com/sfg-autonomous-systems/sfg_apt_repo`                     |
    | **Webhook > Active**                        | Unchecked                                                                    |
    | **Permissions > Repository permissions**    | Set **Contents** to **Read and write**.<br>Set **Actions** to **Read-only**. |
    | **Where can this GitHub App be installed?** | `Only on this account`                                                       |
3. Click **Create GitHub App**.
4. Save the **App ID** and generate a **Private key** (`.pem` file).
5. In the left sidebar, click **Install App** and install it on all repositories.
6. Navigate to the organization's **Settings** > **Secrets and variables** > **Actions** and add the following organization:
    | Name                                    | Value                                                        | Repository access |
    | --------------------------------------- | ------------------------------------------------------------ | ----------------- |
    | `SFG_APT_REPO_UPLOADER_APP_ID`          | Paste the app ID copied previously.                          | Selected repositories > this repository   |
    | `SFG_APT_REPO_UPLOADER_APP_PRIVATE_KEY` | Paste the **entire** contents of the downloaded `.pem` file. | Selected repositories > this repository   |

### Allow the Uploader App to Commit to Protected Branches

As outlined in our [access and security policy](https://github.com/sfg-autonomous-systems/sfg_docs/blob/main/docs/access_and_security_policy.md), certain branches cannot be pushed to directly. To allow the uploader app to push new packages, you must explicitly allow it to bypass this protection:

1. Navigate to this organization's **Settings** > **Repository** > **Rulesets** and click on the ruleset that was imported as part of the access and security policy.
2. Under **Bypass list** click **Add bypass** and select the `sfg-apt-repo-uploader` app.
3. Select **Save changes** to persist the bypass.

### Configure GPG Repository Signing

> [!important]
> Once the GPG key is generated and the secret is created, delete the private key from your local machine. If the key is ever lost or compromised, do not attempt to recover it; generate a new key and update the secret instead.

Aptly requires a passphrase-less GPG key to sign the repository automatically during the GitHub Actions deployment.

1. Run the following on a secure local machine to generate a GPG key:
    ```bash
    cat >"key-config" <<EOF
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