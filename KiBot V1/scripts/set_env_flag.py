#!/usr/bin/env python3
import sys
from pathlib import Path

def set_env_flag(name: str, value: str):
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        env_path.write_text(f"{name}={value}\n")
        print(f"Created .env and set {name}={value}")
        return

    content = env_path.read_text()
    lines = content.splitlines()
    found = False
    
    for i, line in enumerate(lines):
        striped = line.strip()
        # Match standard VAR_NAME=value or commented out #VAR_NAME=value or empty VAR_NAME=
        if striped.startswith(f"{name}=") or striped.startswith(f"#{name}=") or striped == name or striped == f"#{name}":
            lines[i] = f"{name}={value}"
            found = True
            break
            
    if not found:
        lines.append(f"{name}={value}")
        
    env_path.write_text("\n".join(lines) + "\n")
    print(f"Set {name}={value} in .env")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 set_env_flag.py <VAR_NAME> <VALUE>")
        sys.exit(1)
    set_env_flag(sys.argv[1], sys.argv[2])
