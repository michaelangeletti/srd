#!/usr/bin/env python3
"""
Secure file replication with integrity verification.
Copies files from a remote server via SFTP/rsync, or from a local directory,
and validates checksums. Works on macOS and Ubuntu 24.04.
"""

import subprocess
import logging
import sys
import time
import select
import re
import hashlib
from pathlib import Path
from typing import Optional, Tuple, Set, List, Dict
from dataclasses import dataclass
from datetime import datetime

# --- Platform Detection ---
IS_MACOS = sys.platform == "darwin"

# --- Fixed Configuration (edit these as needed) ---
REMOTE_HOST_ALIAS = "sul-smpl.stanford.edu"  # SSH hostname — update if needed

REMOTE_USER    = "YOUR_SERVER_USERNAME"   # ← your username on the remote server
CONTROL_SOCKET = "/tmp/srd_ctl_%h"        # leave as-is
LOG_DIR        = "/path/to/your/srd_logs" # ← where logs will be saved on this machine

# --- ANSI Color Codes ---
class Colors:
    """ANSI color codes for terminal output."""
    RESET   = '\033[0m'
    RED     = '\033[91m'
    GREEN   = '\033[92m'
    YELLOW  = '\033[93m'
    BLUE    = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN    = '\033[96m'
    BOLD    = '\033[1m'

    @staticmethod
    def disable():
        """Disable colors (for non-TTY output)."""
        Colors.RESET = Colors.RED = Colors.GREEN = Colors.YELLOW = ''
        Colors.BLUE  = Colors.MAGENTA = Colors.CYAN = Colors.BOLD = ''

# --- Constants ---
SSH_TIMEOUT          = 30
RSYNC_TIMEOUT        = 3600
MD5_CHUNK_SIZE       = 8192
PROGRESS_DOT_INTERVAL = 2.0

PROGRESS2_RE = re.compile(r'xfr#(\d+),\s*(?:to|ir)-chk=(\d+)/(\d+)')

if not sys.stdout.isatty():
    Colors.disable()


class ColoredFormatter(logging.Formatter):
    """Custom formatter that adds colors based on log level."""
    FORMATS = {
        logging.DEBUG:    Colors.CYAN   + '%(asctime)s - DEBUG: %(message)s'    + Colors.RESET,
        logging.INFO:                     '%(asctime)s - %(message)s',
        logging.WARNING:  Colors.YELLOW + '%(asctime)s - WARNING: %(message)s'  + Colors.RESET,
        logging.ERROR:    Colors.RED    + '%(asctime)s - ERROR: %(message)s'    + Colors.RESET,
        logging.CRITICAL: Colors.RED + Colors.BOLD + '%(asctime)s - CRITICAL: %(message)s' + Colors.RESET,
    }
    def format(self, record):
        return logging.Formatter(self.FORMATS.get(record.levelno, self.FORMATS[logging.INFO])).format(record)


@dataclass
class TransferStats:
    """Statistics for the file transfer operation."""
    remote_file_count:    int
    remote_size_bytes:    int
    local_file_count:     int
    local_size:           str
    duration:             float
    remote_orphans:       List[str]
    missing_files:        Set[str]
    checksum_mismatches:  List[str]
    verified_count:       int = 0
    unverifiable_count:   int = 0

# Module-level logger — handlers are added inside main() once LOG_FILE is known.
# All functions use this logger; it works correctly once main() configures it.
logger      = logging.getLogger('srd')
file_handler = None   # assigned in main()


def run_ssh_command(command: str, timeout: int = SSH_TIMEOUT) -> Optional[str]:
    """
    Execute a command on the remote host via SSH.
    
    Args:
        command: The command to execute on remote host
        timeout: Maximum time to wait for command completion
        
    Returns:
        Command output as string, or None if command failed
    """
    if IS_MACOS:
        ssh_cmd = [
            'ssh',
            '-o', 'ControlMaster=no',
            '-o', f'ControlPath={CONTROL_SOCKET}',
            f'{REMOTE_USER}@{REMOTE_HOST_ALIAS}', command,
        ]
    else:
        ssh_cmd = [
            'ssh', '-o', 'ControlMaster=no',
            '-o', f'ControlPath={CONTROL_SOCKET}',
            f'{REMOTE_USER}@{REMOTE_HOST_ALIAS}', command,
        ]
    
    try:
        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            errors='surrogateescape',
            timeout=timeout,
            check=False
        )
        
        if result.returncode != 0:
            logger.error(f"SSH command failed (exit {result.returncode}): {command}")
            if result.stderr:
                logger.error(f"Error output: {result.stderr.strip()}")
            return None
            
        return result.stdout.strip()
        
    except subprocess.TimeoutExpired:
        logger.error(f"SSH command timed out after {timeout}s: {command}")
        return None
    except Exception as e:
        logger.error(f"SSH command exception: {e}")
        return None



def check_local_path(path: str, label: str) -> bool:
    """
    Verify a local path exists and is a directory.
    Prints a clear, actionable error if not.
    """
    p = Path(path)
    if not p.exists():
        logger.error(f"{Colors.RED}✗ {label} path not found: {path}{Colors.RESET}")
        logger.error(f"  Please check for typos and verify the drive is mounted.")
        return False
    if not p.is_dir():
        logger.error(f"{Colors.RED}✗ {label} path is not a directory: {path}{Colors.RESET}")
        return False
    return True


def check_remote_path(path: str, label: str) -> bool:
    """
    Verify a remote path exists and is a directory via SSH.
    Prints a clear, actionable error if not.
    """
    result = run_ssh_command(f'test -d {path} && echo DIR_OK || echo DIR_MISSING', timeout=15)
    if result and 'DIR_OK' in result:
        return True
    logger.error(f"{Colors.RED}✗ {label} path not found on server: {path}{Colors.RESET}")
    logger.error(f"  Please check for typos. The directory must already exist on the server.")
    return False


def verify_ssh_connection() -> bool:
    """Verify SSH connection is working."""
    logger.info(f"{Colors.CYAN}Verifying SSH connection...{Colors.RESET}")
    result = run_ssh_command("echo 'SSH_OK'", timeout=10)
    
    if result and 'SSH_OK' in result:
        logger.info(f"{Colors.GREEN}✓ SSH connection verified successfully{Colors.RESET}")
        return True
    
    logger.error(f"SSH connection failed to {REMOTE_HOST_ALIAS}")
    logger.error("Please ensure the ControlMaster socket is open (run: srd --open-ssh)")
    return False


def check_ssh_socket() -> bool:
    """Verify the ControlMaster socket exists before any SSH call."""
    socket_path = Path(CONTROL_SOCKET.replace('%h', REMOTE_HOST_ALIAS))
    if socket_path.exists():
        logger.info(f"{Colors.GREEN}\u2713 SSH control socket found: {socket_path}{Colors.RESET}")
        return True
    logger.error(f"{Colors.RED}\u2717 SSH control socket not found: {socket_path}{Colors.RESET}")
    logger.error("Run:  srd --open-ssh  and approve the Duo prompt first.")
    return False


def get_remote_stats(remote_path: str) -> Tuple[Set[str], int, List[str]]:
    """
    Get remote directory statistics in a single SSH session.
    
    Returns:
        Tuple of (file manifest, total size in bytes, orphan files without .md5)
    """
    logger.info(f"{Colors.CYAN}Gathering remote directory statistics...{Colors.RESET}")
    
    # Single SSH command that does everything in one session
    combined_cmd = f"""
    cd {remote_path} 2>/dev/null || exit 1
    
    # List all files (excluding hidden) and calculate total size
    find . -type f ! -path '*/.*' -print0 | 
    while IFS= read -r -d '' file; do
        echo "FILE:$file"
    done
    
    # Calculate total size using actual file sizes (not disk usage)
    if [["$OSTYPE" == "darwin"*]]; then
        total_bytes=$(find . -type f ! -path '*/.*' -exec stat -f%z {{}} + 2>/dev/null | awk '{{sum+=$1}} END {{print sum}}')
    else
        total_bytes=$(find . -type f ! -path '*/.*' -exec stat -c%s {{}} + 2>/dev/null | awk '{{sum+=$1}} END {{print sum}}')
    fi
    echo "SIZE_BYTES:$total_bytes"
    """
    
    output = run_ssh_command(combined_cmd, timeout=SSH_TIMEOUT * 2)
    
    if not output:
        logger.error("Failed to get remote statistics")
        return set(), 0, []
    
    manifest = set()
    remote_files = set()
    orphans = []
    total_bytes = 0
    
    for line in output.splitlines():
        if line.startswith("FILE:"):
            # Remove "FILE:" prefix and leading "./"
            file_path = line[5:].lstrip('./')
            if file_path:  # Skip empty paths
                manifest.add(file_path)
                remote_files.add(file_path)
        elif line.startswith("SIZE_BYTES:"):
            try:
                total_bytes = int(line[11:].strip())
            except (ValueError, AttributeError):
                total_bytes = 0
    
    # Check for orphan files (data files without .md5 sidecars)
    for file_path in sorted(remote_files):
        if not file_path.endswith('.md5'):
            md5_path = f"{file_path}.md5"
            if md5_path not in remote_files:
                orphans.append(file_path)
    
    size_str = format_bytes(total_bytes)
    logger.info(f"{Colors.GREEN}✓ Remote: {len(manifest)} files, {size_str}{Colors.RESET}")
    
    return manifest, total_bytes, orphans


