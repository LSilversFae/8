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


def extract_summary(block: Any) -> Optional[str]:
    if isinstance(block, dict):
        for k in ("summary", "description", "overview"):
            v = block.get(k)
            if isinstance(v, dict):
                # nested description
                if v.get("description"):
                    return clean(v.get("description"))
            elif isinstance(v, str):
                return clean(v)
    return None


def normalize_file(path: Path) -> List[Dict[str, Any]]:
    data = load(path)
    entries: List[Dict[str, Any]] = []

    if isinstance(data, dict) and "plots" in data and isinstance(data["plots"], dict):
        for name, body in data["plots"].items():
            nm = clean(body.get("plot_name") if isinstance(body, dict) else name) or clean(name)
            summary = extract_summary(body)
            entries.append({
                "id": re.sub(r"[^a-z0-9_]+", "_", (nm or "plot").lower()),
                "name": nm,
                "arc": None,
                "status": None,
                "summary": summary,
                "source": {"file": str(path), "category": "plots"},
            })
    return entries


__all__ = ["normalize_file", "save"]

