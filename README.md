# SFG APT Repo

This repository hosts the official APT packages for SFG Autonomous Systems. The packages contained in this repository are generated via GitHub Actions and hosted via GitHub Pages.

## For Users: Adding This Repository to Your System

Follow below steps to install SFG packages on your Ubuntu machine.

### Add the APT Repository

To install software from this repository, you need to add our public GPG key and configure APT to pull from our GitHub Pages site:

```bash
# Install prerequisites.
sudo apt update && sudo apt install -y curl gpg
# Add the GPG signing key.
curl -fsSL "https://sfg-autonomous-systems.github.io/sfg_apt_repo/sfg-apt-repo-public.gpg" | sudo gpg --dearmor -o "/usr/share/keyrings/sfg-apt-repo.gpg"
# Add the APT repository.
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/sfg-apt-repo.gpg] https://sfg-autonomous-systems.github.io/sfg_apt_repo $(. /etc/os-release && echo "$VERSION_CODENAME") main" | sudo tee "/etc/apt/sources.list.d/sfg-apt-repo.list"
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
> This repository is completely automated. **Do not upload, edit or delete package files manually.**

To publish a package to this repository, your worker repository must build the package, and then call this repository's GitHub Action to securely submit it.

### Prerequisites

Your repository must have access to the following organization-level secrets:

* `SFG_APT_REPO_SUBMITTER_APP_CLIENT_ID`
* `SFG_APT_REPO_SUBMITTER_APP_PRIVATE_KEY`

> [!note]
> Only repositories that actually need to publish packages should have access to these secrets. If your repository needs to publish packages, ask an organization owner to grant it access to the secrets, see [Grant a Repository Access to the Submitter Secrets](#grant-a-repository-access-to-the-submitter-secrets).

### Example GitHub Actions Workflow

Add the following structure to `.github/workflows/build_and_submit_packages.yaml` inside your own repository:

```yaml
name: Build and Submit Package(s)

