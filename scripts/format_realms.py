#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def normalize_realm(entry: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    name = clean_text(entry.get("name")) or "Unknown"
    canon_name = canonicalize_with_synonyms(name, SYNONYMS.get("name", {}), title_case=True)

    desc = clean_text(entry.get("description"))
    domains = clean_list(entry.get("domains")) or []
    ruler = clean_text(entry.get("ruler") or entry.get("sovereign") or entry.get("god_king"))
    capital = clean_text(entry.get("capital"))
    factions = clean_list(entry.get("factions") or entry.get("courts")) or []
    locations = clean_list(entry.get("notable_locations") or entry.get("landmarks")) or []

    recognized = {"name","description","domains","ruler","sovereign","god_king","capital","factions","courts","notable_locations","landmarks"}
    notes: List[str] = []
    extra: Dict[str, Any] = {}
    for k, v in entry.items():
        if k in recognized:
            continue
        if isinstance(v, (dict, list)):
            extra[k] = v
        else:
            t = clean_text(v)
            if t:
                notes.append(f"{k}: {t}")

    return {
        "id": re.sub(r"[^a-z0-9_]+", "_", canon_name.lower()),
        "name": canon_name,
        "description": desc,
        "domains": domains,
        "ruler": ruler,
        "capital": capital,
        "factions": factions or None,
        "notable_locations": locations or None,
        "notes": notes or None,
        "attributes": extra or None,
        "source": {
            "file": context.get("file"),
            "category": context.get("category"),
        },
    }


def normalize_file(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    result: List[Dict[str, Any]] = []

    if isinstance(data, dict):
        if "realms" in data and isinstance(data["realms"], list):
            for r in data["realms"]:
                if isinstance(r, dict):
                    ctx = {"file": str(path), "category": "realms"}
                    result.append(normalize_realm(r, ctx))
        elif "Realms" in data and isinstance(data["Realms"], list):
            for r in data["Realms"]:
                if isinstance(r, dict):
                    ctx = {"file": str(path), "category": "realms"}
                    result.append(normalize_realm(r, ctx))
        else:
            # Single realm object
            if data.get("name"):
                ctx = {"file": str(path), "category": "realms"}
                result.append(normalize_realm(data, ctx))
    elif isinstance(data, list):
        for r in data:
            if isinstance(r, dict):
                ctx = {"file": str(path), "category": "realms"}
                result.append(normalize_realm(r, ctx))

    return result


def build_index(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "id": e.get("id"),
            "name": e.get("name"),
            "domains": e.get("domains") or [],
            "ruler": e.get("ruler"),
            "capital": e.get("capital"),
        }
        for e in entries
    ]


SYNONYMS: Dict[str, Dict[str, str]] = {
    "name": {
        "elarion": "Elarion",
        "the abyss": "Abyss",
        "abyss": "Abyss",
        "ignisyr": "Ignisyr",
        "elysion": "Elysion",
    }
}


def main():
    ap = argparse.ArgumentParser(description="Normalize realm JSON files.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", type=str)
    src.add_argument("--scan", type=str)

    ap.add_argument("--outdir", type=str)
    ap.add_argument("--output", type=str)
    ap.add_argument("--split", action="store_true")
    ap.add_argument("--index", action="store_true")
    ap.add_argument("--mappings", type=str)

    args = ap.parse_args()

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
            name = e.get("name") or e.get("id") or "realm"
            safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", name)
            save_json(outdir / f"{safe}.json", e)
        if args.index:
            save_json(Path(args.outdir) / "_index.json", build_index(all_entries))

    if args.output:
        save_json(Path(args.output), {"realms": all_entries})

    if not args.split and not args.output:
        print(json.dumps({"realms": all_entries}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
