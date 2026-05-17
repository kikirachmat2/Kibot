#!/usr/bin/env python3
import os
import sys
from pathlib import Path

# Ensure project root is in the path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

def test_no_forbidden_cache_or_temp_files():
    forbidden_extensions = {".pyc", ".pyo", ".tmp", ".bak"}
    forbidden_folders = {"__pycache__", ".pytest_cache", ".aider.tags.cache"}
    
    # Audit repository root up to 3 levels deep for forbidden artifacts
    for root, dirs, files in os.walk(PROJECT_ROOT):
        # Skip top level virtual environments if they are named env, venv, .env, or .venv, or .pytest_cache
        if any(p in Path(root).parts for p in (".venv", "venv", "env", ".git", ".pytest_cache", ".gemini", ".aider.tags.cache", "__pycache__")):
            continue
            
        for d in dirs:
            if d in (".pytest_cache", "__pycache__", ".aider.tags.cache"):
                continue
            assert d not in forbidden_folders, f"Forbidden folder '{d}' found in {root}!"
            
        for f in files:
            file_path = Path(root) / f
            assert file_path.suffix not in forbidden_extensions, f"Forbidden extension file '{f}' found at {file_path}!"
            assert f != ".DS_Store", f".DS_Store file found at {file_path}!"

def test_gitignore_has_correct_rules():
    gitignore_path = PROJECT_ROOT / ".gitignore"
    assert gitignore_path.exists(), ".gitignore does not exist in the repository root!"
    
    content = gitignore_path.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines() if line.strip() and not line.strip().startswith("#")]
    
    expected_rules = {"state/", "Logs/", "backups/", "state", "Logs", "backups"}
    
    matched = False
    for line in lines:
        if any(rule in line for rule in expected_rules) or "state" in line or "Logs" in line:
            matched = True
            
    assert matched, ".gitignore is missing critical patterns for state/, Logs/, or backups/!"
