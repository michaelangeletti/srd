# srd — SMPL Replicate Directory
## User Manual

**Stanford Media Preservation Lab**
Version 0.1 — 2026

---

## Table of Contents

1. [Overview](#overview)
2. [Requirements](#requirements)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Basic Usage](#basic-usage)
6. [Transfer Modes](#transfer-modes)
   - [SFTP Mode (pull from server)](#sftp-mode)
   - [Local Mode (disk-to-disk)](#local-mode)
   - [Push Mode (send to server)](#push-mode)
7. [Options Reference](#options-reference)
8. [Ubuntu: SSH and Duo Authentication](#ubuntu-ssh-and-duo-authentication)
9. [Transfer Phases and Progress Display](#transfer-phases-and-progress-display)
10. [MD5 Verification](#md5-verification)
11. [The Final Report](#the-final-report)
12. [Log Files and Directory Trees](#log-files-and-directory-trees)
13. [Resuming Interrupted Transfers](#resuming-interrupted-transfers)
14. [Exit Codes](#exit-codes)
15. [Troubleshooting](#troubleshooting)
16. [Notes and Limitations](#notes-and-limitations)

---

## Overview

`srd` (SMPL Replicate Directory) is a command-line tool for copying directory trees and verifying their integrity using MD5 checksum sidecar files. It is designed for digital preservation workflows where confirming that every file arrived completely and without corruption is as important as the transfer itself.

Every srd run answers three questions:

1. **Did every source file reach the destination?** — pre- and post-transfer file counts are compared, and any missing files are listed by name.
2. **Did every file arrive intact?** — each data file is checksummed against its `.md5` sidecar at the destination.
3. **Is the outcome documented?** — a timestamped log file and a directory tree of the source are written to disk for every run.

srd wraps `rsync` for the transfer itself and adds pre-flight path validation, a live two-line progress display, phase-aware ETA, and a structured integrity report.

---

## Requirements

- **macOS** (any recent version) or **Ubuntu 24.04**
- **Python 3.9 or later** — check with `python3 --version`. On macOS, update via `brew upgrade python` if needed.
- **rsync** — built into macOS; available by default on Ubuntu.
- **SSH key authentication** configured for the remote server (SFTP and push modes).
- **Duo two-factor authentication** — required by the Stanford server. Ubuntu users must complete a one-time setup step before each session; see [Ubuntu: SSH and Duo Authentication](#ubuntu-ssh-and-duo-authentication).
- **Sufficient free disk space** at the destination — srd checks this before starting and requires a 10% safety margin.

---

## Installation

Copy the script to a location on your PATH and make it executable:

```bash
cp srd.py /usr/local/bin/srd
chmod +x /usr/local/bin/srd
```

Verify the installation:

```bash
srd --help
```

---

## Configuration

Two constants near the top of the script must be set before first use. Open `srd.py` in a text editor:

```python
# --- Fixed Configuration (edit these as needed) ---
REMOTE_HOST_ALIAS = "sul-smpl.stanford.edu"   # SSH hostname for the remote server
LOG_DIR = "/Users/dav1/Desktop/srd_logs"       # Where log files and tree files are saved
```

**On Ubuntu**, two additional constants are present:

```python
REMOTE_USER    = "smpl-5220r"           # Your username on the remote server
CONTROL_SOCKET = "/tmp/srd_ctl_%h"      # SSH ControlMaster socket path
```

`LOG_DIR` will be created automatically if it does not exist.

---

## Basic Usage

```
srd <SOURCE_DIR> <DEST_DIR> [OPTIONS]
```

- `SOURCE_DIR` — the directory to copy from (local path in all modes; remote path in SFTP mode)
- `DEST_DIR` — the directory to copy to (local path in SFTP and local modes; remote path in push mode)
- `OPTIONS` — one or more optional flags described in [Options Reference](#options-reference)

Arguments containing spaces must be quoted:

```bash
srd '/Volumes/SMPL RAID/batch_01' '/Volumes/dav1_read/260223'
```

---

## Transfer Modes

### SFTP Mode

**Pull files from the remote server to a local destination.** This is the default mode — no flag is required.

```bash
srd /pool0/smpl2/digreq-2664 /Volumes/dav1_read/260219
srd /pool0/smpl2/digreq-2664 /Volumes/dav1_read/260219 --compress
srd /pool0/smpl2/digreq-2664 /Volumes/dav1_read/260219 --resume
```

- The first argument is the path on the remote server.
- The second argument is the local destination. It will be created if it does not exist.
- Verification is performed locally after the transfer completes.
- SSH authentication (including Duo on Ubuntu) is required before running. See [Ubuntu: SSH and Duo Authentication](#ubuntu-ssh-and-duo-authentication).

---

### Local Mode

**Copy files between two local directories or attached drives.** No network connection or SSH session is required.

```bash
srd /Volumes/SMPL_RAID_SHUTTLE/digreq-2664 /Volumes/dav1_read/260219 --local
srd /Volumes/SourceDrive/batch /Volumes/BackupDrive/batch --local --resume
```

- Both arguments are local paths.
- The destination will be created if it does not exist.
- Verification is performed locally.
- Mutually exclusive with `--push`.

---

### Push Mode

**Send files from a local source to the remote server.** This is the reverse of SFTP mode.

```bash
srd /Volumes/SMPL_RAID_SHUTTLE/digreq-2664 /pool0/smpl2 --push
srd /Volumes/SMPL_RAID_SHUTTLE/digreq-2664 /pool0/smpl2 --push --create-dest
```

- The first argument is the local source directory.
- The second argument is the parent directory on the server. The source folder itself is copied into this location, so files land at `<DEST_DIR>/<source_folder_name>/` on the server. For example:

  ```
  srd /Volumes/drive/digreq-2664 /pool0/smpl2 --push
  ```
  Files land at `/pool0/smpl2/digreq-2664/` on the server.

- The destination parent directory must already exist on the server unless `--create-dest` is used.
- All files and directories written to the server receive open (`rwx`) permissions so that all team members can access them.
- Verification is performed on the server via SSH — files are not re-downloaded for checksum comparison.
- SSH authentication (including Duo on Ubuntu) is required. See [Ubuntu: SSH and Duo Authentication](#ubuntu-ssh-and-duo-authentication).

#### Creating the destination automatically

If the target subdirectory does not yet exist on the server, add `--create-dest`:

```bash
srd /Volumes/drive/specpat-3496 /pool0/smpl2 --push --create-dest
```

This creates `/pool0/smpl2/specpat-3496/` on the server with open `rwx` permissions before the transfer begins. It does not attempt to modify the parent directory (`/pool0/smpl2/`), which you may not own.

`--create-dest` is only valid with `--push` and will produce an error if used alone.

---

## Options Reference

| Option | Description |
|---|---|
| `--push` | Push local files to the remote server (reverses transfer direction). |
| `--create-dest` | Create the destination subdirectory on the server before pushing. Only valid with `--push`. Uses open `rwx` permissions. |
| `--local` | Disk-to-disk mode. No SSH required. Mutually exclusive with `--push`. |
| `--compress`, `-z` | Enable rsync compression. Reduces bandwidth at the cost of CPU time. Useful for slow or metered connections; not recommended for local transfers or fast LAN/campus links. |
| `--resume` | Enable partial-file resumption (`--partial --append-verify`). Allows interrupted transfers to continue from where they left off rather than restarting files from the beginning. Recommended when transferring very large files over a network. Slightly slower on fresh transfers. |
| `--help`, `-h` | Print usage information and exit with code 0. |

---

## Ubuntu: SSH and Duo Authentication

The Stanford staging server requires Duo two-factor authentication, which cannot be handled automatically by a script. srd solves this using SSH ControlMaster: you authenticate once interactively, and all subsequent SSH connections and rsync operations reuse that session transparently.

**Before running any SFTP or push transfer on Ubuntu, open a persistent SSH session:**

```bash
srd --open-ssh
```

This will display the Duo prompt. Approve it (option 1 for a Duo Push is typical). The session is then held open in the background — you do not need to keep that terminal window active.

You can then run srd normally in any terminal:

```bash
srd /pool0/smpl2/digreq-2664 /media/smpl-5220r/RAID_1/260219
```

**The control socket does not survive a reboot.** After restarting your Ubuntu workstation, run `srd --open-ssh` again before your first transfer of the session.

If you forget and run srd without opening the session first, you will see a clear error:

```
✗ SSH control socket not found: /tmp/srd_ctl_sul-smpl.stanford.edu
  Run: srd --open-ssh
```

> **macOS note:** The macOS version does not require this step. SSH key authentication is handled directly and Duo is not required on that platform.

---

## Transfer Phases and Progress Display

A complete srd run proceeds through four sequential phases. Each phase with measurable progress shows a live two-line display in the terminal.

### Phase 1: Pre-flight

Before any data moves, srd:

- Verifies that source and destination paths exist (and are accessible)
- On SFTP and push modes, verifies the SSH connection
- Counts all files in the source and calculates their total size
- Checks that the destination has sufficient free disk space (requires 10% safety margin)

No progress bar is shown during pre-flight. If any check fails, srd exits with a clear error message before touching any data.

### Phase 2: Directory scan (rsync ir-chk)

rsync begins by building an internal file list. During this phase the bar shows:

```
[████████░░░░░░░░░░░░░░░░░░░░░░░░]  25.3%  scanning… 80/1112  |  total 1.2TB  |  00:00:42 elapsed  |  ETA --:--:--
[rsync] ./Reel_01/  0%  0.00kB/s  0:00:00 (xfr#80, ir-chk=1032/1112)
```

ETA is suppressed (`--:--:--`) during the scan because the scan rate is much faster than the transfer rate and would produce a misleading estimate.

### Phase 3: File transfer (rsync to-chk)

Once rsync begins moving data, the display switches to transfer mode:

```
[████████████░░░░░░░░░░░░░░░░░░░░]  37.5%  301/1112 files  |  total 1.2TB  |  00:34:02 elapsed  |  ETA 00:56:18
[rsync] BigFile_reel01.mov  386.46MB/s    0:00:12 (xfr#301, to-chk=811/1112)
```

- **Line 1** — overall progress bar, file count, total data size, time elapsed since the script started, and ETA calculated from the moment file transfer began (excluding the scan phase, which would distort the estimate).
- **Line 2** — the current file being transferred with its live rsync speed and per-file progress.

Both lines update in place without scrolling. When the transfer completes cleanly, the bar is stamped at 100% before the success message appears.

If no output is received for several seconds (e.g. between large files), a yellow heartbeat dot `•` is printed to indicate the process is still running.

### Phase 4: Integrity verification

After rsync exits, srd verifies every data file against its MD5 sidecar. A separate progress bar tracks this phase:

```
[████████████████░░░░░░░░░░░░░░░░]  50.3%  796/1592 verified  |  00:23:15 elapsed  |  ETA 00:22:58
[verify] BigFile_reel01.mov
```

In **push mode**, verification runs on the server via SSH. The progress bar updates as each file's result is streamed back. While the server is computing a checksum on a large file (which may take several minutes), the elapsed timer on the bar refreshes every 5 seconds so it is clear the process is running.

---

## MD5 Verification

srd expects every data file to have a companion sidecar file with the same name and an `.md5` extension:

```
Reel_01_001.mov         ← data file
Reel_01_001.mov.md5     ← sidecar containing the expected MD5 hash
```

The sidecar can contain the hash in any common format — srd extracts the first 32-character hex string it finds, so both bare hash files and files with filenames (as produced by `md5sum` or `md5`) are supported.

**Files without a sidecar** are flagged as orphans in the final report (a warning, not a failure). They are still copied, but cannot be verified. Consistent orphan warnings indicate that the originating workflow is not producing sidecar files.

**Checksum mismatches** are a failure condition. They indicate that the file content at the destination does not match the file content at the source at the time the sidecar was generated — this may indicate a corrupt transfer, a corrupt source file, or a stale sidecar.

Hidden files (names beginning with `.`) are excluded from file counts, transfer, and verification in all modes.

---

## The Final Report

At the end of every run, srd prints a structured report to both the terminal and the log file. It is organized around the three preservation checks:

```
============================================================
FINAL INTEGRITY REPORT
============================================================
Source :   3184 files  (1.2TB)
Dest   :   3184 files  (1.2TB)
Duration: 4092.26 seconds (68.2 minutes)
------------------------------------------------------------
Checksums passed  : 1592/1592
Checksums failed  : 0/1592
------------------------------------------------------------
CHECK 1: Complete transfer
  ✓ PASS — All 3184 source files are present at the destination.
CHECK 2: Intact transfer (MD5 verification)
  ✓ PASS — All 1592 verified file(s) match their MD5 sidecars.
  ✓ All source files have .md5 sidecars.
CHECK 3: Documentation
  ✓ Full log written to:  /Users/dav1/srd_logs/digreq-2664_20260223_090900_replication.log
  ✓ Directory tree saved: /Users/dav1/srd_logs/digreq-2664_20260223_090900_source.tree
============================================================
✓ SUCCESS — Transfer complete and verified.
============================================================
```

### When issues are found

**Missing files** are listed individually (up to 100 filenames):

```
CHECK 1: Complete transfer
  ✗ FAIL — File count mismatch: source=3184, dest=3180 (-4).
            Hidden files (.*) are excluded from both counts.
  ✗ FAIL — 4 source file(s) not found at destination:
    → Reel_03/digreq-2664_reel03_002.mov
    → Reel_03/digreq-2664_reel03_002.mov.md5
    → Reel_07/digreq-2664_reel07_011.mov
    → Reel_07/digreq-2664_reel07_011.mov.md5
```

**Checksum failures** are also listed individually (up to 100):

```
CHECK 2: Intact transfer (MD5 verification)
  ✗ FAIL — 1 file(s) failed MD5 verification:
    → Reel_05/digreq-2664_reel05_003.mov
```

If more than 100 anomalies of a single type are found, srd notes the total and flags it as a systemic issue requiring investigation rather than listing every filename.

### Check outcomes and severity

| Check | Outcome if failed | Causes overall failure? |
|---|---|---|
| Source files have .md5 sidecars | WARNING — files copied but unverifiable | No |
| File count matches | ERROR — count mismatch reported with difference | Yes |
| No files missing from destination | ERROR — missing files listed by name | Yes |
| All checksums pass | ERROR — mismatched files listed by name | Yes |

---

## Log Files and Directory Trees

Every run produces two files in `LOG_DIR`, named with the source folder name and a timestamp:

```
digreq-2664_20260223_090900_replication.log
digreq-2664_20260223_090900_source.tree
```

### Log file

The `.log` file contains the complete run record: startup parameters, pre-flight results, progress snapshots every 30 seconds (tagged by phase), any warnings or errors, and the full final report. Progress entries are tagged for easy searching:

```
[progress:scan]       — during rsync directory scan
[progress:transfer]   — during rsync file transfer
[verify]              — during local MD5 verification
[verify:remote]       — during server-side MD5 verification (push mode)
```

### Directory tree

The `.tree` file shows the complete folder and file structure of the source directory at the time of transfer, with file sizes. This allows staff to quickly review what was included in a batch and spot missing components such as an absent derivative file.

```
Source directory tree: /Volumes/SMPL_RAID_SHUTTLE/digreq-2664
Generated: 2026-02-23 09:09:17
============================================================
/Volumes/SMPL_RAID_SHUTTLE/digreq-2664
├── Reel_01/
│   ├── digreq-2664_reel01_001.mov  [74.2GB]
│   └── digreq-2664_reel01_001.mov.md5  [72.0B]
├── Reel_02/
│   ├── digreq-2664_reel02_001.mov  [52.8GB]
│   └── digreq-2664_reel02_001.mov.md5  [72.0B]

2 directories, 4 files
```

The tree is generated using the system `tree` command if available (install via `brew install tree` on macOS; built-in on Ubuntu). If `tree` is not installed, srd generates an equivalent tree in Python automatically — the output is never skipped.

---

## Resuming Interrupted Transfers

If a transfer is interrupted — by a network drop, system sleep, manual cancellation, or a reboot — it can be resumed by re-running the same command with the `--resume` flag added.

**Recommended restart procedure after a reboot (Ubuntu):**

```bash
srd --open-ssh
srd /pool0/smpl2/digreq-2664 /media/smpl-5220r/RAID_1/260219 --resume
```

**Without `--resume`** (default): rsync skips files that already exist at the destination and are complete. Any file that was mid-transfer when the interruption occurred will be deleted and restarted.

**With `--resume`**: rsync adds `--partial --append-verify`, which preserves partially-transferred files and resumes them from where they stopped. For large files (50–100 GB) this is a significant time saving.

Note that `--resume` adds a small overhead to fresh transfers because rsync performs an extra verification pass. For transfers of very large files over a network connection this overhead is negligible compared to the benefit.

---

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success — all files transferred and verified. |
| `1` | Failure — transfer error, missing files, checksum mismatch, path error, or insufficient disk space. |
| `130` | Cancelled — the user interrupted the run with Ctrl+C. |

These codes are suitable for use in shell scripts that need to check whether a transfer succeeded before proceeding.

---

## Troubleshooting

### "SSH control socket not found" (Ubuntu)

The ControlMaster session has not been opened, or it was cleared by a reboot. Run `srd --open-ssh` and approve the Duo prompt, then re-run your transfer command.

### "Source path not found" or "Destination path not found"

srd performs early path validation and will report this before attempting any transfer. Check for:

- Typos in the path
- A drive that is not mounted (macOS: check Finder; Ubuntu: check `/media/`)
- A remote path that does not exist on the server (use `--create-dest` with `--push` if the destination folder needs to be created)

### File count mismatch — but no files listed as missing

This can occur if the destination has extra files from a previous transfer that are not in the current source manifest, resulting in a higher destination count than source count. The difference value shown in the report (e.g. `+4`) indicates which direction the mismatch goes.

Also note: hidden files (names beginning with `.`, such as `.DS_Store`) are excluded from both counts. A mismatch caused entirely by hidden files is not a preservation concern, but srd notes this in the report to rule it out quickly.

### "Operation not permitted" when using --create-dest

This occurs when srd tries to `chmod` a directory you did not create. Ensure you are providing the **parent** directory as the destination argument — srd will create and set permissions on the new subdirectory (named after your source folder) inside it. It will never attempt to modify the parent.

```bash
# Correct: /pool0/smpl2 is the parent you have write access to
srd /Volumes/drive/digreq-2664 /pool0/smpl2 --push --create-dest

# This creates /pool0/smpl2/digreq-2664/ with open permissions
```

### ETA shows --:--:-- during transfer

This is normal during the initial rsync directory scan (ir-chk phase). ETA is intentionally suppressed until the first actual file transfer begins, at which point it switches to a rate calculated from observed transfer speed.

### Progress bar not visible

The live progress bar requires a TTY (an interactive terminal). If you are running srd inside a script, redirecting output, or running it via a remote tool that does not allocate a TTY, the bar is suppressed and progress is written to the log file every 30 seconds instead.

### SyntaxError on older Python

If you see a `SyntaxError` referencing an f-string, your Python version is too old. Run `python3 --version` — srd requires 3.9 or later. On macOS: `brew upgrade python`. On Ubuntu: `sudo apt install python3`.

---

## Notes and Limitations

**rsync's file count vs. srd's file count.** rsync's internal `to-chk` counter includes directories as well as files, which can cause the transfer bar to reach 86–90% and appear to stall before rsync finishes. srd clamps the bar to 100% on a clean rsync exit regardless of this count. The file counts in the final report are always based on actual files only, consistent with the source manifest built at the start of the run.

**Destination directory creation (pull and local modes).** In SFTP and local modes, the destination directory is created automatically if it does not exist. In push mode, the parent directory must exist; use `--create-dest` to create the batch subdirectory.

**Compression.** The `--compress` flag is most useful for slow or metered network connections. For campus-speed transfers (~100 MB/s) or local disk-to-disk transfers, compression adds CPU overhead that exceeds any I/O benefit and will slow the transfer down.

**Verification time estimate.** Remote verification in push mode depends on server-side disk read speed, not network speed — only a 32-character hash travels back over the wire per file. At typical staging server speeds (~300 MB/s sustained read), expect roughly 3–6 minutes of verification time per 100 GB of data.

**File naming.** srd does not rename, reorganize, or modify any files. The destination directory structure mirrors the source exactly. rsync copies the source folder itself into the destination, so a source folder named `digreq-2664` will appear as a subfolder at the destination.

**Concurrent runs.** Running multiple instances of srd simultaneously to the same destination is not recommended and may produce unreliable file count comparisons in the final report.

---

*srd is an internal tool of the Stanford Media Preservation Lab. For questions or to report issues, contact the Lab's digital preservation staff.*
