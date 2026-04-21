# 🖨️ Inkify Printer Agent (Edge Hardware Node)

The **Inkify Printer Agent** is a lightweight, cross-platform background daemon that connects local physical Hardware to the Inkify Cloud API. 

It acts as the critical bridge between the web dashboard and physical hardware, allowing users to route print jobs securely from anywhere in the world to their local machines.

---
 
##  📑 Table of Contents
 
- [How It Works](#how-it-works)
- [Features](#features)
- [Developer Setup](#developer-setup)
- [Building & Packaging](#building--packaging)
- [CI/CD Pipeline](#cicd-pipeline)
- [Repository Structure](#repository-structure)
- [License](#license)
 
---
## ⚙️ How It Works
 
The agent sits at the edge of the Inkify architecture as the physical hardware node.
 
```
Inkify Cloud API (FastAPI)
        │
        │  pre-signed S3 links, job dispatch
        ▼
Inkify Frontend (React)
        │
        │  secure download + pairing token
        ▼
Inkify Printer Agent  ◄── this repo
        │
        │  polls jobs, downloads PDFs, pushes to spooler
        ▼
Local OS Print Spooler (CUPS / Win32)
        │
        ▼
Physical Printer
```

1. **Cloud API** generates a 24-hour registration token and a pre-signed S3 download link for the installer.
2. **Frontend** presents the Host user with a one-click download button.
3. **Agent** installs as an OS-level service, authenticates with the token, polls for pending jobs, downloads the PDFs, and hands them to the local print spooler.
4. **Telemetry** flows back to the cloud in real time — paper levels, ink status, job completions, and hardware errors.
 
---

## ✨ Core Features

| Feature | Detail |
|---|---|
| Cross-platform | Native support for Windows (`.exe` via `WinSW`), macOS (`.pkg` via `launchd`), and Linux (`.deb` via `systemd`). |
| Invisible operation | Runs entirely in the background as an OS-level service with zero User Interaction. |
| Zero-touch config | Pairs with the cloud securely using dynamically injected 24-hour registration tokens in the downloaded installer file. |
| Hardware telemetry |  Monitors OS-level print spoolers (CUPS/Win32) for paper jams, ink levels, and job States, reporting status back to the cloud. |
| Automated distribution | GitHub Actions builds, packages, and pushes installers to AWS S3 on every tagged release |
 
---

## 🏗️ Architecture Overview

1. **The Cloud API (FastAPI):** Orchestrates users, manages print jobs, and generates pre-signed S3 download links for the installers.
2. **The Frontend (React):** Provides the Host user with a secure download button.
3. **The Edge Agent (This Repo):** A Python executable that polls the Cloud API, downloads pending PDFs, and pushes them to the local OS print spooler.

---

## 🛠️ Developer Setup (Local Environment)

### Prerequisites
* Python 3.11+
* `pip` and `virtualenv`
* Local printer configured (for testing print spooling)

### 1. Initialize the Environment
Clone the repository and set up your Python virtual environment:
```bash
git clone [https://github.com/yourusername/inkify-agent.git](https://github.com/yourusername/inkify-agent.git)
cd inkify-agent

python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```
### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Environment Configuration
Create a `.env` file in the root directory and configure your cloud connection:
```env
INKIFY_CLOUD_URL=http://localhost:8000/
ENVIRONMENT=development
JOB_POLL_INTERVAL=5
CLEANUP_INTERVAL_SECONDS=86400
```
### 4. Running Locally
To test the agent in the foreground without installing it as a background service:

```bash
python app/main.py --token "your_24_hour_test_token"
```
(Alternatively, use the provided helper script:
```bash
 ./scripts/run-inkify-agent.sh)
```
## 📦 Building and Packaging
The application is compiled into a standalone binary using PyInstaller and then wrapped into native OS installers.

> **Note:** Compiling for a specific OS requires running the build commands on that exact OS. We use GitHub Actions to automate this cross-platform matrix.
 
###   Local Compilation Commands
If you need to test the compilation manually on your local machine:

### Step 1 - Build the raw binary:

```bash
./scripts/build-inkify-agent.sh
```

### Step 2 - Package into a native installer:

| OS | Command | Output |
|---|---|---|
| macOS | `./scripts/build-mac-pkg.sh` | `.pkg` via `pkgbuild` |
| Linux | `./scripts/build-linux-deb.sh` | `.deb` via `dpkg-deb` |
| Windows | Compile `system/windows/setup.iss` with Inno Setup | `.exe` via WinSW |
 
---

## 🚀 CI/CD Pipeline & Distribution
- **This repository utilizes GitHub Actions to automate the entire assembly line.**

### How to Release a New Version
When you are ready to distribute an update to Host users, simply tag a commit and push it to GitHub:

```bash
git tag v1.0.0
git push origin v1.0.0
```
### What the Pipeline Does:
- Boots up ubuntu-latest, windows-latest, and macos-latest runners.

- Compiles the Python code into native executables via PyInstaller.

- Wraps the executables in native setup files (.deb, Inno Setup .exe, .pkg).

- Uploads the final installers directly to AWS S3 (inkify-installers bucket) for dynamic SaaS distribution.

- Creates a public GitHub Release with the attached binaries as a permanent backup.
```
Tag pushed to GitHub
        │
        ├── ubuntu-latest runner
        │       └── PyInstaller → .deb → upload to S3
        │
        ├── windows-latest runner
        │       └── PyInstaller → Inno Setup .exe → upload to S3
        │
        └── macos-latest runner
                └── PyInstaller → pkgbuild .pkg → upload to S3
                        │
                        └── GitHub Release created with all three binaries attached
```

- Installers land in the `inkify-installers` S3 bucket. The Cloud API generates pre-signed download URLs on demand so each installer file can carry a unique injected token — no manual distribution step required.
 
---
## 📂 Repository Structure
```
inkify-agent/
├── app/                          # Core Python application 
│   ├── main.py                   # Entry point — token extraction and bootstrap
│   ├── agent_lifecycle.py        # Main polling and telemetry loop
│   ├── services/                 # Cloud sync, job processing, and print dispatch
│   └── platform/                 # OS-specific spooler managers (Win32 / CUPS)
│
├── scripts/                      # Developer tools and build scripts
│   ├── build-inkify-agent.sh     # PyInstaller wrapper
│   ├── build-linux-deb.sh        # Debian packaging
│   └── build-mac-pkg.sh          # macOS pkgbuild packaging
│
├── system/                       # Passive OS blueprints and configurations
│   ├── linux/                    # systemd service files
│   ├── mac/                      # launchd plist files
│   └── windows/                  # Inno Setup .iss config + WinSW wrapper
│
├── .github/
│   └── workflows/                # CI/CD pipeline definitions
│
└── requirements.txt              # Python dependencies
```
---
## 📝 License
MIT License © 2026 Avinash Singh.