# srd

**srd** — SMPL Replicate Directory
**v1.1 — May 2026**

A command-line tool for secure file replication with MD5 integrity verification, developed for the Stanford Media Preservation Lab. Designed for digital preservation workflows where confirming that every file arrived completely and without corruption is as important as the transfer itself.

---

## Features

- **Three transfer modes:** pull from server (SFTP), local disk-to-disk, or push to server
- **Role code filtering:** transfer only files matching a specific role suffix (`--role pm`, `--role sl`, etc.)
- **MD5 verification:** every file is checksummed against its `.md5` sidecar after transfer
- **Live progress display:** purple two-line in-place bar with phase-aware ETA (scan / transfer / verify)
- **Structured integrity report:** three explicit preservation checks — complete, intact, documented
- **Companion output files:** timestamped `.log`, directory `.tree`, and optional `.csv` file list
- **Duo 2FA support:** SSH ControlMaster on both macOS and Ubuntu for two-factor authentication
- **Cross-platform:** single codebase for macOS and Ubuntu 24.04
- **Environment variable config:** set `SRD_REMOTE_USER` and `SRD_LOG_DIR` in `.zshrc` — no script editing needed after install

---

## Installation

**Recommended: pipx** (manages an isolated environment automatically)

```bash
brew install pipx        # macOS only, if pipx is not already installed
pipx install git+https://github.com/michaelangeletti/smpl-replicate-directory.git
```

On Ubuntu:

```bash
pip3 install --break-system-packages pipx
pipx install git+https://github.com/michaelangeletti/smpl-replicate-directory.git
```

**Requires:** Python 3.9+, rsync (built into macOS; available by default on Ubuntu)

See [INSTALL_MACOS.md](INSTALL_MACOS.md) or [INSTALL_UBUNTU.md](INSTALL_UBUNTU.md) for full setup instructions including Duo 2FA configuration.

---

## Configuration

No script editing required. Add two lines to `~/.zshrc` on each machine:

```bash
export SRD_REMOTE_USER="your_server_username"
export SRD_LOG_DIR="/Users/yourname/Desktop/srd_logs"
```

Then reload:

```bash
source ~/.zshrc
```

These values are read automatically every time srd runs. Future upgrades will never overwrite them.

---

## Usage

```
srd <SOURCE_DIR> <DEST_DIR> [OPTIONS]
```

### Pull files from server

```bash
srd /pool0/smpl2/digreq-2664 /Volumes/dav1_read/260219
srd /pool0/smpl2/specpat-3574 /Volumes/dav1_read/260219 --role pm
```

### Local disk-to-disk copy

```bash
srd /Volumes/SMPL_RAID/digreq-2664 /Volumes/BackupDrive/copy --local
```

### Push files to server

```bash
srd /Volumes/SMPL_RAID/digreq-2664 /pool0/smpl2 --push
srd /Volumes/SMPL_RAID/digreq-2664 /pool0/smpl2 --push --create-dest
```

### Open SSH session first (Duo 2FA — required on both macOS and Ubuntu)

```bash
srd --open-ssh
# approve the Duo prompt, then run srd normally in another terminal
srd /pool0/smpl2/digreq-2664 /Volumes/dav1_read/260219
```

---

## Options

| Option | Description |
|---|---|
| `--open-ssh` | Open persistent SSH session for Duo 2FA (run this first) |
| `--push` | Push local files to the remote server |
| `--create-dest` | Create destination directory on server (with `--push`) |
| `--local` | Disk-to-disk mode, no SSH required |
| `--role <code>` | Transfer only files with this role suffix: `pm`, `sl`, `sh`, `thumb`, `m_sl`, `m_sh`, `m_thumb` |
| `--compress`, `-z` | Enable rsync compression |
| `--resume` | Resume interrupted transfers |
| `--csv` | Generate a CSV file list alongside the log and tree |
| `--version`, `-v` | Show version and exit |
| `--help`, `-h` | Show usage |

---

## Output files

Every run produces files in your configured log directory:

```
digreq-2664_20260507_090900_replication.log   <- full activity log
digreq-2664_20260507_090900_source.tree       <- directory tree of source
digreq-2664_20260507_090900_filelist.csv      <- file list (with --csv)
```

---

## Updating

```bash
pipx upgrade smpl-replicate-directory
```

---

## Removing old installations

Before installing via pipx on a machine that previously had srd installed by other means:

```bash
pipx uninstall smpl-replicate-directory 2>/dev/null
sudo rm -f /usr/local/bin/srd
sudo rm -f /opt/homebrew/bin/srd
```

---

## Documentation

- [MANUAL.md](MANUAL.md) — full user guide
- [INSTALL_MACOS.md](INSTALL_MACOS.md) — macOS setup
- [INSTALL_UBUNTU.md](INSTALL_UBUNTU.md) — Ubuntu 24.04 setup

---

## About

Developed at the [Stanford Media Preservation Lab](https://library.stanford.edu/libraries/media-preservation-lab) for internal use in digitization and preservation workflows.

## License

Apache 2.0
