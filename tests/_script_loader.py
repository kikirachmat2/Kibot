from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def load_script_module(relative_path: str, module_name: str) -> ModuleType:
    path = Path(relative_path)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {relative_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
