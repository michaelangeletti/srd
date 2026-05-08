# Installing srd on macOS

**srd v1.1 — May 2026**

---

## Requirements

- macOS (any recent version; tested on macOS 15.x Sequoia)
- Python 3.9 or later
- rsync (built into macOS; Homebrew version recommended — see below)
- pipx (recommended installer)

Check your Python version:

```bash
python3 --version
```

If it is below 3.9, update via Homebrew:

```bash
brew upgrade python
```

---

## Before installing: remove old versions

If srd was previously installed by copying a script to `/usr/local/bin` or via pip, remove those copies first to avoid conflicts:

```bash
pipx uninstall smpl-replicate-directory 2>/dev/null
sudo rm -f /usr/local/bin/srd
sudo rm -f /opt/homebrew/bin/srd
```

Then confirm nothing is left:

```bash
which -a srd
```

---

## Install via pipx (recommended)

pipx installs srd in an isolated environment and avoids conflicts with Homebrew's Python.

```bash
brew install pipx   # if pipx is not already installed
pipx install git+https://github.com/michaelangeletti/smpl-replicate-directory.git
```

Verify:

```bash
srd --version
```

---

## Configuration

No script editing required. Add two lines to `~/.zshrc`:

```bash
export SRD_REMOTE_USER="your_server_username"
export SRD_LOG_DIR="/Users/yourname/Desktop/srd_logs"
```

Then reload:

```bash
source ~/.zshrc
```

`SRD_REMOTE_USER` is your username on the remote server (e.g. `mangelet`).
`SRD_LOG_DIR` is where srd will save log, tree, and CSV files. It will be created automatically if it does not exist.

These variables persist across upgrades — you will never need to edit the script again after setting them.

---

## Duo two-factor authentication

The Stanford staging server requires Duo two-factor authentication. srd handles this using SSH ControlMaster — you authenticate once interactively, and all subsequent SSH connections and rsync transfers reuse that session.

**Before running any SFTP or push transfer, open a persistent SSH session:**

```bash
srd --open-ssh
```

Approve the Duo prompt (typically option 1 for a push notification). The session is held open in the background — you do not need to keep that terminal window active.

Run srd normally in any other terminal:

```bash
srd /pool0/smpl2/digreq-2664 /Volumes/dav1_read/260219
```

**The control socket does not survive a reboot.** After restarting your Mac, run `srd --open-ssh` again before your first transfer of the session.

---

## Homebrew rsync (recommended)

The rsync built into macOS is an older version. Homebrew provides a current version with better performance. If you use Homebrew, add this to `~/.zshrc` to ensure the Homebrew version takes priority:

```bash
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
alias rsync="/opt/homebrew/bin/rsync"
```

---

## Updating

```bash
pipx upgrade smpl-replicate-directory
```

Because the version number is updated with each release, this will always pull the latest changes without needing `--force`.

---

## Finding the installed cli.py

If you ever need to inspect the installed script directly:

```bash
find ~/.local/pipx -name "cli.py" -path "*/srd/*"
```
