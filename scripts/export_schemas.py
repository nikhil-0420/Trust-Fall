#!/usr/bin/env python3
"""
Export Pydantic models to JSON Schema files in contracts/schemas/.
"""
import json
import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from contracts.models import Attack, Event, Patch, Results

def export():
    schemas_dir = repo_root / "contracts" / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)

    models = {
        "event.schema.json": Event,
        "results.schema.json": Results,
        "patch.schema.json": Patch,
        "attack.schema.json": Attack,
    }

    for filename, model_cls in models.items():
        schema_path = schemas_dir / filename
        schema = model_cls.model_json_schema()
        with open(schema_path, "w", encoding="utf-8") as f:
            json.dump(schema, f, indent=2)
        print(f"[*] Exported {schema_path}")

if __name__ == "__main__":
    export()
