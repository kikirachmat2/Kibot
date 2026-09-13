#!/usr/bin/env python3
"""
KiBot Sovereign Disk Cleaner
=============================
Otomatis deteksi & bersihkan sampah disk yang bikin server penuh.
Aman dijalankan kapan saja. Tidak akan hapus file trading aktif.

Usage:
  python3 sovereign_disk_cleaner.py           # Dry-run (lihat apa yang akan dihapus)
  python3 sovereign_disk_cleaner.py --execute # Jalankan cleanup beneran
  python3 sovereign_disk_cleaner.py --report  # Laporan disk usage saja
  python3 sovereign_disk_cleaner.py --schedule # Install cronjob otomatis (setiap jam 03:00)
"""

from __future__ import annotations
import os
import sys
import shutil
import subprocess
import time
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Any

# ───────────────────────────────────────────────
#  KONFIGURASI
# ───────────────────────────────────────────────
KIBOT_ROOT = Path("/home/ubuntu/KiBot")
HOME_DIR   = Path("/home/ubuntu")
LOG_DIR    = KIBOT_ROOT / "logs"
STATE_DIR  = KIBOT_ROOT / "state"

# File/folder yang TIDAK BOLEH disentuh
PROTECTED = {
    KIBOT_ROOT / ".env",
    KIBOT_ROOT / ".env.kiv",
    KIBOT_ROOT / "state" / "active_trades.json",
    KIBOT_ROOT / "state" / "learning_state.json",
    KIBOT_ROOT / "state" / "active_strategy.json",
    KIBOT_ROOT / "state" / "risk_state.json",
}

# Ambang batas disk (%) sebelum mode agresif aktif
DISK_WARNING_PCT  = 85
DISK_CRITICAL_PCT = 95

# Log cleaner
CLEANER_LOG = STATE_DIR / "disk_cleaner.log"

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] 🧹 DISK-CLEANER - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("SovereignDiskCleaner")


# ───────────────────────────────────────────────
#  HELPER
# ───────────────────────────────────────────────
def human_size(size_bytes: float | int) -> str:
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if abs(size) < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def disk_usage_pct(path: str = "/") -> Tuple[int, int, float]:
    """Returns (used_bytes, free_bytes, pct_used)."""
    stat = shutil.disk_usage(path)
    pct  = (stat.used / stat.total) * 100
    return stat.used, stat.free, round(pct, 1)


def is_protected(path: Path) -> bool:
    for p in PROTECTED:
        if path == p or p in path.parents:
            return True
    return False


def safe_remove(path: Path, dry_run: bool = True) -> int:
    """Remove file or dir. Returns bytes freed (0 on dry-run or error)."""
    if is_protected(path):
        logger.warning(f"  ⛔ PROTECTED, skip: {path}")
        return 0

    try:
        size = 0
        if path.is_file() or path.is_symlink():
            size = path.stat().st_size if path.is_file() else 0
            if not dry_run:
                path.unlink(missing_ok=True)
        elif path.is_dir():
            size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            if not dry_run:
                shutil.rmtree(path, ignore_errors=True)

        action = "Would remove" if dry_run else "Removed"
        logger.info(f"  {'🔍' if dry_run else '🗑️'}  {action}: {path} ({human_size(size)})")
        return size
    except Exception as e:
        logger.error(f"  ❌ Failed on {path}: {e}")
        return 0


# ───────────────────────────────────────────────
#  TARGET PEMBERSIHAN
# ───────────────────────────────────────────────

def find_recursive_repo_clones(dry_run: bool) -> int:
    """
    Deteksi folder KiBot yang nested (KiBot/KiBot/KiBot/...).
    Ini penyebab utama 153GB terbuang.
    """
    freed = 0
    logger.info("🔍 [1] Scanning recursive KiBot clones...")

    # Cari semua .git di dalam KIBOT_ROOT (selain root itu sendiri)
    for git_dir in KIBOT_ROOT.rglob(".git"):
        candidate = git_dir.parent
        if candidate == KIBOT_ROOT:
            continue  # Skip root repo itu sendiri
        logger.info(f"     Found nested repo: {candidate}")
        freed += safe_remove(candidate, dry_run)

    return freed


def clean_playwright_cache(dry_run: bool) -> int:
    """Hapus Playwright browser cache (~428MB+)."""
    freed = 0
    logger.info("🔍 [2] Cleaning Playwright/browser cache...")

    candidates = [
        HOME_DIR / ".cache" / "ms-playwright",
        HOME_DIR / ".local" / "share" / "ms-playwright",
    ]
    # Juga cari nested di dalam KiBot
    for nested in KIBOT_ROOT.rglob("ms-playwright"):
        candidates.append(nested)

    for p in candidates:
        if p.exists():
            freed += safe_remove(p, dry_run)

    return freed