on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v7

      # 1. Build your package(s)...
      # run: ...

      # 2. Submit the built package(s) to the SFG APT repository.
      - name: Submit Package(s)
        uses: sfg-autonomous-systems/sfg_apt_repo/.github/actions/submit_packages@main
        with:
          submitter_app_client_id: ${{ secrets.SFG_APT_REPO_SUBMITTER_APP_CLIENT_ID }}
          submitter_app_private_key: ${{ secrets.SFG_APT_REPO_SUBMITTER_APP_PRIVATE_KEY }}
          distribution: jammy
          path: ./*.deb
```

### Action Inputs

| Input                       | Required                                 | Description                                                                                                |
| --------------------------- | ---------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `submitter_app_client_id`   | yes                                      | Client ID of the submitter GitHub App.                                                                     |
| `submitter_app_private_key` | yes                                      | Private key of the submitter GitHub App.                                                                   |
| `distribution`              | yes                                      | Target Ubuntu distribution, e.g. `jammy` or `noble`, or `all` for packages that are installable on every distribution. `all` stores the packages once in the `common` release. |
| `path`                      | exactly one of `path` or `artifact_name` | Path to the packages to upload. The action uploads them as an artifact.                                    |
| `artifact_name`             | exactly one of `path` or `artifact_name` | Name of an artifact the current run already uploaded. Skips the upload and submits that artifact directly. |

### Artifact Layout

The `.deb` files must be at the **root** of the artifact, with no subdirectories, for either input. The processing workflow downloads the artifact into `./submitted_packages` and discovers packages with the non-recursive glob `"submitted_packages/"*.deb`, so anything nested deeper is silently ignored. `upload-artifact` stores files relative to the least common ancestor of the search paths, so `path: dist/*.deb` yields a flat artifact (root = `dist`), whereas `path: dist/` would preserve the directory and break discovery.

### Package Storage

Packages are not stored in git. They are stored as assets of these GitHub releases:

| Release             | Contents                                                         | Published into         |
| ------------------- | ---------------------------------------------------------------- | ---------------------- |
| `common`            | Packages that are installable on every distribution, stored once | every distribution     |
| `jammy`, `noble`, … | Packages built for one Ubuntu distribution                       | that distribution only |

The [Publish Package(s)](.github/workflows/publish_packages.yaml) workflow downloads all releases and rebuilds the APT repository on GitHub Pages from them. A new distribution only needs its first submitted package. It then also gets every package of the `common` release.

Every upload is checked before anything is uploaded, see [scripts/package_storage.py](scripts/package_storage.py):

* A package version can only be uploaded once. Submitting identical content again, e.g. by re-running the processing workflow, is skipped. A rebuilt package is never identical, so different content under an existing version fails, increment the `Version` instead.
* A package must be stored either in `common` or in distribution releases, never both.
* Only assets uploaded by the `sfg-apt-repo-uploader` app are trusted. An asset uploaded by anyone else, e.g. by hand, blocks uploads of the same package and makes the publish workflow fail until it is deleted.
* GitHub replaces `~` and `:` in asset names with `.`. Each asset's label therefore holds the exact filename `<Package>_<Version>_<Architecture>.deb`. Two versions that only differ in these characters, e.g. `1.0.0~jammy1` and `1.0.0.jammy1`, can't both be stored.

Runs on branches other than `main` use separate releases with the `test-` prefix, e.g. `test-jammy`, and never touch the production releases.

### Internal Packages

Internal packages are owned by this repository, such as `sfg-rosdep-index`. They are defined in `src/<package>/` as a raw `dpkg-deb` tree with a `DEBIAN/control` file. The [Build Internal Packages](.github/workflows/build_internal_packages.yaml) workflow runs [scripts/build_internal_packages.py](scripts/build_internal_packages.py) and uploads every package version that is missing from its release. To release a change, bump `Version` in the package's `DEBIAN/control` file.

Each package is built once and stored in the `common` release, so it is published into every distribution.

## For Admins: Setup Instructions

This repository relies on a two-app architecture. This ensures worker repositories can request a package upload, but only the central repository has the cryptographic authority to download, verify, and store the packages.

### Set Up the Submitter App `sfg-apt-repo-submitter`

1. Navigate to the organization's **Settings** > **Developer settings** > **GitHub Apps**.
2. Click **New GitHub App** and configure the following properties:
    | Setting                                     | Value                                                    |
    | ------------------------------------------- | -------------------------------------------------------- |
    | **GitHub App name**                         | `sfg-apt-repo-submitter`                                 |
    | **Homepage URL**                            | `https://github.com/sfg-autonomous-systems/sfg_apt_repo` |
    | **Webhook > Active**                        | Unchecked                                                |
    | **Permissions > Repository permissions**    | Set **Actions** to **Read and write**.                   |
    | **Where can this GitHub App be installed?** | `Only on this account`                                   |
3. Click **Create GitHub App**.
4. Save the **Client ID**.
5. Go to **Credentials** > **Key pairs** and generate a new key (`.pem` file).
6. In the left sidebar, click **Install App** and install it **only** on this repository.
7. Navigate to the organization's **Settings** > **Secrets and variables** > **Actions** and add the following organization secrets:
    | Name                                     | Value                                                        | Repository access                                               |
    | ---------------------------------------- | ------------------------------------------------------------ | --------------------------------------------------------------- |
    | `SFG_APT_REPO_SUBMITTER_APP_CLIENT_ID`   | Paste the Client ID copied previously.                       | Selected repositories > only repositories that publish packages |
    | `SFG_APT_REPO_SUBMITTER_APP_PRIVATE_KEY` | Paste the **entire** contents of the downloaded `.pem` file. | Selected repositories > only repositories that publish packages |
8. Delete the downloaded `.pem` file.

### Grant a Repository Access to the Submitter Secrets

Do this when a repository starts publishing packages, and undo it when it stops.

1. Navigate to the organization's **Settings** > **Secrets and variables** > **Actions**.
2. Open the edit page of `SFG_APT_REPO_SUBMITTER_APP_CLIENT_ID`.
3. Under **Repository access**, add the repository to (or remove it from) the **Selected repositories**.
4. Click **Save changes**. You don't need to enter a new value.
5. Repeat this for `SFG_APT_REPO_SUBMITTER_APP_PRIVATE_KEY`.

### Set Up the Uploader App `sfg-apt-repo-uploader`

1. Navigate to the organization's **Settings** > **Developer settings** > **GitHub Apps**.
2. Click **New GitHub App** and configure the following properties:
    | Setting                                     | Value                                                                        |
    | ------------------------------------------- | ---------------------------------------------------------------------------- |
    | **GitHub App name**                         | `sfg-apt-repo-uploader`                                                      |
    | **Homepage URL**                            | `https://github.com/sfg-autonomous-systems/sfg_apt_repo`                     |
    | **Webhook > Active**                        | Unchecked                                                                    |
    | **Permissions > Repository permissions**    | Set **Contents** to **Read and write** (required to upload release assets).<br>Set **Actions** to **Read-only**. |
    | **Where can this GitHub App be installed?** | `Only on this account`                                                       |
3. Click **Create GitHub App**.
4. Save the **Client ID**.
5. Go to **Credentials** > **Key pairs** and generate a new key (`.pem` file).
6. In the left sidebar, click **Install App** and install it **only** on this repository.
7. Navigate to the organization's **Settings** > **Secrets and variables** > **Actions** and add the following organization secrets:
    | Name                                    | Value                                                        | Repository access                       |
    | --------------------------------------- | ------------------------------------------------------------ | --------------------------------------- |
    | `SFG_APT_REPO_UPLOADER_APP_CLIENT_ID`   | Paste the Client ID copied previously.                       | Selected repositories > this repository |
    | `SFG_APT_REPO_UPLOADER_APP_PRIVATE_KEY` | Paste the **entire** contents of the downloaded `.pem` file. | Selected repositories > this repository |
8. Delete the downloaded `.pem` file.

### Protect the Package Releases

The releases are the only copy of the packages. Deleting a release deletes every package in it, and unlike git there is no history to recover from. The uploader app never pushes to branches, so it needs no bypass for the branch rulesets.

GitHub has no per-release permissions: everyone with write access to this repository can upload and delete release assets. The scripts therefore only publish assets uploaded by the uploader app. Keep write access to this repository limited to the people who maintain it. Developers submit packages through the action and only need read access.

1. Navigate to this repository's **Settings** > **Rules** > **Rulesets** and click **New ruleset** > **New tag ruleset**.
2. Set **Ruleset name** to `Package Releases` and **Enforcement status** to **Active**.
3. Under **Bypass list** click **Add bypass** and select the `sfg-apt-repo-uploader` app.
4. Under **Target tags** add the patterns `common`, `jammy`, `noble` and `test-*`. Add every new distribution here as well.
5. Enable **Restrict updates** and **Restrict deletions**, then click **Create**.

Keep **Settings** > **General** > **Releases** > **Enable release immutability** disabled. The releases are updated with new assets over time.

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

## For Maintainers: Changing the Package Workflows

This section is only relevant when changing the workflows or scripts of this repository.

### Tests

The scripts in [scripts/](scripts/) are tested with `python3 -m unittest discover -s tests` (requires `dpkg-deb`, e.g. on Ubuntu). The [Test Scripts](.github/workflows/test_scripts.yaml) workflow runs them for pull requests and pushes to `main` that change `scripts/` or `tests/`.

[tests/e2e_release_storage.py](tests/e2e_release_storage.py) is a manual end-to-end test against real GitHub releases of a separate test repository, e.g. `sfg-autonomous-systems/release-asset-name-test`. It is not run by CI. Each run uses its own tag prefix `e2e-<timestamp>-` and leaves its releases in place:

```bash
GH_TOKEN="$(gh auth token)" python3 tests/e2e_release_storage.py --repository sfg-autonomous-systems/release-asset-name-test
```
