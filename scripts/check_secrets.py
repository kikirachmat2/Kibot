#!/usr/bin/env python3
"""
KiBot V3 — Pre-commit Credential & Secret Scanner.
Scans modified and committed files to strictly prevent accidental credential leaks.
"""

import sys
import re
from pathlib import Path

PATTERNS = [
    (r"\b\d{10}:[A-Za-z0-9_-]{35}\b", "Telegram Bot Token"),
    (r"\b[A-F0-9]{8}-[A-Z0-9]{8}-[A-Z0-9]{8}-[A-Z0-9]{8}-[A-Z0-9]{8}\b", "Indodax API Key"),
    (r"\b[a-f0-9]{80,}\b", "Indodax API Secret"),
    (r"\b(SECRET|KEY|TOKEN|PASSWORD)\s*=\s*[A-Za-z0-9_-]{20,}\b", "Generic High-Entropy Secret"),
    (r"\bgh[po]_[A-Za-z0-9]{36}\b", "GitHub Personal Access Token"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS Access Key"),
]

def scan_file(file_path: Path) -> list:
    findings = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return findings

    for line_no, line in enumerate(content.splitlines(), start=1):
        for pattern, label in PATTERNS:
            if re.search(pattern, line):
                findings.append((line_no, label, line.strip()[:60]))
    return findings

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/check_secrets.py <file1> [file2 ...]")
        sys.exit(0)

    total_violations = 0
    for target in sys.argv[1:]:
        p = Path(target)
        if not p.exists() or p.is_dir():
            continue
        issues = scan_file(p)
        if issues:
            total_violations += len(issues)
            print(f"❌ [LEAK DETECTED] File: {target}")
            for line_no, label, snippet in issues:
                print(f"   Line {line_no}: Found {label} -> {snippet}...")

    if total_violations > 0:
        print(f"\n🚨 ABORT: {total_violations} credential leak(s) detected! Commit blocked.")
        sys.exit(1)
    else:
        print("✅ Clean: No credentials or secrets detected.")
        sys.exit(0)

if __name__ == "__main__":
    main()