def clean_python_cache(dry_run: bool) -> int:
    """Hapus __pycache__ dan .pyc files."""
    freed = 0
    logger.info("🔍 [3] Cleaning Python cache (__pycache__, .pyc)...")

    for cache_dir in KIBOT_ROOT.rglob("__pycache__"):
        freed += safe_remove(cache_dir, dry_run)

    for pyc in KIBOT_ROOT.rglob("*.pyc"):
        freed += safe_remove(pyc, dry_run)

    for pyc in KIBOT_ROOT.rglob("*.pyo"):
        freed += safe_remove(pyc, dry_run)

    return freed


def clean_application_logs(dry_run: bool, max_age_days: int = 3) -> int:
    """Hapus log aplikasi lama. Pertahankan 3 hari terakhir."""
    freed = 0
    logger.info(f"🔍 [4] Cleaning application logs older than {max_age_days} days...")

    cutoff = time.time() - (max_age_days * 86400)

    # Logs di LOG_DIR
    if LOG_DIR.exists():
        for f in LOG_DIR.rglob("*.log"):
            if f.stat().st_mtime < cutoff and not is_protected(f):
                freed += safe_remove(f, dry_run)

        for f in LOG_DIR.rglob("*.log.old"):
            freed += safe_remove(f, dry_run)

        for f in LOG_DIR.rglob("*.log.gz"):
            freed += safe_remove(f, dry_run)

    # Rotated logs di root log path
    for f in KIBOT_ROOT.rglob("*.log"):
        if f.stat().st_mtime < cutoff and not is_protected(f):
            freed += safe_remove(f, dry_run)

    # Truncate logs yang sangat besar (>100MB) tapi masih aktif → potong ke 10MB terakhir
    if not dry_run:
        for f in LOG_DIR.rglob("*.log"):
            if f.exists() and f.stat().st_size > 100 * 1024 * 1024:
                try:
                    with open(f, "rb") as fh:
                        fh.seek(-10 * 1024 * 1024, 2)
                        tail = fh.read()
                    with open(f, "wb") as fh:
                        fh.write(tail)
                    logger.info(f"  ✂️  Truncated large log: {f.name}")
                except Exception as e:
                    logger.error(f"  ❌ Truncate failed: {f} — {e}")

    return freed


def clean_system_logs(dry_run: bool) -> int:
    """Vacuum systemd journal + hapus rotated syslog."""
    freed = 0
    logger.info("🔍 [5] Cleaning system logs (journalctl + syslog)...")

    # Estimasi ukuran journal sebelum vacuum
    journal_path = Path("/var/log/journal")
    if journal_path.exists():
        journal_size = sum(f.stat().st_size for f in journal_path.rglob("*") if f.is_file())
        freed += journal_size

    if not dry_run:
        try:
            subprocess.run(
                ["sudo", "journalctl", "--vacuum-size=200M"],
                capture_output=True, timeout=30
            )
            logger.info("     journalctl vacuumed to 200M")
        except Exception as e:
            logger.warning(f"     journalctl vacuum failed: {e}")

    # Rotated syslog / auth / kern
    for rotated_log in Path("/var/log").glob("*.log.*"):
        size = rotated_log.stat().st_size if rotated_log.is_file() else 0
        if not dry_run:
            try:
                rotated_log.unlink()
                logger.info(f"  🗑️  Removed: {rotated_log} ({human_size(size)})")
            except Exception:
                pass
        freed += size

    for rotated_log in Path("/var/log").glob("syslog.*"):
        size = rotated_log.stat().st_size if rotated_log.is_file() else 0
        if not dry_run:
            try:
                rotated_log.unlink()
                logger.info(f"  🗑️  Removed: {rotated_log} ({human_size(size)})")
            except Exception:
                pass
        freed += size

    return freed


def clean_pip_cache(dry_run: bool) -> int:
    """Hapus pip cache."""
    freed = 0
    logger.info("🔍 [6] Cleaning pip cache...")

    pip_cache = HOME_DIR / ".cache" / "pip"
    if pip_cache.exists():
        freed += safe_remove(pip_cache, dry_run)

    return freed


