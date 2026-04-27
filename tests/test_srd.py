"""
Basic tests for srd utility functions.
These tests cover pure-Python logic that can run without rsync or SSH.
"""

import sys
import tempfile
import hashlib
from pathlib import Path

# ── Helpers duplicated here for testability ───────────────────────────────────

def format_bytes(num_bytes: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if num_bytes < 1024.0:
            return f"{num_bytes:.1f}{unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f}PB"

def format_eta(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def human_size(size_bytes: int) -> str:
    if size_bytes < 1_048_576:
        return f"{size_bytes / 1_024:.2f} KB"
    elif size_bytes < 1_073_741_824:
        return f"{size_bytes / 1_048_576:.2f} MB"
    else:
        return f"{size_bytes / 1_073_741_824:.2f} GB"

def extract_hash_from_sidecar(sidecar_path: Path):
    import re
    try:
        content = sidecar_path.read_text(errors='replace')
        match = re.search(r'[a-fA-F0-9]{32}', content)
        return match.group(0).lower() if match else None
    except OSError:
        return None

def calculate_md5(file_path: Path):
    md5 = hashlib.md5()
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                md5.update(chunk)
        return md5.hexdigest()
    except OSError:
        return None


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestFormatBytes:
    def test_bytes(self):
        assert format_bytes(512) == "512.0B"

    def test_kilobytes(self):
        assert format_bytes(1024) == "1.0KB"

    def test_megabytes(self):
        assert format_bytes(1024 * 1024) == "1.0MB"

    def test_gigabytes(self):
        assert format_bytes(1024 ** 3) == "1.0GB"

    def test_terabytes(self):
        assert format_bytes(1024 ** 4) == "1.0TB"


class TestFormatEta:
    def test_zero(self):
        assert format_eta(0) == "00:00:00"

    def test_seconds(self):
        assert format_eta(90) == "00:01:30"

    def test_hours(self):
        assert format_eta(3661) == "01:01:01"

    def test_negative_clamped_to_zero(self):
        assert format_eta(-5) == "00:00:00"


class TestHumanSize:
    def test_kb(self):
        result = human_size(512)
        assert result.endswith("KB")

    def test_mb(self):
        result = human_size(50 * 1024 * 1024)
        assert result.endswith("MB")
        assert result.startswith("50.00")

    def test_gb(self):
        result = human_size(2 * 1024 ** 3)
        assert result.endswith("GB")
        assert result.startswith("2.00")


class TestMd5Verification:
    def test_calculate_md5(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mov') as f:
            f.write(b'test content')
            tmp = Path(f.name)
        expected = hashlib.md5(b'test content').hexdigest()
        assert calculate_md5(tmp) == expected
        tmp.unlink()

    def test_extract_hash_from_sidecar_bare(self):
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.md5') as f:
            f.write('d41d8cd98f00b204e9800998ecf8427e')
            tmp = Path(f.name)
        assert extract_hash_from_sidecar(tmp) == 'd41d8cd98f00b204e9800998ecf8427e'
        tmp.unlink()

    def test_extract_hash_from_sidecar_with_filename(self):
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.md5') as f:
            f.write('d41d8cd98f00b204e9800998ecf8427e  file.mov\n')
            tmp = Path(f.name)
        assert extract_hash_from_sidecar(tmp) == 'd41d8cd98f00b204e9800998ecf8427e'
        tmp.unlink()

    def test_md5_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'file.mov'
            sidecar = Path(tmp) / 'file.mov.md5'
            data.write_bytes(b'hello preservation')
            actual = calculate_md5(data)
            sidecar.write_text(actual)
            assert extract_hash_from_sidecar(sidecar) == actual

    def test_md5_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'file.mov'
            sidecar = Path(tmp) / 'file.mov.md5'
            data.write_bytes(b'hello preservation')
            sidecar.write_text('deadbeefdeadbeefdeadbeefdeadbeef')
            assert extract_hash_from_sidecar(sidecar) != calculate_md5(data)


class TestHiddenFileExclusion:
    def test_hidden_files_excluded_from_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp)
            (src / 'visible.mov').write_bytes(b'data')
            (src / '.DS_Store').write_bytes(b'hidden')
            (src / '.hidden_dir').mkdir()
            (src / '.hidden_dir' / 'also_hidden.mov').write_bytes(b'data')

            manifest = set()
            for item in src.rglob('*'):
                if any(part.startswith('.') for part in item.parts):
                    continue
                if item.is_file():
                    manifest.add(str(item.relative_to(src)))

            assert 'visible.mov' in manifest
            assert '.DS_Store' not in manifest
            assert not any('.hidden_dir' in f for f in manifest)
