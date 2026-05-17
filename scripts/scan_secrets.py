import os
import re
import sys

exclude_dirs = {'.git', 'venv', '.venv', 'node_modules', 'Logs', 'logs'}
secret_regex = re.compile(
    r'(api[_-]?key|secret|private[_-]?key|seed|mnemonic|token|password|authorization|bearer)', 
    re.IGNORECASE
)

# Regex to find secrets with their values (e.g. key = "value")
value_regex = re.compile(
    r'([a-zA-Z0-9_-]*(?:api[_-]?key|secret|private[_-]?key|seed|mnemonic|token|password|auth)[a-zA-Z0-9_-]*\s*[:=]\s*)(["\']?[a-zA-Z0-9_\-\.\+\/]{8,150}["\']?)',
    re.IGNORECASE
)

target_dir = '/home/ubuntu/KiBot' if len(sys.argv) < 2 else sys.argv[1]

count = 0
for root, dirs, files in os.walk(target_dir):
    dirs[:] = [d for d in dirs if d not in exclude_dirs]
    for file in files:
        if file.endswith(('.bak', '.png', '.jpg', '.pyc', '.gitkeep', '.json')):
            continue
        path = os.path.join(root, file)
        try:
            with open(path, 'r', errors='ignore') as f:
                for line_num, line in enumerate(f, 1):
                    if secret_regex.search(line):
                        censored = line.strip()
                        censored = value_regex.sub(r'\1<REDACTED>', censored)
                        # Remove actual secrets if they slip past the regex
                        # If a line contains KIBOT_ or INDODAX_ keys, let's keep the key but hide the value
                        rel_path = os.path.relpath(path, target_dir)
                        print(f'{rel_path}:{line_num}: {censored}')
                        count += 1
                        if count >= 100:
                            break
        except Exception:
            pass
        if count >= 100:
            break
    if count >= 100:
        break
