import os
from pathlib import Path

def audit_population():
    root_dir = Path("/Users/kiki/Documents/Web Develop/KiBot/SERVER_BATAM")
    expected_dirs = [
        "AI_Orchestration", "Communication", "Core_Logic", 
        "Indicators_Math", "Infrastructure", "Intelligence", 
        "Security", "Support", "data", "state", "scratch"
    ]
    
    print("=== PHASE 1: DIRECTORY POPULATION AUDIT ===")
    
    all_present = True
    for d in expected_dirs:
        dir_path = root_dir / d
        if dir_path.exists() and dir_path.is_dir():
            num_files = sum(1 for _ in dir_path.rglob('*') if _.is_file())
            print(f"[OK] {d} - Found {num_files} files.")
            if num_files == 0 and d not in ["scratch"]:
                print(f"  -> WARNING: {d} is empty!")
                all_present = False
        else:
            print(f"[MISSING] {d}")
            all_present = False
            
    if all_present:
        print("\n=> Result: ALL CORE DIRECTORIES POPULATED.")
    else:
        print("\n=> Result: MISSING OR EMPTY DIRECTORIES DETECTED.")

if __name__ == "__main__":
    audit_population()