def get_local_stats(source_path: str) -> Tuple[Set[str], int, List[str]]:
    """
    Get source directory statistics for a local path.
    Mirrors get_remote_stats() but uses the local filesystem instead of SSH.

    Returns:
        Tuple of (file manifest, total size in bytes, orphan files without .md5)
    """
    logger.info(f"{Colors.CYAN}Gathering source directory statistics...{Colors.RESET}")

    src = Path(source_path)
    if not src.exists():
        logger.error(f"Source directory does not exist: {source_path}")
        return set(), 0, []
    if not src.is_dir():
        logger.error(f"Source path is not a directory: {source_path}")
        return set(), 0, []

    manifest: Set[str] = set()
    total_bytes = 0

    for item in src.rglob('*'):
        # Skip hidden files and directories
        if any(part.startswith('.') for part in item.parts):
            continue
        if item.is_file():
            rel = item.relative_to(src)
            manifest.add(str(rel))
            try:
                total_bytes += item.stat().st_size
            except OSError:
                pass

    # Identify orphan data files (no accompanying .md5 sidecar)
    orphans = [
        f for f in sorted(manifest)
        if not f.endswith('.md5') and f"{f}.md5" not in manifest
    ]

    size_str = format_bytes(total_bytes)
    logger.info(f"{Colors.GREEN}✓ Source: {len(manifest)} files, {size_str}{Colors.RESET}")

    return manifest, total_bytes, orphans


def extract_hash_from_sidecar(sidecar_path: Path) -> Optional[str]:
    """Extract MD5 hash from sidecar file."""
    try:
        content = sidecar_path.read_text(errors='ignore')
        match = re.search(r'([a-fA-F0-9]{32})', content)
        return match.group(1).lower() if match else None
    except Exception as e:
        logger.error(f"Error reading sidecar {sidecar_path}: {e}")
        return None


def calculate_md5(file_path: Path) -> Optional[str]:
    """Calculate MD5 hash of a file."""
    try:
        md5_hash = hashlib.md5()
        with file_path.open('rb') as f:
            for chunk in iter(lambda: f.read(MD5_CHUNK_SIZE), b''):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()
    except Exception as e:
        logger.error(f"Error calculating MD5 for {file_path}: {e}")
        return None


