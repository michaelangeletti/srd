# Installing srd on macOS

## Requirements

- macOS (any recent version)
- Python 3.9 or later
- rsync (built into macOS)

Check your Python version:

```bash
python3 --version
```

If it is below 3.9, update via Homebrew:

```bash
brew install python
```

## Install

### Option 1: pip from GitHub

```bash
pip3 install git+https://github.com/michaelangeletti/smpl-replicate-directory.git
```

If you get a permissions error, add `--break-system-packages`:

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

Open the file `srd/cli.py` (inside the package, or in your cloned copy) and update:

```python
REMOTE_HOST_ALIAS = "sul-smpl.stanford.edu"   # your server hostname

if IS_MACOS:
    LOG_DIR = "/Users/yourname/Desktop/srd_logs"   # where logs are saved
```

The `LOG_DIR` folder will be created automatically on first run.

## SSH key authentication

srd requires SSH key authentication to the remote server. Confirm it works:

```bash
ssh sul-smpl.stanford.edu
```

If prompted for a password rather than connecting directly, you will need to set up an SSH key pair. Contact your system administrator if needed.

## Updating

```bash
pip3 install --break-system-packages --upgrade git+https://github.com/michaelangeletti/smpl-replicate-directory.git
```
