import json
import os
import shutil

def atomic_save(data, filepath):
    """Menulis data ke JSON secara aman (Atomic)."""
    temp_file = filepath + ".tmp"
    try:
        with open(temp_file, "w") as f:
            json.dump(data, f, indent=4)
        os.replace(temp_file, filepath)
        return True
    except Exception as e:
        if os.path.exists(temp_file):
            os.remove(temp_file)
        return False

def atomic_load(filepath):
    """Membaca data secara aman."""
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except:
        return {}