def format_bytes(num_bytes: int) -> str:
    """Convert bytes to human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if num_bytes < 1024.0:
            return f"{num_bytes:.1f}{unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f}PB"


def format_eta(seconds: float) -> str:
    """Format a duration in seconds as HH:MM:SS for ETA display."""
    if seconds <= 0 or seconds > 86400 * 7:  # cap at one week
        return '--:--:--'
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def get_disk_space(path: Path) -> Tuple[int, int]:
    """
    Get available and total disk space for the given path.
    
    Returns:
        Tuple of (available_bytes, total_bytes)
    """
    import shutil
    try:
        stat = shutil.disk_usage(path)
        return stat.free, stat.total
    except Exception as e:
        logger.error(f"Failed to get disk space for {path}: {e}")
        return 0, 0


def check_disk_space(local_path: Path, remote_size_bytes: int) -> bool:
    """
    Verify sufficient disk space is available.
    
    Args:
        local_path: Destination directory
        remote_size_bytes: Size of data to be transferred in bytes
        
    Returns:
        True if sufficient space, False otherwise
    """
    logger.info(f"{Colors.CYAN}Checking available disk space...{Colors.RESET}")
    
    # Get available space
    available, total = get_disk_space(local_path)
    
    if available == 0:
        logger.error("Could not determine available disk space")
        return False
    
    # Add 10% safety margin
    required_bytes = int(remote_size_bytes * 1.1)
    
    logger.info(f"  Required space: {format_bytes(required_bytes)} (including 10% safety margin)")
    logger.info(f"  Available space: {format_bytes(available)}")
    logger.info(f"  Total disk space: {format_bytes(total)}")
    
    if available < required_bytes:
        shortage = required_bytes - available
        logger.error(f"{Colors.RED}✗ INSUFFICIENT DISK SPACE{Colors.RESET}")
        logger.error(f"  Need {format_bytes(shortage)} more free space")
        logger.error(f"  Free up space or choose a different destination")
        return False
    
    # Warn if less than 20% space will remain
    remaining_after = available - remote_size_bytes
    percent_remaining = (remaining_after / total) * 100
    
    if percent_remaining < 20:
        logger.warning(f"⚠ Warning: Only {percent_remaining:.1f}% disk space will remain after transfer")
        logger.warning(f"  ({format_bytes(remaining_after)} free)")
    else:
        logger.info(f"{Colors.GREEN}✓ Sufficient disk space available{Colors.RESET}")
    
    return True


def verify_integrity(
    local_path: Path,
    remote_manifest: Set[str],
    remote_size_bytes: int,
    duration: float,
    remote_orphans: List[str]
) -> TransferStats:
    """
    Verify integrity of transferred files by checking MD5 checksums.
    
    Returns:
        TransferStats object with verification results
    """
    logger.info(f"\n{Colors.CYAN}--- Starting Integrity Verification ---{Colors.RESET}")
    
    local_files_map: Dict[str, Path] = {}
    total_local_size = 0
    source_folder = Path(REMOTE_DIR).name
    
    # Build local file inventory
    for item in local_path.rglob('*'):
        if item.is_file() and not item.name.startswith('.'):
            # Skip hidden files/folders
            if any(part.startswith('.') for part in item.parts):
                continue
                
            total_local_size += item.stat().st_size
            
            # Get relative path
            try:
                rel_path = item.relative_to(local_path)
            except ValueError:
                continue
            
            # Normalize path (remove source folder prefix if present)
            parts = rel_path.parts
            if parts and parts[0] == source_folder:
                normalized = Path(*parts[1:]) if len(parts) > 1 else Path('')
            else:
                normalized = rel_path
            
            if str(normalized):  # Skip empty paths
                local_files_map[str(normalized)] = item
    
    local_manifest = set(local_files_map.keys())
    missing_from_local = remote_manifest - local_manifest
    checksum_mismatches = []
    
    # Verify checksums for data files
    data_files = [f for f in sorted(local_manifest) if not f.endswith('.md5')]
    
    total_to_verify = len(data_files)
    logger.info(f"{Colors.CYAN}Verifying checksums for {total_to_verify} files...{Colors.RESET}")
    verified_count  = 0
    verify_start    = time.time()
    v_active_lines  = 0   # tracks live bar state for the verify phase
    LOG_INTERVAL_V  = 30  # seconds between file log entries
    last_log_time_v = verify_start

    def draw_verify_bar(current_file: str = "", final: bool = False) -> None:
        """Draw/update the two-line verification progress bar in place."""
        nonlocal v_active_lines
        if not sys.stdout.isatty():
            return
        pct    = (verified_count / total_to_verify) if total_to_verify > 0 else 1.0
        if final:
            pct = 1.0
        filled = int(32 * pct)
        bar    = '█' * filled + '░' * (32 - filled)
        elapsed_v  = time.time() - verify_start
        elapsed_str = format_eta(elapsed_v)
        if final or pct >= 1.0:
            eta_str = "ETA 00:00:00"
        elif elapsed_v > 1 and verified_count > 0:
            rate    = verified_count / elapsed_v
            remaining = total_to_verify - verified_count
            eta_str = f"ETA {format_eta(remaining / rate)}"
        else:
            eta_str = "ETA --:--:--"
        bar_line   = (f"{Colors.BOLD}[{bar}] {pct*100:5.1f}%  "
                      f"{verified_count}/{total_to_verify} verified"
                      f"  |  {elapsed_str} elapsed  |  {eta_str}{Colors.RESET}")
        file_label = (f"{Colors.CYAN}[verify] {Path(current_file).name}{Colors.RESET}"
                      if current_file else "")
        if v_active_lines > 0:
            sys.stdout.write('\033[1A\r')
        sys.stdout.write(bar_line + '\033[K\n\r' + file_label + '\033[K')
        sys.stdout.flush()
        v_active_lines = 2

    def close_verify_bar() -> None:
        """Finalize the verification bar (terminate live block cleanly)."""
        nonlocal v_active_lines
        if sys.stdout.isatty() and v_active_lines > 0:
            sys.stdout.write('\n')
            sys.stdout.flush()
        v_active_lines = 0

    for rel_path in data_files:
        full_path    = local_files_map[rel_path]
        sidecar_path = Path(str(full_path) + '.md5')

        draw_verify_bar(current_file=rel_path)

        if sidecar_path.exists():
            expected_md5 = extract_hash_from_sidecar(sidecar_path)

            if not expected_md5:
                close_verify_bar()
                logger.error(f"  Invalid sidecar format: {rel_path}.md5")
                continue

            actual_md5 = calculate_md5(full_path)

            if not actual_md5:
                close_verify_bar()
                logger.error(f"  Could not calculate MD5: {rel_path}")
                continue

            if actual_md5 == expected_md5:
                verified_count += 1
                # Log to file every LOG_INTERVAL_V seconds (time-based, not count-based)
                now = time.time()
                if now - last_log_time_v >= LOG_INTERVAL_V:
                    elapsed_v   = now - verify_start
                    rate        = verified_count / elapsed_v if elapsed_v > 1 else 0
                    rem         = total_to_verify - verified_count
                    eta_log     = format_eta(rem / rate) if rate > 0 and rem > 0 else '--:--:--'
                    pct_log     = verified_count / total_to_verify * 100
                    ts          = time.strftime('%Y-%m-%d %H:%M:%S')
                    file_handler.stream.write(
                        f"{ts} - INFO: [verify] {pct_log:.1f}%  "
                        f"{verified_count}/{total_to_verify} files"
                        f"  |  {format_eta(elapsed_v)} elapsed  |  ETA {eta_log}\n"
                    )
                    file_handler.stream.flush()
                    last_log_time_v = now
            else:
                close_verify_bar()
                logger.error(f"  MD5 MISMATCH: {rel_path}")
                logger.error(f"    Expected: {expected_md5}")
                logger.error(f"    Actual:   {actual_md5}")
                checksum_mismatches.append(rel_path)

    # Stamp 100% and close
    draw_verify_bar(final=True)
    close_verify_bar()
    logger.info(f"{Colors.GREEN}  ✓ Verified {verified_count}/{total_to_verify} files{Colors.RESET}")
    
    # Create stats object
    unverifiable = total_to_verify - verified_count - len(checksum_mismatches)
    stats = TransferStats(
        remote_file_count=len(remote_manifest),
        remote_size_bytes=remote_size_bytes,
        local_file_count=len(local_manifest),
        local_size=format_bytes(total_local_size),
        duration=duration,
        remote_orphans=remote_orphans,
        missing_files=missing_from_local,
        checksum_mismatches=checksum_mismatches,
        verified_count=verified_count,
        unverifiable_count=max(unverifiable, 0),
    )
    
    return stats


def print_final_report(stats: TransferStats) -> bool:
    """
    Print final integrity report structured around the three core preservation checks:
      1. Complete transfer  — every source file reached the destination
      2. Intact transfer    — every file's MD5 matches its sidecar
      3. Documented         — all findings logged with specifics

    Returns:
        True if all checks passed, False otherwise
    """
    ANOMALY_CAP = 100  # max individual filenames printed per anomaly type

    def _list_anomalies(items, label, log_fn, cap=ANOMALY_CAP):
        """Log up to cap filenames, then summarise the remainder."""
        shown = sorted(items)[:cap]
        for f in shown:
            log_fn(f"  → {f}")
        remainder = len(items) - len(shown)
        if remainder > 0:
            log_fn(
                f"  ... and {remainder} more (total {len(items)})."
                f" This volume of anomalies suggests a systemic issue."
                f" Check the source directory and re-run."
            )

    # ── Header ───────────────────────────────────────────────────────────────
    logger.info("\n" + Colors.BOLD + "=" * 60)
    logger.info("FINAL INTEGRITY REPORT")
    logger.info("=" * 60 + Colors.RESET)

    # ── Transfer summary ─────────────────────────────────────────────────────
    logger.info(f"Source : {stats.remote_file_count:>6} files  ({format_bytes(stats.remote_size_bytes)})")
    logger.info(f"Dest   : {stats.local_file_count:>6} files  ({stats.local_size})")
    logger.info(f"Duration: {stats.duration:.2f} seconds ({stats.duration/60:.1f} minutes)")
    logger.info("-" * 60)

    # ── Verification summary ─────────────────────────────────────────────────
    total_data = stats.verified_count + len(stats.checksum_mismatches) + stats.unverifiable_count
    logger.info(f"Checksums passed  : {stats.verified_count}/{total_data}")
    logger.info(f"Checksums failed  : {len(stats.checksum_mismatches)}/{total_data}")
    if stats.unverifiable_count:
        logger.info(f"Could not verify  : {stats.unverifiable_count}/{total_data}  (sidecar missing or unreadable)")
    logger.info("-" * 60)

    success = True

    # ── CHECK 1: Were all source files copied? ────────────────────────────────
    logger.info(Colors.BOLD + "CHECK 1: Complete transfer" + Colors.RESET)
    count_ok = stats.remote_file_count == stats.local_file_count
    missing_ok = len(stats.missing_files) == 0

    if count_ok and missing_ok:
        logger.info(
            f"{Colors.GREEN}  ✓ PASS — All {stats.remote_file_count} source files are present"
            f" at the destination.{Colors.RESET}"
        )
    else:
        success = False
        if not count_ok:
            diff = stats.local_file_count - stats.remote_file_count
            direction = f"+{diff}" if diff > 0 else str(diff)
            logger.error(
                f"  ✗ FAIL — File count mismatch:"
                f" source={stats.remote_file_count}, dest={stats.local_file_count}"
                f" ({direction})."
                f" Hidden files (.*) are excluded from both counts."
            )
        if stats.missing_files:
            logger.error(
                f"  ✗ FAIL — {len(stats.missing_files)} source file(s)"
                f" not found at destination:"
            )
            _list_anomalies(stats.missing_files, "missing", logger.error)

    # ── CHECK 2: Did every file transfer without corruption? ──────────────────
    logger.info(Colors.BOLD + "CHECK 2: Intact transfer (MD5 verification)" + Colors.RESET)
    if not stats.checksum_mismatches:
        logger.info(
            f"{Colors.GREEN}  ✓ PASS — All {stats.verified_count} verified file(s)"
            f" match their MD5 sidecars.{Colors.RESET}"
        )
    else:
        success = False
        logger.error(
            f"  ✗ FAIL — {len(stats.checksum_mismatches)} file(s) failed MD5 verification"
            f" (content does not match sidecar):"
        )
        _list_anomalies(stats.checksum_mismatches, "mismatch", logger.error)

    # ── Note on orphans (no sidecar — WARNING, not a failure) ────────────────
    if stats.remote_orphans:
        logger.warning(
            f"  ⚠ NOTE — {len(stats.remote_orphans)} source file(s) have no .md5 sidecar"
            f" and could not be verified (they were still copied):"
        )
        _list_anomalies(stats.remote_orphans, "orphan", logger.warning)
    else:
        logger.info(
            f"{Colors.GREEN}  ✓ All source files have .md5 sidecars.{Colors.RESET}"
        )

    # ── CHECK 3: Is the outcome documented? ──────────────────────────────────
    logger.info(Colors.BOLD + "CHECK 3: Documentation" + Colors.RESET)
    logger.info(f"  ✓ Full log written to:  {LOG_FILE}")
    logger.info(f"  ✓ Directory tree saved: {TREE_FILE}")
    if USE_CSV:
        logger.info(f"  ✓ CSV file list saved:  {CSV_FILE}")

    # ── Overall result ───────────────────────────────────────────────────────
    logger.info("=" * 60)
    if success:
        logger.info(
            f"{Colors.GREEN}{Colors.BOLD}"
            f"✓ SUCCESS — Transfer complete and verified.{Colors.RESET}"
        )
    else:
        logger.error(
            f"{Colors.RED}{Colors.BOLD}"
            f"✗ VERIFICATION FAILED — See CHECK results above for details.{Colors.RESET}"
        )
    logger.info(Colors.BOLD + "=" * 60 + Colors.RESET)

    return success


def run_rsync_transfer(src: str, dst: Path, total_bytes: int = 0, remote_dst: str = '') -> Tuple[int, float]:
    """
    Execute rsync transfer with progress monitoring.

    Args:
        src:         rsync source path (may include host prefix for remote transfers)
        dst:         Local destination directory
        total_bytes: Total expected bytes (used to drive the overall progress bar)

    Returns:
        Tuple of (return_code, duration)
    """
    start_time = time.time()
    
    # Base rsync command - optimized for speed by default
    rsync_cmd = [
        'rsync', '-av8', '--protect-args',
        '--exclude=.*', '--info=progress2', '--timeout=300',
    ]
    if IS_MACOS:
        rsync_cmd.insert(3, '--iconv=UTF-8-MAC,UTF-8')
    if not USE_LOCAL:
        rsync_cmd.extend(['-e', f'ssh -o ControlMaster=no -o ControlPath={CONTROL_SOCKET}'])
    
    # Add optional flags if requested
    if USE_COMPRESSION:
        rsync_cmd.append('-z')
        logger.info(f"{Colors.YELLOW}Compression enabled (will be slower but use less bandwidth){Colors.RESET}")
    
    if USE_RESUME:
        rsync_cmd.extend(['--partial', '--append-verify'])
        logger.info(f"{Colors.YELLOW}Resume mode enabled (will be slower but can resume interrupted transfers){Colors.RESET}")

    # Push mode: set open permissions on server so colleagues can access the files.
    # --no-owner / --no-group: don't attempt to preserve ownership (avoids permission errors).
    # --chmod: make all directories and files fully readable/writable/executable by everyone.
    if USE_PUSH:
        rsync_cmd.extend([
            '--no-owner',
            '--no-group',
            '--chmod=Du=rwx,Dgo=rwx,Fu=rwx,Fgo=rwx',
        ])
        logger.info(f"{Colors.YELLOW}Push mode: setting open permissions on server (--no-owner --no-group --chmod=Du=rwx,Dgo=rwx,Fu=rwx,Fgo=rwx){Colors.RESET}")

    # Add source and destination
    # In push mode, remote_dst overrides dst so rsync sends to the server.
    effective_dst = remote_dst if remote_dst else str(dst)
    rsync_cmd.extend([src, effective_dst])
    
    logger.info(f"{Colors.CYAN}Starting rsync transfer...{Colors.RESET}")
    logger.info(f"Command: {' '.join(rsync_cmd)}")
    
    try:
        process = subprocess.Popen(
            rsync_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors='surrogateescape',
            bufsize=1  # Line buffered
        )
        
        logger.info(f"{Colors.CYAN}Transfer in progress (live updates below)...{Colors.RESET}")
        last_activity_time = time.time()
        last_log_time = time.time()
        LOG_INTERVAL = 30  # Log progress to file every 30 seconds
        last_logged_line = ""

        # --- Live two-line display state ---
        # active_lines tracks how many terminal lines the live display currently
        # occupies so clear_live() and update_live() can reposition the cursor.
        active_lines       = 0      # 0 = no live block on screen; 2 = block is drawn
        files_done         = 0      # files transferred so far (from xfr# in progress2)
        total_files        = 0      # total file count (from to/ir-chk denominator)
        in_transfer_phase  = False  # True once rsync switches from ir-chk to to-chk
        transfer_start_time = 0.0   # time.time() at the moment to-chk first appears

        def clear_live() -> None:
            """Terminate the live display block so normal log output can follow."""
            nonlocal active_lines
            if sys.stdout.isatty() and active_lines > 0:
                sys.stdout.write('\n')   # finish the current line cleanly
                sys.stdout.flush()
            active_lines = 0

        def update_live(rsync_line: str) -> None:
            """
            Redraw the two-line live display in place.

            Line 1 – overall progress bar  (new)
            Line 2 – per-file rsync stats  (unchanged from original behaviour)
            """
            nonlocal active_lines
            if not sys.stdout.isatty():
                return

            # Bar percentage is always driven by file count.
            pct    = min(files_done / total_files, 1.0) if total_files > 0 else 0.0
            filled = int(32 * pct)
            bar    = '█' * filled + '░' * (32 - filled)

            size_ref = (f"  |  total {format_bytes(total_bytes)}" if total_bytes > 0 else "")

            if not in_transfer_phase:
                # Directory scan in progress — ETA would be meaningless here.
                files_part = (f"scanning… {files_done}/{total_files}"
                              if total_files > 0 else "scanning…")
                eta_part   = "ETA --:--:--"
            else:
                # Real file transfer underway — calculate ETA from the moment
                # to-chk first appeared, ignoring the fast directory-scan phase.
                elapsed_xfr = time.time() - transfer_start_time
                rate_fps        = files_done / elapsed_xfr if elapsed_xfr > 1 else 0
                remaining_files = total_files - files_done
                eta = (format_eta(remaining_files / rate_fps)
                       if rate_fps > 0 and remaining_files > 0 else '--:--:--')
                files_part = (f"{files_done}/{total_files} files"
                              if total_files > 0 else "transferring…")
                eta_part   = f"ETA {eta}"

            elapsed_total = time.time() - start_time
            elapsed_str   = format_eta(elapsed_total)

            bar_line = (f"{Colors.BOLD}[{bar}] {pct*100:5.1f}%  "
                        f"{files_part}{size_ref}  |  {elapsed_str} elapsed  |  {eta_part}{Colors.RESET}")
            rsync_display = f"{Colors.CYAN}[rsync] {rsync_line}{Colors.RESET}"

            if active_lines > 0:
                # Cursor is at end of line 2 (rsync line), no trailing newline.
                # Move up exactly 1 line to reach line 1 (bar), then carriage-return.
                sys.stdout.write('\033[1A\r')

            # Write line 1 then line 2.  \033[K clears any leftover characters
            # to the right so old wider content never bleeds through.
            sys.stdout.write(bar_line + '\033[K\n\r' + rsync_display + '\033[K')
            sys.stdout.flush()
            active_lines = 2

        while True:
            # Check for output with timeout
            reads = [process.stdout, process.stderr]
            ret = select.select(reads, [], [], 0.5)
            
            if process.stdout in ret[0]:
                line = process.stdout.readline()
                if line:
                    line = line.strip()
                    if line:
                        last_activity_time = time.time()
                        
                        # Handle progress lines (contain transfer stats)
                        if any(keyword in line for keyword in ['to-chk', 'ir-chk', 'xfr#', '%', '/s']):
                            current_time = time.time()

                            # Parse file counts from progress2 output (both phases):
                            #   (xfr#5, ir-chk=1052/1112)  ← initial scan
                            #   (xfr#5,  to-chk=245/300)   ← transfer
                            m = PROGRESS2_RE.search(line)
                            if m:
                                files_done  = int(m.group(1))
                                remaining_f = int(m.group(2))
                                total_files = int(m.group(3))
                                # Detect phase transition via chk marker on file-complete lines
                                if not in_transfer_phase and 'to-chk' in line:
                                    in_transfer_phase   = True
                                    transfer_start_time = time.time()

                            # Also catch mid-large-file progress lines: rsync emits
                            # bare "bytes  pct  speed  ETA" with no xfr#/chk marker
                            # while transferring a single file — no regex match above.
                            if not in_transfer_phase and '/s' in line and 'ir-chk' not in line:
                                in_transfer_phase   = True
                                transfer_start_time = time.time()

                            # Update terminal display
                            if sys.stdout.isatty():
                                update_live(line)
                            
                            # Log to file periodically (richer entry includes overall progress)
                            if current_time - last_log_time >= LOG_INTERVAL and line != last_logged_line:
                                pct_log  = (files_done / total_files * 100) if total_files > 0 else 0
                                ts       = time.strftime('%Y-%m-%d %H:%M:%S')
                                size_ref = f"  |  total {format_bytes(total_bytes)}" if total_bytes > 0 else ""
                                if in_transfer_phase and transfer_start_time > 0:
                                    elapsed_xfr = current_time - transfer_start_time
                                    rate_fps    = files_done / elapsed_xfr if elapsed_xfr > 1 else 0
                                    rem_files   = total_files - files_done
                                    eta_log     = format_eta(rem_files / rate_fps) if rate_fps > 0 and rem_files > 0 else '--:--:--'
                                    phase_label = "transfer"
                                else:
                                    eta_log     = "scanning"
                                    phase_label = "scan"
                                elapsed_log = format_eta(current_time - start_time)
                                file_handler.stream.write(
                                    f"{ts} - INFO: [progress:{phase_label}] {pct_log:.1f}%  "
                                    f"{files_done}/{total_files} files{size_ref}"
                                    f"  |  {elapsed_log} elapsed  |  ETA {eta_log}\n"
                                )
                                file_handler.stream.write(f"{ts} - INFO: [rsync] {line}\n")
                                file_handler.stream.flush()
                                last_log_time = current_time
                                last_logged_line = line
                        
                        # Log summary lines immediately
                        elif any(keyword in line.lower() for keyword in ['speedup', 'total size', 'sent', 'received']):
                            clear_live()
                            logger.info(f"{Colors.CYAN}[rsync] {line}{Colors.RESET}")
            
            if process.stderr in ret[0]:
                line = process.stderr.readline()
                if line:
                    last_activity_time = time.time()
                    clear_live()
                    logger.warning(f"[rsync stderr] {line.strip()}")
            
            # Show heartbeat dot only when no live display is active
            current_time = time.time()
            if active_lines == 0 and current_time - last_activity_time > PROGRESS_DOT_INTERVAL * 2:
                sys.stdout.write(f"{Colors.YELLOW}•{Colors.RESET}")
                sys.stdout.flush()
                last_activity_time = current_time
            
            # Check if process finished
            if process.poll() is not None:
                break
        
        # Get remaining output
        stdout, stderr = process.communicate()
        if stdout:
            for line in stdout.splitlines():
                line = line.strip()
                if line and any(keyword in line.lower() for keyword in ['total size', 'speedup', 'sent', 'received']):
                    clear_live()
                    logger.info(f"{Colors.CYAN}[rsync] {line}{Colors.RESET}")
        
        # On a clean exit, stamp the bar at 100% so it doesn't end mid-fill
        if process.returncode == 0 and sys.stdout.isatty():
            elapsed_total = time.time() - start_time
            elapsed_str   = format_eta(elapsed_total)
            bar           = '█' * 32
            size_ref      = f"  |  total {format_bytes(total_bytes)}" if total_bytes > 0 else ""
            files_label   = f"{total_files}/{total_files} files" if total_files > 0 else "complete"
            bar_line      = (f"{Colors.BOLD}[{bar}] 100.0%  "
                             f"{files_label}{size_ref}  |  {elapsed_str} elapsed  |  ETA 00:00:00{Colors.RESET}")
            if active_lines > 0:
                sys.stdout.write('\033[1A\r')
            sys.stdout.write(bar_line + '\033[K\n\r' + ' ' * 80 + '\033[K')
            sys.stdout.flush()
            active_lines = 2

        clear_live()
        
        duration = time.time() - start_time
        
        if process.returncode != 0:
            logger.warning(f"Rsync completed with exit code {process.returncode}")
            if stderr:
                logger.warning(f"Errors: {stderr.strip()}")
        else:
            logger.info(f"{Colors.GREEN}✓ Rsync completed successfully in {duration:.2f} seconds{Colors.RESET}")
        
        return process.returncode, duration
        
    except Exception as e:
        logger.error(f"Rsync execution error: {e}")
        return 1, time.time() - start_time



def get_remote_dest_stats(remote_path: str) -> Tuple[Set[str], int, List[str]]:
    """
    Get file inventory at the remote DESTINATION after a push transfer.
    Used for Check 1 (file count / missing file detection) in push mode.
    Reuses the same SSH batching pattern as get_remote_stats().

    Returns:
        Tuple of (file manifest, total size in bytes, orphan files without .md5)
    """
    logger.info(f"{Colors.CYAN}Gathering destination statistics on server...{Colors.RESET}")

    combined_cmd = f"""
    cd {remote_path} 2>/dev/null || exit 1
    find . -type f ! -path '*/.*' -print0 |
    while IFS= read -r -d '' file; do
        echo "FILE:$file"
    done
    total_bytes=$(find . -type f ! -path '*/.*' -exec stat -c%s {{}} + 2>/dev/null | awk '{{sum+=$1}} END {{print sum}}')
    echo "SIZE_BYTES:$total_bytes"
    """

    output = run_ssh_command(combined_cmd, timeout=SSH_TIMEOUT * 2)
    if not output:
        logger.error("Failed to gather destination statistics from server")
        return set(), 0, []

    manifest: Set[str] = set()
    total_bytes = 0

    for line in output.splitlines():
        if line.startswith("FILE:"):
            file_path = line[5:].lstrip('./')
            if file_path:
                manifest.add(file_path)
        elif line.startswith("SIZE_BYTES:"):
            try:
                total_bytes = int(line[11:].strip())
            except (ValueError, AttributeError):
                total_bytes = 0

    orphans = [
        f for f in sorted(manifest)
        if not f.endswith('.md5') and f"{f}.md5" not in manifest
    ]

    logger.info(
        f"{Colors.GREEN}✓ Server destination: {len(manifest)} files,"
        f" {format_bytes(total_bytes)}{Colors.RESET}"
    )
    return manifest, total_bytes, orphans


def verify_remote_integrity(
    source_manifest: Set[str],
    source_path: str,
    remote_dest_path: str,
    source_size_bytes: int,
    duration: float,
    source_orphans: List[str],
) -> TransferStats:
    """
    Verify integrity of a push transfer by running md5sum on the server.

    A single SSH session streams all hash results back as tagged lines:
      MATCH:<rel_path>
      MISMATCH:<rel_path>
      NOMD5:<rel_path>       — sidecar missing on server
      BADSIDECAR:<rel_path>  — sidecar unreadable / no hash found

    Returns:
        TransferStats object with verification results
    """
    logger.info(f"\n{Colors.CYAN}--- Starting Remote Integrity Verification ---{Colors.RESET}")

    # ── Build the remote file list (data files only, sorted) ─────────────────
    data_files = sorted(f for f in source_manifest if not f.endswith('.md5'))
    total_to_verify = len(data_files)
    logger.info(f"{Colors.CYAN}Verifying checksums for {total_to_verify} files on server...{Colors.RESET}")

    if not data_files:
        logger.warning("No data files to verify.")
        return TransferStats(
            remote_file_count=len(source_manifest),
            remote_size_bytes=source_size_bytes,
            local_file_count=len(source_manifest),
            local_size=format_bytes(source_size_bytes),
            duration=duration,
            remote_orphans=source_orphans,
            missing_files=set(),
            checksum_mismatches=[],
            verified_count=0,
            unverifiable_count=0,
        )

    # ── Build a single shell command that verifies every file ─────────────────
    # For each data file the server:
    #   1. Finds the expected MD5 from the .md5 sidecar
    #   2. Calculates the actual MD5 with md5sum
    #   3. Emits a tagged result line
    # Everything happens in one SSH session — no per-file round-trips.
    dest_base = remote_dest_path.rstrip('/')
    file_list_sh = " ".join(
        f"'{dest_base}/{f}'" for f in data_files
    )

    verify_cmd = f"""