def clean_tmp_files(dry_run: bool) -> int:
    """Hapus file .tmp yang ditinggal proses."""
    freed = 0
    logger.info("🔍 [7] Cleaning orphaned .tmp files...")

    for tmp_file in KIBOT_ROOT.rglob("*.tmp.*"):
        freed += safe_remove(tmp_file, dry_run)

    for tmp_file in KIBOT_ROOT.rglob("*.tmp"):
        freed += safe_remove(tmp_file, dry_run)

    # State cache bisa diregen
    stale_caches = [
        STATE_DIR / "ai_coordinator_cache.json",
        STATE_DIR / "ai_search_cache.json",
        STATE_DIR / "brain_indodax_pairs.json",
    ]
    for cache in stale_caches:
        if cache.exists():
            age = time.time() - cache.stat().st_mtime
            if age > 86400:  # > 1 hari
                freed += safe_remove(cache, dry_run)

    return freed


def clean_ollama_unused_blobs(dry_run: bool) -> int:
    """
    Hapus model Ollama yang tidak terdaftar di manifest.
    Aman: hanya hapus blob orphan, bukan model aktif.
    """
    freed = 0
    ollama_blobs  = Path("/usr/share/ollama/.ollama/models/blobs")
    ollama_manifests = Path("/usr/share/ollama/.ollama/models/manifests")

    if not ollama_blobs.exists():
        return 0

    logger.info("🔍 [8] Scanning Ollama orphan blobs...")

    # Kumpulkan semua digest yang dirujuk manifest
    referenced_digests = set()
    if ollama_manifests.exists():
        for manifest_file in ollama_manifests.rglob("*"):
            if manifest_file.is_file():
                try:
                    data = json.loads(manifest_file.read_text())
                    for layer in data.get("layers", []):
                        digest = layer.get("digest", "").replace(":", "-")
                        referenced_digests.add(digest)
                    cfg = data.get("config", {}).get("digest", "")
                    if cfg:
                        referenced_digests.add(cfg.replace(":", "-"))
                except Exception:
                    pass

    if not referenced_digests:
        logger.info("     No manifests found — skipping Ollama cleanup for safety.")
        return 0

    for blob in ollama_blobs.iterdir():
        if blob.is_file() and blob.name not in referenced_digests:
            freed += safe_remove(blob, dry_run)

    return freed


def clean_npm_cache(dry_run: bool) -> int:
    freed = 0
    logger.info("🔍 [9] Cleaning npm/node cache...")

    npm_cache = HOME_DIR / ".npm"
    if npm_cache.exists():
        cache_size = sum(f.stat().st_size for f in npm_cache.rglob("*") if f.is_file())
        if cache_size > 100 * 1024 * 1024:  # > 100MB
            freed += safe_remove(npm_cache, dry_run)

    # node_modules di KiBot (kalau ada)
    for nm in KIBOT_ROOT.rglob("node_modules"):
        freed += safe_remove(nm, dry_run)

    return freed


def clean_dot_cache(dry_run: bool) -> int:
    """Hapus .cache selain pip dan ms-playwright (sudah dihandle terpisah)."""
    freed = 0
    logger.info("🔍 [10] Cleaning .cache subdirs...")

    cache_root = HOME_DIR / ".cache"
    if not cache_root.exists():
        return 0

    # Hapus cache yang aman
    safe_cache_targets = [
        "huggingface",
        "torch",
        "triton",
        "matplotlib",
        "fontconfig",
        "chromium",
        "puppeteer",
    ]
    for name in safe_cache_targets:
        p = cache_root / name
        if p.exists():
            freed += safe_remove(p, dry_run)

    return freed


# ───────────────────────────────────────────────
#  REPORT
# ───────────────────────────────────────────────

def print_disk_report():
    """Cetak ringkasan disk usage sebelum dan sesudah."""
    used, free, pct = disk_usage_pct("/")

    status_emoji = "🟢" if pct < 70 else "🟡" if pct < 90 else "🔴"

    print("\n" + "═" * 55)
    print("  📊  SOVEREIGN DISK REPORT")
    print("═" * 55)
    print(f"  Path  : /")
    print(f"  Used  : {human_size(used)}")
    print(f"  Free  : {human_size(free)}")
    print(f"  Usage : {status_emoji} {pct}%")
    print("═" * 55)

    # Top 5 biggest paths
    print("\n  TOP USAGE DIRECTORIES:")
    try:
        result = subprocess.run(
            ["du", "-sh", "--max-depth=2", str(HOME_DIR)],
            capture_output=True, text=True, timeout=30
        )
        lines = []
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 2:
                lines.append((parts[0], parts[1]))
        lines.sort(key=lambda x: x[0], reverse=True)
        for size, path in lines[:8]:
            print(f"    {size:>8}  {path}")
    except Exception as e:
        print(f"    (du failed: {e})")

    print()

    if pct >= DISK_CRITICAL_PCT:
        print("  🚨 CRITICAL: Disk hampir penuh! Jalankan --execute sekarang.")
    elif pct >= DISK_WARNING_PCT:
        print("  ⚠️  WARNING: Disk mulai penuh. Pertimbangkan cleanup.")
    else:
        print("  ✅ Disk usage dalam batas aman.")
    print()


