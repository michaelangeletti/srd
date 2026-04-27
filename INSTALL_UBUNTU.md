# Installing srd on Ubuntu 24.04

## Requirements

- Ubuntu 24.04 LTS
- Python 3.9 or later (Python 3.12 is the default on Ubuntu 24.04)
- rsync (installed by default)
- SSH key authentication configured for the remote server

Check your Python version:

```bash
python3 --version
```

## Install

### Option 1: pip from GitHub

```bash
pip3 install --break-system-packages git+https://github.com/michaelangeletti/smpl-replicate-directory.git
```

### Option 2: clone and install locally

```bash
git clone https://github.com/michaelangeletti/smpl-replicate-directory.git
cd smpl-replicate-directory
pip3 install --break-system-packages .
```

## Verify installation

```bash
srd --help
```

## Configuration

Open `srd/cli.py` and update the Ubuntu-specific constants:

```python
REMOTE_HOST_ALIAS = "sul-smpl.stanford.edu"   # your server hostname

else:
    LOG_DIR        = "/home/yourname/srd_logs"   # where logs are saved
    REMOTE_USER    = "your_server_username"       # your username on the server
    CONTROL_SOCKET = "/tmp/srd_ctl_%h"           # leave this as-is
```

## Duo two-factor authentication

The Stanford staging server requires Duo two-factor authentication. srd handles this using SSH ControlMaster — you authenticate once interactively, and all subsequent connections reuse that session.

**Before running any SFTP or push transfer, open a persistent SSH session:**

```bash
srd --open-ssh
```

This will display the Duo prompt. Approve it (typically option 1 for a push notification). The session is then held open in the background.

You can then run srd normally in any terminal:

```bash
srd /pool0/smpl2/digreq-2664 /media/smpl-5220r/RAID_1/260219
```

**The control socket does not survive a reboot.** After restarting your workstation, run `srd --open-ssh` again before your first transfer of the session.

## Updating

```bash
pip3 install --break-system-packages --upgrade git+https://github.com/michaelangeletti/smpl-replicate-directory.git
```
