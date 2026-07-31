# SFG APT Repo

This repository hosts the official APT packages for SFG Autonomous Systems. The repository is automatically generated and hosted via GitHub Pages.

## How to Add the Repository to Your System

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
    echo "deb [signed-by=/usr/share/keyrings/sfg-apt-repo.gpg] https://sfg-autonomous-systems.github.io/sfg_apt_repo $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/sfg-apt-repo.list
    ```

4. **Update Package Lists**
    ```bash
    sudo apt update
    ```