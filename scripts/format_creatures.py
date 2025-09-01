#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, DefaultDict
from collections import defaultdict

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

    # Derive a higher-level region from location or grouping if provided
    region: Optional[str] = None
    if location:
        loc_l = location.lower()
        for needle, value in (SYNONYMS.get("region", {}) or {}).items():
            try:
                if needle in loc_l:
                    region = value
                    break
            except Exception:
                continue
    if not region:
        grp = context.get("group")
        if isinstance(grp, str) and grp.strip():
            region = grp.strip()

    # Derive realm from explicit field, location, or region heuristics
    realm: Optional[str] = None
    realm_in = clean_text(raw.get("realm"))
    if realm_in:
        realm = canonicalize_with_synonyms(realm_in, SYNONYMS.get("realm", {}), title_case=True)
    if not realm and location:
        ll = location.lower()
        for k, v in (SYNONYMS.get("realm", {}) or {}).items():
            try:
                if k in ll:
                    realm = v
                    break
            except Exception:
                continue
    if not realm and region:
        rl = str(region).lower()
        for k, v in (SYNONYMS.get("realm", {}) or {}).items():
            if k in rl:
                realm = v
                break

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
        "region": region,
        "realm": realm,
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
            "region": e.get("region"),
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
    "region": {
        "northern": "Northern Region",
        "wraithwood": "Wraithwood",
        "abyss": "Abyss",
        "elarion": "Elarion",
    },
    "realm": {
        "elarion": "Elarion",
        "elysion": "Elysion",
        "nythralkar": "Nythralkar",
        "ignisyr": "Ignisyr",
        "dreaming realm": "Dreaming Realm",
        "abyss": "Abyss"
    },
}


# -------- Region bundles (per-region JSON grouped by danger) --------
def danger_bucket(text: Optional[str]) -> str:
    if not text:
        return "Unknown"
    t = str(text).lower()
    # coarse bucketing; adjust as needed
    if any(k in t for k in ("extreme", "mythic", "catastrophic")):
        return "Extreme"
    if any(k in t for k in ("very high", "extremely high", "deadly", "lethal", "high")):
        return "High"
    if any(k in t for k in ("moderate", "medium")):
        return "Moderate"
    if any(k in t for k in ("low", "minor")):
        return "Low"
    return "Unknown"


def build_region_bundles(entries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Aggregate creatures into per-region bundles categorized by danger level.

    Returns mapping: region -> { region, categories: { Danger: [entries...] } }
    """
    bundles: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        region = e.get("region") or "Uncategorized"
        bucket = danger_bucket(e.get("danger_level"))
        if region not in bundles:
            bundles[region] = {"region": region, "categories": defaultdict(list)}  # type: ignore
        bundles[region]["categories"][bucket].append(e)  # type: ignore

    # Convert inner defaultdicts to plain dicts
    for r, b in list(bundles.items()):
        cats = b.get("categories", {})
        if isinstance(cats, defaultdict):
            bundles[r]["categories"] = dict(cats)  # type: ignore
    return bundles


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
    ap.add_argument("--by-region", action="store_true", help="When splitting, nest files under region subfolders")
    ap.add_argument("--region-bundles", action="store_true", help="Also write per-region JSON grouped by danger level")

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
            subdir = outdir
            if args.by_region:
                reg = e.get("region") or "Uncategorized"
                reg_safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(reg))
                subdir = outdir / reg_safe
                subdir.mkdir(parents=True, exist_ok=True)
            save_json(subdir / f"{safe}.json", e)
        if args.index:
            save_json(Path(args.outdir) / "_index.json", build_index(all_entries))

        if args.region_bundles:
            bundles = build_region_bundles(all_entries)
            base = Path(args.outdir) / "regions"
            for region, data in bundles.items():
                rsafe = re.sub(r"[^a-zA-Z0-9._-]+", "_", region)
                save_json(base / f"{rsafe}.json", data)

    if args.output:
        save_json(Path(args.output), {"creatures": all_entries})

    if not args.split and not args.output:
        print(json.dumps({"creatures": all_entries}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
