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
# Matches hardcoded literals like API_KEY = "abc12345..." but ignores {vars} or os.getenv
SUSPICIOUS_KEY_PATTERN = re.compile(r'(?:BOT_TOKEN|API_KEY|SECRET)\s*=\s*["\'](?!\{)[^"\']{8,}["\']', re.IGNORECASE)

def get_staged_files():
    cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return [f.strip() for f in res.stdout.splitlines() if f.strip()]

def scan_file(filepath):
    # Exclude security docs, secret check scripts, or test mocks
    if "SECURITY_INCIDENT" in filepath or "check_secrets" in filepath or "test_" in filepath or filepath.endswith(".md"):
        return []

    cmd = ["git", "show", f":{filepath}"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return []

    lines = res.stdout.splitlines()
    violations = []
    for idx, line in enumerate(lines, start=1):
        if TELEGRAM_TOKEN_PATTERN.search(line):
            violations.append(f"{filepath}:{idx}: Potential Telegram Bot Token detected")
        elif SUSPICIOUS_KEY_PATTERN.search(line):
            violations.append(f"{filepath}:{idx}: Potential hardcoded secret/API key detected")
    return violations

def main():
    staged = get_staged_files()
    all_violations = []
    for f in staged:
        all_violations.extend(scan_file(f))

    if all_violations:
        print("❌ PRE-COMMIT HOOK REJECTED: Potential secrets detected in staged changes:")
        for v in all_violations:
            print(f"  - {v}")
        print("\nPlease remove hardcoded credentials and use environment variables instead.")
        sys.exit(1)
    
    sys.exit(0)

if __name__ == "__main__":
    main()
