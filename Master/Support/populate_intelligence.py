#!/usr/bin/env python3
import json
import os
from pathlib import Path

def aggregate_knowledge():
    root = Path(".")
    batam = root / "SERVER_BATAM"
    state = batam / "state"
    
    knowledge = {
        "rules": {},
        "system_map": "",
        "learning_experience": {},
        "world_context": {}
    }
    
    # Load Rules
    if (root / "KIBOT_RULES.md").exists():
        knowledge["rules"]["core"] = (root / "KIBOT_RULES.md").read_text()
    
    # Load Map
    if (root / "TRINITY_SOVEREIGN_MAP.md").exists():
        knowledge["system_map"] = (root / "TRINITY_SOVEREIGN_MAP.md").read_text()
    
    # Load Learning State (without signature)
    if (state / "learning_state.json").exists():
        content = (state / "learning_state.json").read_text()
        if "|" in content:
            payload, _ = content.rsplit("|", 1)
            knowledge["learning_experience"] = json.loads(payload)
    
    # Load World Model
    if (state / "world_model.json").exists():
        knowledge["world_context"] = json.loads((state / "world_model.json").read_text())
        
    output_path = batam / "data" / "intelligence_bundle.json"
    with open(output_path, "w") as f:
        json.dump(knowledge, f, indent=2)
    
    print(f"✅ Knowledge Bundle created at {output_path}")
    print(f"📊 Total Rules: {len(knowledge['rules'])}")
    print(f"🧠 Pairs Learned: {len(knowledge['learning_experience'])}")

if __name__ == "__main__":
    aggregate_knowledge()
