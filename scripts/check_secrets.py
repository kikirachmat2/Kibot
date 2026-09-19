#!/usr/bin/env python3
"""
Pre-commit hook to scan for leaked secrets and credentials:
- Telegram Bot Tokens: r'\\d{10}:[A-Za-z0-9_-]{35}'
- Hardcoded secrets: BOT_TOKEN=..., API_KEY=..., SECRET=... (with non-empty literals)
"""
import re
import subprocess
import sys

TELEGRAM_TOKEN_PATTERN = re.compile(r'\b\d{10}:[A-Za-z0-9_-]{35}\b')
SUSPICIOUS_KEY_PATTERN = re.compile(r'(?:BOT_TOKEN|API_KEY|SECRET)\s*=\s*["\'](?!\{)[^"\']{8,}["\']', re.IGNORECASE)

# Warning patterns
OCID_PATTERN = re.compile(r'ocid1\.(?:tenancy|user|compartment)\.oc1\..{20,}', re.IGNORECASE)
FINGERPRINT_PATTERN = re.compile(r'(?:[0-9a-f]{2}:){15}[0-9a-f]{2}', re.IGNORECASE)
CHAT_ID_ENV_PATTERN = re.compile(r'(?:CHAT_ID|TELEGRAM_CHAT_ID)\s*=\s*["\']?\b\d{9,10}\b["\']?', re.IGNORECASE)

def get_staged_files():
    cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return [f.strip() for f in res.stdout.splitlines() if f.strip()]

def scan_file(filepath):
    # Exclude security docs, secret check scripts, or test mocks
    if "SECURITY_INCIDENT" in filepath or "check_secrets" in filepath or "test_" in filepath or filepath.endswith(".md"):
        return [], []

    cmd = ["git", "show", f":{filepath}"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return [], []

    lines = res.stdout.splitlines()
    blocks = []
    warnings = []

    for idx, line in enumerate(lines, start=1):
        if TELEGRAM_TOKEN_PATTERN.search(line):
            blocks.append(f"{filepath}:{idx}: CRITICAL - Potential Telegram Bot Token detected")
        elif SUSPICIOUS_KEY_PATTERN.search(line):
            blocks.append(f"{filepath}:{idx}: CRITICAL - Potential hardcoded secret/API key detected")
        
        # Check warnings
        if OCID_PATTERN.search(line):
            warnings.append(f"{filepath}:{idx}: WARNING - Sensitive Oracle OCID detected (should be redacted/env var)")
        if FINGERPRINT_PATTERN.search(line):
            warnings.append(f"{filepath}:{idx}: WARNING - OCI API Key Fingerprint detected (should be redacted/env var)")
        if CHAT_ID_ENV_PATTERN.search(line) or ((".env" in filepath or "config" in filepath) and re.search(r'\b\d{9,10}\b', line)):
            warnings.append(f"{filepath}:{idx}: WARNING - Raw Chat ID detected in env/config context")

    return blocks, warnings

def main():
    staged = get_staged_files()
    all_blocks = []
    all_warnings = []
    for f in staged:
        blocks, warnings = scan_file(f)
        all_blocks.extend(blocks)
        all_warnings.extend(warnings)

    if all_warnings:
        print("⚠️  SECURITY WARNING: Potential sensitive metadata detected:")
        for w in all_warnings:
            print(f"  - {w}")
        print("Please ensure credentials and identifiers are redacted where appropriate.\n")

    if all_blocks:
        print("❌ PRE-COMMIT HOOK REJECTED: Critical secrets detected in staged changes:")
        for b in all_blocks:
            print(f"  - {b}")
        print("\nPlease remove hardcoded credentials and use environment variables instead.")
        sys.exit(1)
    
    sys.exit(0)

if __name__ == "__main__":
    main()