cd {remote_dest_path} 2>/dev/null || {{ echo "CDERR:cannot cd to destination"; exit 1; }}

verify_file() {{
    local rel="$1"
    local full="{remote_dest_path.rstrip('/')}/$rel"
    local sidecar="$full.md5"

    if [ ! -f "$sidecar" ]; then
        echo "NOMD5:$rel"
        return
    fi

    # Extract the 32-char hex hash from the sidecar (first match)
    expected=$(grep -oE '[a-fA-F0-9]{{32}}' "$sidecar" | head -1)
    if [ -z "$expected" ]; then
        echo "BADSIDECAR:$rel"
        return
    fi

    actual=$(md5sum "$full" 2>/dev/null | awk '{{print $1}}')
    if [ -z "$actual" ]; then
        echo "BADSIDECAR:$rel"
        return
    fi

    if [ "$actual" = "$expected" ]; then
        echo "MATCH:$rel"
    else
        echo "MISMATCH:$rel"
    fi
}}

# Export function so subshell can use it if needed
export -f verify_file 2>/dev/null || true

{chr(10).join(f"verify_file '{f}'" for f in data_files)}
"""

    # ── Progress bar for remote verification ─────────────────────────────────
    verify_start   = time.time()
    processed      = 0
    verified_count = 0
    checksum_mismatches: List[str] = []
    unverifiable_count = 0
    v_active_lines = 0

    def draw_remote_bar(final: bool = False) -> None:
        nonlocal v_active_lines
        if not sys.stdout.isatty():
            return
        pct    = (processed / total_to_verify) if total_to_verify > 0 else 1.0
        if final:
            pct = 1.0
        filled = int(32 * pct)
        bar    = '█' * filled + '░' * (32 - filled)
        elapsed_v   = time.time() - verify_start
        elapsed_str = format_eta(elapsed_v)
        if final or pct >= 1.0:
            eta_str = "ETA 00:00:00"
        elif elapsed_v > 1 and processed > 0:
            rate      = processed / elapsed_v
            remaining = total_to_verify - processed
            eta_str   = f"ETA {format_eta(remaining / rate)}"
        else:
            eta_str = "ETA --:--:--"
        bar_line = (
            f"{Colors.BOLD}[{bar}] {pct*100:5.1f}%  "
            f"{processed}/{total_to_verify} verified  "
            f"|  {elapsed_str} elapsed  |  {eta_str}{Colors.RESET}"
        )
        status_line = (
            f"{Colors.CYAN}[verify:remote] waiting for server...{Colors.RESET}"
            if processed == 0 else
            f"{Colors.CYAN}[verify:remote] {verified_count} passed  "
            f"{len(checksum_mismatches)} failed  {unverifiable_count} unverifiable{Colors.RESET}"
        )
        if v_active_lines > 0:
            sys.stdout.write('\033[1A\r')
        sys.stdout.write(bar_line + '\033[K\n\r' + status_line + '\033[K')
        sys.stdout.flush()
        v_active_lines = 2

    def close_remote_bar() -> None:
        nonlocal v_active_lines
        if sys.stdout.isatty() and v_active_lines > 0:
            sys.stdout.write('\n')
            sys.stdout.flush()
        v_active_lines = 0

    # ── Stream the SSH session line-by-line so the bar updates in real time ─────
    # Each file emits one tagged line as soon as md5sum finishes, so we get a
    # progress update per file rather than waiting for the entire batch.
    LOG_INTERVAL_V    = 30
    HEARTBEAT_INTERVAL = 5        # seconds between bar refreshes while server is silent
    last_log_time_v   = verify_start
    last_heartbeat    = verify_start

    try:
        process = subprocess.Popen(
            ['ssh', '-o', 'ControlMaster=no',
             '-o', f'ControlPath={CONTROL_SOCKET}',
             f'{REMOTE_USER}@{REMOTE_HOST_ALIAS}', verify_cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors='surrogateescape',
        )
    except Exception as exc:
        logger.error(f"Could not launch SSH verification process: {{exc}}")
        draw_remote_bar(final=True)
        close_remote_bar()
    else:
        draw_remote_bar()   # show initial bar while connection is being established

        while True:
            reads = [process.stdout, process.stderr]
            ready, _, _ = select.select(reads, [], [], HEARTBEAT_INTERVAL)

            if process.stdout in ready:
                raw = process.stdout.readline()
                if not raw:
                    break
                line = raw.strip()
                if not line:
                    continue

                if line.startswith("MATCH:"):
                    verified_count += 1
                    processed += 1
                    draw_remote_bar()

                    now = time.time()
                    last_heartbeat = now
                    if now - last_log_time_v >= LOG_INTERVAL_V:
                        elapsed_v = now - verify_start
                        rate      = processed / elapsed_v if elapsed_v > 1 else 0
                        rem       = total_to_verify - processed
                        eta_log   = format_eta(rem / rate) if rate > 0 and rem > 0 else '--:--:--'
                        pct_log   = processed / total_to_verify * 100
                        ts        = time.strftime('%Y-%m-%d %H:%M:%S')
                        file_handler.stream.write(
                            f"{{ts}} - INFO: [verify:remote] {{pct_log:.1f}}%  "
                            f"{{processed}}/{{total_to_verify}} files"
                            f"  |  {{format_eta(elapsed_v)}} elapsed  |  ETA {{eta_log}}\n"
                        )
                        file_handler.stream.flush()
                        last_log_time_v = now

                elif line.startswith("MISMATCH:"):
                    rel = line[9:]
                    checksum_mismatches.append(rel)
                    processed += 1
                    last_heartbeat = time.time()
                    close_remote_bar()
                    logger.error(f"  MD5 MISMATCH on server: {{rel}}")
                    draw_remote_bar()

                elif line.startswith("NOMD5:"):
                    rel = line[6:]
                    unverifiable_count += 1
                    processed += 1
                    last_heartbeat = time.time()
                    close_remote_bar()
                    logger.warning(f"  No .md5 sidecar on server for: {{rel}}")
                    draw_remote_bar()

                elif line.startswith("BADSIDECAR:"):
                    rel = line[11:]
                    unverifiable_count += 1
                    processed += 1
                    last_heartbeat = time.time()
                    close_remote_bar()
                    logger.warning(f"  Unreadable sidecar on server for: {{rel}}")
                    draw_remote_bar()

                elif line.startswith("CDERR:"):
                    close_remote_bar()
                    logger.error(f"  Server error: {{line[6:]}}")

            if process.stderr in ready:
                err = process.stderr.readline()
                if err and err.strip():
                    close_remote_bar()
                    logger.warning(f"  [ssh stderr] {{err.strip()}}")
                    draw_remote_bar()

            # Heartbeat: if no output for HEARTBEAT_INTERVAL seconds, refresh the
            # elapsed timer so the user knows the server is still hashing.
            now = time.time()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                draw_remote_bar()
                last_heartbeat = now

            if process.poll() is not None:
                # Drain any remaining stdout
                for raw in process.stdout:
                    line = raw.strip()
                    if line.startswith("MATCH:"):
                        verified_count += 1
                        processed += 1
                    elif line.startswith("MISMATCH:"):
                        checksum_mismatches.append(line[9:])
                        processed += 1
                    elif line.startswith(("NOMD5:", "BADSIDECAR:")):
                        unverifiable_count += 1
                        processed += 1
                    draw_remote_bar()
                break

        process.wait()

    draw_remote_bar(final=True)
    close_remote_bar()
    logger.info(
        f"{Colors.GREEN}  ✓ Remote verification complete: "
        f"{verified_count}/{total_to_verify} passed{Colors.RESET}"
    )

    # ── Build stats: use remote dest manifest for local_file_count ────────────
    # (populated by get_remote_dest_stats() earlier; passed through source_manifest
    #  here since both should match after a clean transfer)
    return TransferStats(
        remote_file_count=len(source_manifest),
        remote_size_bytes=source_size_bytes,
        local_file_count=len(source_manifest),   # placeholder; report gets real count
        local_size=format_bytes(source_size_bytes),
        duration=duration,
        remote_orphans=source_orphans,
        missing_files=set(),                      # populated by caller from dest stats
        checksum_mismatches=checksum_mismatches,
        verified_count=verified_count,
        unverifiable_count=unverifiable_count,
    )


def generate_source_tree(source_path: str, tree_file: str, label: str = "source") -> None:
    """
    Write a directory tree of the source folder to a .tree file.

    Tries the system `tree` command first (available via Homebrew on macOS,
    built-in on Ubuntu). Falls back to a pure-Python implementation if `tree`
    is not installed, so the output is never silently skipped.

    Output includes file sizes (-s) and omits hidden files (-I '.*').
    The .tree file is saved alongside the .log with the same base name.
    """
    import shutil as _shutil

    header = (
        f"{label.capitalize()} directory tree: {source_path}\n"
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        + "=" * 60 + "\n"
    )

    tree_output = None

    # ── Try system tree command ───────────────────────────────────────────────
    if _shutil.which('tree'):
        try:
            result = subprocess.run(
                ['tree', '-sh', '--du', '-I', '.*', source_path],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0 and result.stdout.strip():
                tree_output = result.stdout
        except Exception:
            pass  # Fall through to Python implementation

    # ── Python fallback ───────────────────────────────────────────────────────
    if tree_output is None:
        logger.info(f"{Colors.YELLOW}  `tree` not found — using built-in directory listing{Colors.RESET}")
        lines = []

        def _py_tree(path: Path, prefix: str = '') -> None:
            # Sort: directories first, then files, both alphabetically
            try:
                entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except PermissionError:
                lines.append(prefix + '[permission denied]')
                return

            visible = [e for e in entries if not e.name.startswith('.')]
            for i, entry in enumerate(visible):
                connector = '└── ' if i == len(visible) - 1 else '├── '
                extension = '    ' if i == len(visible) - 1 else '│   '
                if entry.is_dir():
                    lines.append(f"{prefix}{connector}{entry.name}/")
                    _py_tree(entry, prefix + extension)
                else:
                    try:
                        size = entry.stat().st_size
                        size_str = format_bytes(size)
                    except OSError:
                        size_str = '?'
                    lines.append(f"{prefix}{connector}{entry.name}  [{size_str}]")

        lines.append(str(source_path))
        _py_tree(Path(source_path))

        # Summary counts
        all_files = [f for f in Path(source_path).rglob('*')
                     if f.is_file() and not any(p.startswith('.') for p in f.parts)]
        all_dirs  = [d for d in Path(source_path).rglob('*')
                     if d.is_dir()  and not any(p.startswith('.') for p in d.parts)]
        lines.append('')
        lines.append(f"{len(all_dirs)} directories, {len(all_files)} files")
        tree_output = '\n'.join(lines)

    # ── Write to .tree file ───────────────────────────────────────────────────
    try:
        Path(tree_file).parent.mkdir(parents=True, exist_ok=True)
        with open(tree_file, 'w', encoding='utf-8', errors='replace') as f:
            f.write(header)
            f.write(tree_output)
            f.write('\n')
        logger.info(f"{Colors.GREEN}✓ Directory tree saved: {tree_file}{Colors.RESET}")
    except Exception as e:
        logger.error(f"Could not write tree file: {e}")


def generate_csv_filelist(source_path: str, csv_file: str) -> None:
    """
    Write a CSV file listing every non-hidden file in source_path with:
      - File Name   (filename only, no path)
      - Extension   (including the dot, e.g. ".mov"; blank for files with none)
      - Relative Path (path relative to source_path)
      - Size        (in the most useful unit: KB < 1 MB, MB < 1 GB, otherwise GB)

    The CSV is saved alongside the .log and .tree files and named:
      <source_folder>_<timestamp>_filelist.csv
    """
    import csv as _csv

    def _human_size(size_bytes: int) -> str:
        """Return size in the most readable unit, rounded to 2 decimal places."""
        if size_bytes < 1_048_576:          # < 1 MB → KB
            return f"{size_bytes / 1_024:.2f} KB"
        elif size_bytes < 1_073_741_824:    # < 1 GB → MB
            return f"{size_bytes / 1_048_576:.2f} MB"
        else:                               # ≥ 1 GB → GB
            return f"{size_bytes / 1_073_741_824:.2f} GB"

    src = Path(source_path)
    rows = []

    for item in sorted(src.rglob('*'), key=lambda p: (str(p.parent), p.name)):
        if any(part.startswith('.') for part in item.parts):
            continue
        if not item.is_file():
            continue
        try:
            size_bytes = item.stat().st_size
        except OSError:
            size_bytes = 0

        suffix = item.suffix          # e.g. ".mov" or ".md5" or "" for no extension
        rows.append({
            'File Name':     item.name,
            'Extension':     suffix,
            'Relative Path': str(item.relative_to(src)),
            'Size':          _human_size(size_bytes),
        })

    try:
        Path(csv_file).parent.mkdir(parents=True, exist_ok=True)
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = _csv.DictWriter(
                f,
                fieldnames=['File Name', 'Extension', 'Relative Path', 'Size'],
            )
            writer.writeheader()
            writer.writerows(rows)
        logger.info(
            f"{Colors.GREEN}✓ CSV file list saved: {csv_file}"
            f" ({len(rows)} files){Colors.RESET}"
        )
    except Exception as e:
        logger.error(f"Could not write CSV file list: {e}")


def replicate() -> bool:
    """
    Main replication function. Supports both SFTP (remote) and local disk-to-disk modes.
    
    Returns:
        True if replication and verification succeeded, False otherwise
    """
    if USE_PUSH:
        mode_label = f"PUSH → {REMOTE_HOST_ALIAS}"
    elif USE_LOCAL:
        mode_label = "LOCAL"
    else:
        mode_label = f"SFTP → {REMOTE_HOST_ALIAS}"

    logger.info(Colors.BOLD + "="*60)
    logger.info(f"Starting replication  [{mode_label}]")
    logger.info(f"Source: {REMOTE_DIR}")
    logger.info(f"Dest:   {LOCAL_DIR}")
    logger.info("="*60 + Colors.RESET)

    if USE_PUSH:
        # ── Push mode: local → remote server ────────────────────────────────
        if not check_ssh_socket():
            return False

        if not verify_ssh_connection():
            logger.error("Cannot proceed without SSH connection")
            return False

        if not check_local_path(REMOTE_DIR, 'Source'):
            return False

        # Compute the actual remote landing directory up front.
        # rsync copies the source folder itself into LOCAL_DIR, so files land
        # at LOCAL_DIR/<source_folder_name>/ — not at LOCAL_DIR/ directly.
        source_folder      = Path(REMOTE_DIR).name
        remote_actual_dest = LOCAL_DIR.rstrip('/') + '/' + source_folder

        # Verify the parent destination exists on the server
        if not check_remote_path(LOCAL_DIR, 'Destination parent'):
            return False

        # Create the specific subdirectory for this batch if requested.
        # We create and chmod remote_actual_dest (e.g. /pool0/smpl2/batch_name),
        # NOT LOCAL_DIR (the parent) which we don't own and can't chmod.
        if USE_CREATE_DEST:
            logger.info(f"{Colors.CYAN}Creating destination directory on server: {remote_actual_dest}{Colors.RESET}")
            mk_result = run_ssh_command(
                f"mkdir -p '{remote_actual_dest}' && chmod 777 '{remote_actual_dest}'",
                timeout=15,
            )
            if mk_result is None:
                logger.error(f"{Colors.RED}✗ Could not create directory on server: {remote_actual_dest}{Colors.RESET}")
                logger.error("  Check that you have write permission to the parent directory on the server.")
                return False
            logger.info(f"{Colors.GREEN}✓ Destination directory created: {remote_actual_dest}{Colors.RESET}")

        logger.info(f"{Colors.CYAN}Files will land at: {remote_actual_dest}{Colors.RESET}")

        # Gather local source stats
        source_manifest, source_size_bytes, source_orphans = get_local_stats(REMOTE_DIR)
        if not source_manifest:
            logger.error("No files found in source directory or error occurred")
            return False

        # Push: src is local, dst is remote (no local Path object needed)
        dst_remote = f"{REMOTE_USER}@{REMOTE_HOST_ALIAS}:{LOCAL_DIR}"
        return_code, duration = run_rsync_transfer(REMOTE_DIR, Path(LOCAL_DIR), source_size_bytes,
                                                    remote_dst=dst_remote)

        if return_code != 0:
            logger.error("Rsync push failed — skipping verification")
            return False

        # Pre-flight: count files at the actual remote subdirectory
        dest_manifest, dest_size_bytes, _ = get_remote_dest_stats(remote_actual_dest)
        missing_files = source_manifest - dest_manifest

        # Remote MD5 verification — look in the actual subdirectory
        stats = verify_remote_integrity(
            source_manifest, REMOTE_DIR, remote_actual_dest,
            source_size_bytes, duration, source_orphans,
        )

        # Patch in the real remote dest counts for the report
        stats.local_file_count = len(dest_manifest)
        stats.local_size       = format_bytes(dest_size_bytes)
        stats.missing_files    = missing_files

    elif USE_LOCAL:
        # ── Local mode: no SSH needed ────────────────────────────────────────
        if not check_local_path(REMOTE_DIR, 'Source'):
            return False

        source_manifest, source_size_bytes, source_orphans = get_local_stats(REMOTE_DIR)

        if not source_manifest:
            logger.error("No files found in source directory or error occurred")
            return False

        local_path = Path(LOCAL_DIR)
        local_path.mkdir(parents=True, exist_ok=True)

        if not check_disk_space(local_path, source_size_bytes):
            logger.error("Aborting transfer due to insufficient disk space")
            return False

        # For local rsync, use the source path directly (no host prefix)
        src = REMOTE_DIR
        return_code, duration = run_rsync_transfer(src, local_path, source_size_bytes)

        # Verify integrity locally
        stats = verify_integrity(local_path, source_manifest, source_size_bytes, duration, source_orphans)

    else:
        # ── SFTP/remote mode: SSH required (pull from server) ────────────────
        if not check_ssh_socket():
            return False

        if not verify_ssh_connection():
            logger.error("Cannot proceed without SSH connection")
            return False

        if not check_remote_path(REMOTE_DIR, 'Source'):
            return False
        if not check_local_path(str(Path(LOCAL_DIR).parent), 'Destination parent'):
            return False

        source_manifest, source_size_bytes, source_orphans = get_remote_stats(REMOTE_DIR)

        if not source_manifest:
            logger.error("No files found on remote server or error occurred")
            return False

        local_path = Path(LOCAL_DIR)
        local_path.mkdir(parents=True, exist_ok=True)

        if not check_disk_space(local_path, source_size_bytes):
            logger.error("Aborting transfer due to insufficient disk space")
            return False

        src = f"{REMOTE_USER}@{REMOTE_HOST_ALIAS}:{REMOTE_DIR}"
        return_code, duration = run_rsync_transfer(src, local_path, source_size_bytes)

        # Verify integrity locally
        stats = verify_integrity(local_path, source_manifest, source_size_bytes, duration, source_orphans)

    # Write companion directory tree.
    # For pull mode the source is remote, so we tree the local destination instead.
    # For push and local modes the source is always local.
    if USE_PUSH or USE_LOCAL:
        tree_path = REMOTE_DIR   # local source
        tree_label = 'source'
    else:
        tree_path = str(local_path)  # local destination (pull mode)
        tree_label = 'destination'
    generate_source_tree(tree_path, TREE_FILE, label=tree_label)

    # Print report (same structure for all modes)
    success = print_final_report(stats)

    # Optional CSV file list
    if USE_CSV:
        generate_csv_filelist(tree_path, CSV_FILE)

    return success and return_code == 0



def main():
    """
    Entry point. All argument parsing, logging setup, and execution live here.
    Static config and function definitions are at module level so importing
    this module does not trigger any side effects.
    """
    global file_handler, logger

    # ── Usage ─────────────────────────────────────────────────────────────────
    def print_usage():
        print("Usage:")
        print(f"  {sys.argv[0]} <SOURCE_DIR> <DEST_DIR> [OPTIONS]")
        print()
        print("Options:")
        print("  --open-ssh        Open a persistent SSH session for Duo 2FA (run this first)")
        print("  --push            Push local files TO the remote server (reverses direction)")
        print("  --create-dest     Create destination directory on server if it does not exist")
        print("                    (only valid with --push; uses open rwx permissions)")
        print("  --local           Replicate from a local directory (no SSH required)")
        print("  --compress, -z    Enable compression (slower but uses less bandwidth)")
        print("  --resume          Enable resume for interrupted transfers (slower)")
        print("  --csv             Generate a CSV file list alongside the log and tree")
        print("  --help, -h        Show this message")
        print()
        print("Examples (SFTP/remote):")
        print(f"  {sys.argv[0]} /pool0/smpl2/digreq-2664 /Users/mangelet/Desktop/copy")
        print(f"  {sys.argv[0]} /pool0/smpl2/digreq-2664 /Users/mangelet/Desktop/copy --compress")
        print()
        print("Examples (local disk-to-disk):")
        if IS_MACOS:
            print(f"  {sys.argv[0]} /Volumes/MediaDrive/digreq-2664 /Users/mangelet/Desktop/copy --local")
            print(f"  {sys.argv[0]} /Volumes/MediaDrive/digreq-2664 /Volumes/BackupDrive/copy --local --resume")
        else:
            print(f"  {sys.argv[0]} /media/MediaDrive/digreq-2664 /home/mangelet/copy --local")
            print(f"  {sys.argv[0]} /media/MediaDrive/digreq-2664 /media/BackupDrive/copy --local --resume")

    # ── --help ────────────────────────────────────────────────────────────────
    if any(arg in sys.argv[1:] for arg in ['--help', '-h']):
        print_usage()
        sys.exit(0)

    # ── --open-ssh: open persistent SSH session for Duo 2FA ──────────────────
    if '--open-ssh' in sys.argv[1:]:
        socket_path = CONTROL_SOCKET.replace('%h', REMOTE_HOST_ALIAS)
        print(f'Opening persistent SSH connection to {REMOTE_USER}@{REMOTE_HOST_ALIAS}...')
        print('Please complete the Duo prompt. Leave this terminal open while srd runs.')
        print()
        try:
            subprocess.run([
                'ssh', '-M', '-S', socket_path,
                '-o', 'ControlPersist=yes', '-N',
                f'{REMOTE_USER}@{REMOTE_HOST_ALIAS}',
            ], check=True)
            print(f'\n\u2713 SSH session open. Socket: {socket_path}')
            print('  You can now run srd normally in a separate terminal.')
        except subprocess.CalledProcessError:
            print('\n\u2717 Failed to open SSH connection.')
            sys.exit(1)
        except KeyboardInterrupt:
            print('\nCancelled.')
            sys.exit(130)
        sys.exit(0)

    # ── Argument validation ───────────────────────────────────────────────────
    if len(sys.argv) < 3:
        print("Error: Invalid number of arguments")
        print()
        print_usage()
        sys.exit(1)

    global REMOTE_DIR, LOCAL_DIR
    global USE_COMPRESSION, USE_RESUME, USE_LOCAL, USE_PUSH, USE_CREATE_DEST, USE_CSV
    global LOG_FILE, TREE_FILE, CSV_FILE

    REMOTE_DIR = sys.argv[1]
    LOCAL_DIR  = sys.argv[2]

    USE_COMPRESSION = False
    USE_RESUME      = False
    USE_LOCAL       = False
    USE_PUSH        = False
    USE_CREATE_DEST = False
    USE_CSV         = False

    for arg in sys.argv[3:]:
        if arg in ['--compress', '-z']:
            USE_COMPRESSION = True
        elif arg == '--resume':
            USE_RESUME = True
        elif arg == '--local':
            USE_LOCAL = True
        elif arg == '--push':
            USE_PUSH = True
        elif arg == '--create-dest':
            USE_CREATE_DEST = True
        elif arg == '--csv':
            USE_CSV = True
        else:
            print(f"Error: Unknown option '{arg}'")
            sys.exit(1)

    if USE_PUSH and USE_LOCAL:
        print("Error: --push and --local are mutually exclusive")
        sys.exit(1)

    if USE_CREATE_DEST and not USE_PUSH:
        print("Error: --create-dest is only valid with --push")
        sys.exit(1)

    # ── Log / tree / CSV filenames ────────────────────────────────────────────
    remote_dir_name = Path(REMOTE_DIR).name
    timestamp       = datetime.now().strftime("%Y%m%d_%H%M%S")
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    LOG_FILE  = str(Path(LOG_DIR) / f"{remote_dir_name}_{timestamp}_replication.log")
    TREE_FILE = str(Path(LOG_DIR) / f"{remote_dir_name}_{timestamp}_source.tree")
    CSV_FILE  = str(Path(LOG_DIR) / f"{remote_dir_name}_{timestamp}_filelist.csv")

    # ── Logging setup ─────────────────────────────────────────────────────────
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8', errors='surrogateescape')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s: %(message)s'))

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(ColoredFormatter())

    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # ── Header ────────────────────────────────────────────────────────────────
    _platform_label = "macOS" if IS_MACOS else "Ubuntu 24.04"
    SCRIPT_HEADER = f"""=========================
Stanford Media Preservation Lab
SMPL Replicate Directory (srd)
v1.0 -- April 2026 ({_platform_label})
========================="""
    print(SCRIPT_HEADER)
    print()
    file_handler.stream.write(SCRIPT_HEADER + "\n\n")
    file_handler.stream.flush()

    # ── Run ───────────────────────────────────────────────────────────────────
    try:
        success = replicate()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.warning("\nOperation cancelled by user")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