def save_report(total_freed: int, dry_run: bool):
    """Simpan laporan cleanup ke state."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp": datetime.now().isoformat(),
        "dry_run": dry_run,
        "freed_bytes": total_freed,
        "freed_human": human_size(total_freed),
        "disk_pct_after": disk_usage_pct("/")[2],
    }
    log_file = STATE_DIR / "disk_cleaner_history.json"
    history = []
    if log_file.exists():
        try:
            history = json.loads(log_file.read_text())
        except Exception:
            pass
    history.append(report)
    history = history[-30:]  # Simpan 30 run terakhir
    log_file.write_text(json.dumps(history, indent=2))


# ───────────────────────────────────────────────
#  INSTALL CRONJOB
# ───────────────────────────────────────────────

def install_cronjob():
    """Pasang cronjob untuk cleanup otomatis setiap hari jam 03:00 WIB."""
    script_path = Path(__file__).resolve()
    cron_line = f"0 3 * * * /usr/bin/python3 {script_path} --execute >> /home/ubuntu/KiBot/logs/disk_cleaner_cron.log 2>&1"

    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        existing = result.stdout if result.returncode == 0 else ""

        if str(script_path) in existing:
            print("✅ Cronjob already installed.")
            return

        new_crontab = existing.rstrip() + "\n" + cron_line + "\n"
        proc = subprocess.run(["crontab", "-"], input=new_crontab, text=True, capture_output=True)
        if proc.returncode == 0:
            print(f"✅ Cronjob installed: runs daily at 03:00 WIB")
            print(f"   Script: {script_path}")
        else:
            print(f"❌ Failed to install cronjob: {proc.stderr}")
    except Exception as e:
        print(f"❌ Cronjob install error: {e}")


# ───────────────────────────────────────────────
#  MAIN
# ───────────────────────────────────────────────

def run_cleanup(dry_run: bool = True) -> int:
    _, _, pct_before = disk_usage_pct("/")

    label = "DRY-RUN PREVIEW" if dry_run else "EXECUTING CLEANUP"
    print(f"\n{'═' * 55}")
    print(f"  🧹  SOVEREIGN DISK CLEANER — {label}")
    print(f"{'═' * 55}\n")

    total_freed = 0
    total_freed += find_recursive_repo_clones(dry_run)
    total_freed += clean_playwright_cache(dry_run)
    total_freed += clean_python_cache(dry_run)
    total_freed += clean_application_logs(dry_run)
    total_freed += clean_system_logs(dry_run)
    total_freed += clean_pip_cache(dry_run)
    total_freed += clean_tmp_files(dry_run)
    total_freed += clean_ollama_unused_blobs(dry_run)
    total_freed += clean_npm_cache(dry_run)
    total_freed += clean_dot_cache(dry_run)

    _, _, pct_after = disk_usage_pct("/")

    print(f"\n{'═' * 55}")
    if dry_run:
        print(f"  📋 DRY-RUN RESULT: Would free ~{human_size(total_freed)}")
        print(f"  ℹ️  Run with --execute to apply changes.")
    else:
        print(f"  ✅ CLEANUP DONE: Freed ~{human_size(total_freed)}")
        print(f"  📊 Disk: {pct_before}% → {pct_after}%")
        save_report(total_freed, dry_run)
    print(f"{'═' * 55}\n")

    return total_freed


def main():
    parser = argparse.ArgumentParser(
        description="KiBot Sovereign Disk Cleaner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--execute",  action="store_true", help="Jalankan cleanup beneran (default: dry-run)")
    parser.add_argument("--report",   action="store_true", help="Tampilkan laporan disk usage saja")
    parser.add_argument("--schedule", action="store_true", help="Install cronjob harian jam 03:00")
    args = parser.parse_args()

    if args.schedule:
        install_cronjob()
        return

    if args.report:
        print_disk_report()
        return

    print_disk_report()
    dry_run = not args.execute
    run_cleanup(dry_run=dry_run)

    if dry_run:
        print("💡 Tip: Jalankan dengan --execute untuk benar-benar membersihkan.\n")


if __name__ == "__main__":
    main()
