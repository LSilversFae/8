#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# Reuse utilities from character formatter to stay consistent
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
from scripts.format_characters import (
    clean_text,
    clean_list,
    save_json,
    load_synonyms,
    set_synonyms,
    canonicalize_with_synonyms,
)


def normalize_creature(name: str, raw: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    display = clean_text(name) or "Unknown"

    kind = clean_text(raw.get("type") or raw.get("kind") or raw.get("species"))
    if kind:
        kind = canonicalize_with_synonyms(kind, SYNONYMS.get("type", {}))

    location = clean_text(raw.get("location") or raw.get("habitat") or context.get("location"))
    if location:
        location = canonicalize_with_synonyms(location, SYNONYMS.get("location", {}), title_case=True)

    desc = clean_text(raw.get("description"))

    abilities_raw = raw.get("abilities") or raw.get("powers")
    abilities: List[str] = []
    if isinstance(abilities_raw, list):
        abilities = clean_list(abilities_raw) or []
    elif abilities_raw:
        abilities = [clean_text(abilities_raw)]  # type: ignore

    danger = clean_text(raw.get("danger_level") or raw.get("threat") or raw.get("danger"))

    # Collect other fields into attributes
    recognized = {"type", "kind", "species", "location", "habitat", "description", "abilities", "powers", "danger_level", "threat", "danger"}
    attributes: Dict[str, Any] = {}
    for k, v in raw.items():
        if k in recognized:
            continue
        if isinstance(v, (dict, list)):
            attributes[k] = v
        else:
            txt = clean_text(v)
            if txt:
                attributes[k] = txt

    entry = {
        "id": re.sub(r"[^a-z0-9_]+", "_", display.lower()),
        "name": display,
        "kind": kind,
        "location": location,
        "description": desc,
        "abilities": abilities,
        "danger_level": danger,
        "attributes": attributes or None,
        "source": {
            "file": context.get("file"),
            "category": context.get("category"),
            "group": context.get("group"),
        },
    }
    return entry


def normalize_file(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    result: List[Dict[str, Any]] = []

    # Expected shapes:
    # { "creatures": { GroupName: { CreatureName: {..}, ... }, ... } }
    # or list/dict variants.
    if isinstance(data, dict) and "creatures" in data and isinstance(data["creatures"], dict):
        for group, block in data["creatures"].items():
            if isinstance(block, dict):
                for cname, cbody in block.items():
                    if isinstance(cbody, dict):
                        ctx = {"file": str(path), "category": "creatures", "group": group}
                        result.append(normalize_creature(cname, cbody, ctx))
    elif isinstance(data, dict):
        # flat dict of name -> details
        for cname, cbody in data.items():
            if isinstance(cbody, dict):
                ctx = {"file": str(path), "category": "creatures", "group": None}
                result.append(normalize_creature(cname, cbody, ctx))
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                n = item.get("name") or "Creature"
                ctx = {"file": str(path), "category": "creatures", "group": None}
                result.append(normalize_creature(n, item, ctx))

    return result


def build_index(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "id": e.get("id"),
            "name": e.get("name"),
            "kind": e.get("kind"),
            "location": e.get("location"),
            "group": e.get("source", {}).get("group"),
        }
        for e in entries
    ]


# Synonyms
SYNONYMS: Dict[str, Dict[str, str]] = {
    "type": {
        "ethereal beings": "Ethereal",
        "undead warriors": "Undead",
        "serpentine creatures": "Drake",
        "predatory beasts": "Beast",
        "tree-like guardians": "Treant",
    },
    "location": {
        "northern courts": "Northern Courts",
        "wraithwood": "Wraithwood Forest",
        "the abyss": "Abyss",
        "abyss": "Abyss",
    },
}


def main():
    ap = argparse.ArgumentParser(description="Normalize creature JSON files.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", type=str)
    src.add_argument("--scan", type=str)

    ap.add_argument("--outdir", type=str)
    ap.add_argument("--output", type=str)
    ap.add_argument("--split", action="store_true")
    ap.add_argument("--index", action="store_true")
    ap.add_argument("--mappings", type=str)

    args = ap.parse_args()

    # Load synonyms
    synonyms = load_synonyms(Path(args.mappings)) if args.mappings else SYNONYMS
    set_synonyms(synonyms)

    inputs: List[Path] = []
    if args.input:
        inputs = [Path(args.input)]
    else:
        root = Path(args.scan)
        inputs = [p for p in root.glob("*.json")]

    all_entries: List[Dict[str, Any]] = []
    for p in inputs:
        try:
            all_entries.extend(normalize_file(p))
        except Exception as e:
            print(f"Failed to normalize {p}: {e}")

    if args.split:
        if not args.outdir:
            raise SystemExit("--outdir is required with --split")
        outdir = Path(args.outdir)
        for e in all_entries:
            name = e.get("name") or e.get("id") or "creature"
            safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", name)
            save_json(outdir / f"{safe}.json", e)
        if args.index:
            save_json(Path(args.outdir) / "_index.json", build_index(all_entries))

    if args.output:
        save_json(Path(args.output), {"creatures": all_entries})

    if not args.split and not args.output:
        print(json.dumps({"creatures": all_entries}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
