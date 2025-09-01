#!/usr/bin/env python3
"""
Character JSON normalizer for worldbuilding lore.

Usage examples:
  - Normalize a single file and split into per-character files:
      python scripts/format_characters.py --input lore/characters/characters.json --outdir lore/characters/formatted --split

  - Scan a folder for *.json and normalize all:
      python scripts/format_characters.py --scan lore/characters --outdir lore/characters/formatted --split

  - Write a single combined normalized JSON instead of split files:
      python scripts/format_characters.py --input lore/characters/characters.json --output lore/characters/characters.normalized.json

This script also cleans up common encoding artifacts and unifies key names.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------- Text cleanup utilities ----------------
RE_WS = re.compile(r"\s+")


def clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)

    # Replace common mojibake/garbled sequences observed in the source files
    replacements = {
        "\uFFFD": "",  # � replacement char
        "\uFFFD?": "",  # sequences like �?
        "\uFFFD\"": "\"",  # �"
        "\uFFFD'": "'",  # �'
        "\u2014": "—",  # ensure em dash normalized
        "\u2013": "–",  # en dash
        "\u2019": "'",  # curly apostrophe → straight
        "\u2018": "'",
        "\u201C": '"',
        "\u201D": '"',
        "\u00A0": " ",  # nbsp
        "": "",     # stray ESC
        # Visible patterns from sample like "�?\"" likely came from broken encodings; strip residual
        "�?\"": "\"",
        "�?" : "",
        "�\"": '"',
        "�'": "'",
        "\r\n": "\n",
    }
    for k, v in replacements.items():
        value = value.replace(k, v)

    # Collapse whitespace
    value = RE_WS.sub(" ", value).strip()
    return value


def clean_list(values: Optional[List[Any]]) -> Optional[List[Any]]:
    if values is None:
        return None
    result: List[str] = []
    for v in values:
        t = clean_text(v)
        if t:
            result.append(t)
    return result or None


# ---------------- Schema + normalization ----------------
def canonicalize_key(k: str) -> str:
    # Lower, replace spaces and special chars with underscores
    k2 = re.sub(r"[^a-z0-9]+", "_", k.lower()).strip("_")
    return k2


def as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def normalize_abilities(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    abilities: List[Dict[str, Any]] = []
    # Abilities could be a dict mapping name -> {description, application}
    if isinstance(raw, dict):
        for name, body in raw.items():
            if isinstance(body, dict):
                abilities.append(
                    {
                        "name": clean_text(name),
                        "description": clean_text(body.get("description")),
                        "application": clean_text(body.get("application")),
                    }
                )
            else:
                abilities.append(
                    {
                        "name": clean_text(name),
                        "description": clean_text(body),
                    }
                )
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and "name" in item:
                abilities.append(
                    {
                        "name": clean_text(item.get("name")),
                        "description": clean_text(item.get("description")),
                        "application": clean_text(item.get("application")),
                    }
                )
            else:
                abilities.append({"name": clean_text(str(item))})
    return abilities


def normalize_personality(raw: Dict[str, Any]) -> Dict[str, Any]:
    if raw is None:
        return {}
    out: Dict[str, Any] = {}
    # Map flexible keys into traits/flaws/virtues/temperament/notes
    keymap = {
        "traits": "traits",
        "temperament": "temperament",
        "flaws": "flaws",
        "virtues": "virtues",
        "strengths": "virtues",
        "weaknesses": "flaws",
    }
    traits_extra: List[str] = []
    for k, v in raw.items():
        kcanon = canonicalize_key(k)
        if kcanon in ("traits", "flaws", "virtues"):
            out[kcanon] = clean_list(as_list(v))
        elif kcanon == "temperament":
            out["temperament"] = clean_text(v)
        elif kcanon in ("strengths", "weaknesses"):
            mapped = keymap.get(kcanon, kcanon)
            out[mapped] = (out.get(mapped) or []) + (clean_list(as_list(v)) or [])
        else:
            # Store other descriptive fields as extra traits
            cleaned = clean_text(v)
            if cleaned:
                label = clean_text(k).replace("_", " ")
                traits_extra.append(f"{label}: {cleaned}")
    if traits_extra:
        out["traits"] = (out.get("traits") or []) + traits_extra
    return out


def normalize_lineage(raw: Dict[str, Any]) -> Dict[str, Any]:
    if raw is None:
        return {}
    fields = {"father", "mother", "siblings", "consorts", "essence", "type", "origin", "status", "role"}
    out: Dict[str, Any] = {}
    for k, v in raw.items():
        kcanon = canonicalize_key(k)
        if kcanon in fields:
            if isinstance(v, list):
                out[kcanon] = clean_list(v)
            else:
                out[kcanon] = clean_text(v)
        elif kcanon == "primordial" and isinstance(v, dict):
            out["primordial"] = {k2: clean_text(v2) for k2, v2 in v.items()}
        else:
            # keep other lineage info
            out.setdefault("notes", []).append(f"{clean_text(k)}: {clean_text(v)}")
    if "notes" in out:
        out["notes"] = clean_list(out["notes"])  # type: ignore
    return out


def normalize_prophecy(raw: Dict[str, Any]) -> Dict[str, Any]:
    if raw is None:
        return {}
    out: Dict[str, Any] = {}
    for k in ("name", "description", "lore_fragment"):
        if k in raw:
            out[k] = clean_text(raw.get(k))
    if "powers_foretold" in raw:
        out["powers_foretold"] = clean_list(as_list(raw.get("powers_foretold")))
    return out


def normalize_appearance(raw: Dict[str, Any]) -> Dict[str, Any]:
    if raw is None:
        return {}
    keys = [
        "height",
        "build",
        "skin",
        "hair",
        "eyes",
        "wings",
        "attire",
        "distinctive_features",
        "marks",
    ]
    out: Dict[str, Any] = {}
    for k, v in raw.items():
        kcanon = canonicalize_key(k)
        if kcanon in [canonicalize_key(x) for x in keys]:
            out[kcanon] = clean_text(v)
        else:
            out.setdefault("notes", []).append(f"{clean_text(k)}: {clean_text(v)}")
    if "notes" in out:
        out["notes"] = clean_list(out["notes"])  # type: ignore
    return out


def normalize_character(entry: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    name = clean_text(entry.get("name")) or "Unknown"
    titles = []
    title_val = entry.get("title") or entry.get("titles")
    if isinstance(title_val, list):
        titles = clean_list(title_val) or []
    elif title_val:
        titles = [clean_text(title_val)]  # type: ignore

    domains = clean_list(entry.get("domain") or entry.get("domains")) or []
    role = clean_text(entry.get("role_in_cosmic_order") or entry.get("role"))

    # Canonicalize species/realm/court with synonyms if available
    species = clean_text(entry.get("species"))
    if species:
        species = canonicalize_with_synonyms(species, SYNONYMS.get("species", {}))

    realm = clean_text(entry.get("realm") or context.get("realm"))
    if realm:
        realm = canonicalize_with_synonyms(realm, SYNONYMS.get("realm", {}), title_case=True)

    court = clean_text(entry.get("court") or context.get("court"))
    if court:
        court = canonicalize_with_synonyms(court, SYNONYMS.get("court", {}), title_case=True)

    out: Dict[str, Any] = {
        "id": re.sub(r"[^a-z0-9_]+", "_", name.lower()),
        "name": name,
        "titles": titles,
        "species": species,
        "gender": clean_text(entry.get("gender")),
        "age": clean_text(entry.get("age")),
        "realm": realm,
        "court": court,
        "affiliations": clean_list(entry.get("affiliations")),
        "domains": domains,
        "role": role,
        "appearance": normalize_appearance(entry.get("appearance")),
        "personality": normalize_personality(entry.get("personality")),
        "lineage": normalize_lineage(entry.get("lineage")),
        "prophecy": normalize_prophecy(entry.get("prophecy")),
        "abilities": normalize_abilities(entry.get("abilities") or {}),
        "relationships": {},
        "notes": None,
        "source": {
            "file": context.get("file"),
            "category": context.get("category"),
            "group": context.get("group"),
        },
    }

    # Relationships: collapse any relationship_* keys into a map
    rels: Dict[str, str] = {}
    relationships = entry.get("relationships") or {}
    if isinstance(relationships, dict):
        for k, v in relationships.items():
            rels[clean_text(k)] = clean_text(v)  # type: ignore

    # Also scan top-level keys starting with relationship_
    for k, v in entry.items():
        if str(k).lower().startswith("relationship_"):
            rels[clean_text(k[12:]).replace("_", " ")] = clean_text(v)  # type: ignore

    if rels:
        out["relationships"] = rels

    # Notes: collect unrecognized top-level fields
    recognized = {
        "name","title","titles","species","gender","age","realm","court","affiliations",
        "domain","domains","role_in_cosmic_order","role","appearance","personality","lineage",
        "prophecy","abilities","relationships",
    }
    notes: List[str] = []
    for k, v in entry.items():
        if k not in recognized:
            cleaned = clean_text(v) if not isinstance(v, (dict, list)) else None
            if cleaned:
                notes.append(f"{k}: {cleaned}")
    out["notes"] = clean_list(notes)

    return out


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def normalize_file(path: Path) -> List[Dict[str, Any]]:
    data = load_json(path)
    normalized: List[Dict[str, Any]] = []

    if isinstance(data, dict) and "characters" in data:
        characters_block = data["characters"]
        # characters can be dict of groups -> list
        if isinstance(characters_block, dict):
            for group, items in characters_block.items():
                if not isinstance(items, list):
                    continue
                for entry in items:
                    if not isinstance(entry, dict):
                        continue
                    ctx = {
                        "file": str(path),
                        "category": "characters",
                        "group": group,
                    }
                    normalized.append(normalize_character(entry, ctx))
        elif isinstance(characters_block, list):
            for entry in characters_block:
                if not isinstance(entry, dict):
                    continue
                ctx = {"file": str(path), "category": "characters", "group": None}
                normalized.append(normalize_character(entry, ctx))
    elif isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict):
                ctx = {"file": str(path), "category": "characters", "group": None}
                normalized.append(normalize_character(entry, ctx))
    elif isinstance(data, dict) and data.get("name"):
        ctx = {"file": str(path), "category": "characters", "group": None}
        normalized.append(normalize_character(data, ctx))

    return normalized


def build_index(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "id": e.get("id"),
            "name": e.get("name"),
            "titles": e.get("titles") or [],
            "realm": e.get("realm"),
            "court": e.get("court"),
            "domains": e.get("domains") or [],
        }
        for e in entries
    ]


# ---------------- Synonyms support ----------------
# Module-level synonyms dictionary used by normalization.
SYNONYMS: Dict[str, Dict[str, str]] = {
    # Defaults; can be overridden or extended via load_synonyms()/set_synonyms()
    "species": {
        "high fae": "Fae",
        "fae": "Fae",
        "faerie": "Fae",
        "dryads": "Dryad",
        "dryad": "Dryad",
        "dragon": "Dragon",
        "dragons": "Dragon",
        "dragonkin": "Dragon",
        "human": "Human",
        "mortal": "Human",
        "mortals": "Human",
    },
    "realm": {
        "elarion": "Elarion",
        "the abyss": "Abyss",
        "abyss": "Abyss",
        "dreaming realm": "Dreaming Realm",
        "dreamweave": "Dreaming Realm",
        "dream": "Dreaming Realm",
    },
    "court": {
        "northern fae courts": "Northern Court",
        "northern court": "Northern Court",
        "southern court": "Southern Court",
        "shadow court": "Shadow Court",
    },
}


def canonicalize_with_synonyms(value: str, mapping: Dict[str, str], title_case: bool = False) -> str:
    key = value.strip().lower()
    if key in mapping:
        return mapping[key]
    # Fallback: title-case or return cleaned
    return value.title() if title_case else value


def load_synonyms(path: Optional[Path]) -> Dict[str, Dict[str, str]]:
    """Load synonyms JSON and merge into defaults. Returns merged mapping."""
    merged = {k: dict(v) for k, v in SYNONYMS.items()}
    if not path:
        return merged
    if not path.exists():
        return merged
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for section, m in data.items():
            if not isinstance(m, dict):
                continue
            sect = section.lower()
            merged.setdefault(sect, {})
            # normalize keys to lowercase for matching
            merged[sect].update({str(k).lower(): str(v) for k, v in m.items()})
    except Exception:
        pass
    return merged


def set_synonyms(synonyms: Dict[str, Dict[str, str]]) -> None:
    """Replace module-level synonyms mapping."""
    global SYNONYMS
    SYNONYMS = synonyms


def main():
    ap = argparse.ArgumentParser(description="Normalize character JSON files.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", type=str, help="Path to a JSON file to normalize")
    src.add_argument("--scan", type=str, help="Folder to scan for *.json files")

    ap.add_argument("--outdir", type=str, help="Output directory for split files")
    ap.add_argument("--output", type=str, help="Path to write combined normalized JSON")
    ap.add_argument("--split", action="store_true", help="Write one JSON per character into --outdir")
    ap.add_argument("--index", action="store_true", help="Also write a compact index JSON next to outputs")
    ap.add_argument("--mappings", type=str, help="Optional path to synonyms mapping JSON")

    args = ap.parse_args()

    inputs: List[Path] = []
    if args.input:
        inputs = [Path(args.input)]
    else:
        root = Path(args.scan)
        inputs = [p for p in root.glob("*.json")]

    # Load synonyms if provided
    synonyms = load_synonyms(Path(args.mappings)) if args.mappings else SYNONYMS
    set_synonyms(synonyms)

    all_entries: List[Dict[str, Any]] = []
    for p in inputs:
        try:
            all_entries.extend(normalize_file(p))
        except Exception as e:
            print(f"Failed to normalize {p}: {e}")

    if args.split:
        if not args.outdir:
            raise SystemExit("--outdir is required when using --split")
        outdir = Path(args.outdir)
        for e in all_entries:
            name = e.get("name") or e.get("id") or "character"
            safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", name)
            save_json(outdir / f"{safe}.json", e)
        if args.index:
            save_json(Path(args.outdir) / "_index.json", build_index(all_entries))

    if args.output:
        save_json(Path(args.output), {"characters": all_entries})

    if not args.split and not args.output:
        # default to printing to stdout
        print(json.dumps({"characters": all_entries}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
