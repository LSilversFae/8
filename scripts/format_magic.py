#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def clean(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = str(s)
    return re.sub(r"\s+", " ", s).strip()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def normalize_file(path: Path) -> List[Dict[str, Any]]:
    data = load(path)
    entries: List[Dict[str, Any]] = []

    # Very tolerant normalizer for magic_and_abilities.json
    # Strategy: ingest any ability-like items under abilities_list; use name; description if present.
    # Also scan for any simple dicts with 'name' and promote as entries.
    root = data.get("magic_Levels_of_mastery_and_abilities") if isinstance(data, dict) else None
    if isinstance(root, dict):
        lst = root.get("abilities_list")
        if isinstance(lst, list):
            for item in lst:
                name = clean(item.get("name") if isinstance(item, dict) else item)
                if not name:
                    continue
                ent: Dict[str, Any] = {
                    "id": re.sub(r"[^a-z0-9_]+", "_", name.lower()),
                    "name": name,
                    "type": None,
                    "school": None,
                    "description": clean(item.get("description")) if isinstance(item, dict) else None,
                    "domains": [],
                    "source": {"file": str(path), "category": "magic"},
                }
                entries.append(ent)

    # Fallback: scan for list/dict of simple entries
    if not entries:
        if isinstance(data, list):
            for x in data:
                if isinstance(x, dict) and x.get("name"):
                    name = clean(x.get("name"))
                    entries.append({
                        "id": re.sub(r"[^a-z0-9_]+", "_", name.lower()),
                        "name": name,
                        "type": clean(x.get("type")),
                        "school": clean(x.get("school")),
                        "description": clean(x.get("description")),
                        "domains": x.get("domains") or [],
                        "source": {"file": str(path), "category": "magic"},
                    })

    return entries


__all__ = ["normalize_file", "save"]

