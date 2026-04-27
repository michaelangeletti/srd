# smpl-replicate-directory

**srd** — SMPL Replicate Directory

A command-line tool for secure file replication with MD5 integrity verification, developed for the Stanford Media Preservation Lab. Designed for digital preservation workflows where confirming that every file arrived completely and without corruption is as important as the transfer itself.

## Features

- **Three transfer modes:** pull from server (SFTP), local disk-to-disk, or push to server
- **MD5 verification:** every file is checksummed against its `.md5` sidecar after transfer
- **Live progress display:** two-line in-place bar with phase-aware ETA (scan vs. transfer vs. verify)
- **Structured integrity report:** three explicit preservation checks — complete, intact, documented
- **Companion output files:** timestamped `.log`, directory `.tree`, and optional `.csv` file list
- **Duo 2FA support:** SSH ControlMaster for Ubuntu workstations with two-factor authentication
- **Cross-platform:** single codebase for macOS and Ubuntu 24.04

## Installation

### Option 1: pip install from GitHub (recommended)

```bash
pip3 install git+https://github.com/michaelangeletti/smpl-replicate-directory.git
```

or without a virtual environment:

```bash
pip3 install --break-system-packages git+https://github.com/michaelangeletti/smpl-replicate-directory.git
```

### Option 2: manual install

```bash
git clone https://github.com/michaelangeletti/smpl-replicate-directory.git
cd smpl-replicate-directory
pip3 install --break-system-packages .
```

**Requires:** Python 3.9+, rsync (built into macOS; available by default on Ubuntu)

See [INSTALL_MACOS.md](INSTALL_MACOS.md) or [INSTALL_UBUNTU.md](INSTALL_UBUNTU.md) for platform-specific setup.

## Configuration

Before first use, open `srd/cli.py` and update two lines near the top:

```python
REMOTE_HOST_ALIAS = "sul-smpl.stanford.edu"   # SSH hostname of your server

if IS_MACOS:
    LOG_DIR = "/Users/yourname/Desktop/srd_logs"
else:
    LOG_DIR     = "/home/yourname/srd_logs"
    REMOTE_USER = "your_server_username"
```

## Usage

```
srd <SOURCE_DIR> <DEST_DIR> [OPTIONS]
```

### Pull files from server

```bash
srd /pool0/smpl2/digreq-2664 /Volumes/dav1_read/260219
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

### Ubuntu: open SSH session first (Duo 2FA)

```bash
srd --open-ssh
# approve the Duo prompt, then run srd normally in another terminal
srd /pool0/smpl2/digreq-2664 /media/smpl-5220r/RAID_1/260219
```

## Options

| Option | Description |
|---|---|
| `--push` | Push local files to the remote server |
| `--create-dest` | Create destination directory on server (with `--push`) |
| `--local` | Disk-to-disk mode, no SSH required |
| `--compress`, `-z` | Enable rsync compression |
| `--resume` | Resume interrupted transfers |
| `--csv` | Generate a CSV file list alongside the log |
| `--open-ssh` | Open persistent SSH session for Duo 2FA (Ubuntu only) |
| `--help`, `-h` | Show usage |

## Output files

Every run produces files in your configured log directory:

```
digreq-2664_20260223_090900_replication.log   ← full activity log
digreq-2664_20260223_090900_source.tree       ← directory tree of source
digreq-2664_20260223_090900_filelist.csv      ← file list (with --csv)
```

## Documentation

- [MANUAL.md](MANUAL.md) — full user guide
- [INSTALL_MACOS.md](INSTALL_MACOS.md) — macOS setup
- [INSTALL_UBUNTU.md](INSTALL_UBUNTU.md) — Ubuntu 24.04 setup

## About

Developed at the [Stanford Media Preservation Lab](https://library.stanford.edu/libraries/media-preservation-lab) for internal use in digitization and preservation workflows.

## License

Apache 2.0
