#!/usr/bin/env python3
"""
Utilities to sync Character JSON files with a Notion database.

Relies on environment variables:
- NOTION_TOKEN: Notion integration token
- CHARACTER_DB_ID: Notion database ID for the Characters table

Mapping configuration:
- scripts/notion_mappings/characters.json defines how JSON fields map to Notion properties

This module provides functions to:
- push_characters_to_notion: create/update Notion pages from local JSON files
- pull_characters_from_notion: update/create local JSON from Notion pages
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from notion_client import Client
from dotenv import load_dotenv


load_dotenv()


LORE_ROOT = Path("lore")
CHAR_DIR = LORE_ROOT / "characters" / "formatted"
MAPPINGS_DIR = Path("scripts") / "notion_mappings"
CHAR_MAPPING_PATH = MAPPINGS_DIR / "characters.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_env_client() -> tuple[Client, str]:
    token = os.getenv("NOTION_TOKEN")
    if not token:
        raise ValueError("NOTION_TOKEN is not set")
    db_id = os.getenv("CHARACTER_DB_ID")
    if not db_id:
        raise ValueError("CHARACTER_DB_ID is not set")
    return Client(auth=token), db_id


def load_mapping(path: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    p = path or CHAR_MAPPING_PATH
    if not p.exists():
        raise FileNotFoundError(f"Mapping file not found: {p}")
    data = load_json(p)
    if not isinstance(data, dict):
        raise ValueError("Invalid mapping JSON format")
    # Normalize keys to strings
    return {str(k): {"json": str(v.get("json")), "type": str(v.get("type"))} for k, v in data.items()}


def get_by_path(obj: Dict[str, Any], path: str) -> Any:
    cur: Any = obj
    for part in path.split("."):
        if cur is None:
            return None
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def set_by_path(obj: Dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur: Dict[str, Any] = obj
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]  # type: ignore
    cur[parts[-1]] = value


def to_notion_prop(prop_type: str, value: Any):
    if value is None:
        # Notion requires empty object of the correct type to clear; leave unset to avoid overwriting
        return None
    if prop_type == "title":
        return {"title": [{"text": {"content": str(value)}}]}
    if prop_type == "rich_text":
        return {"rich_text": [{"text": {"content": str(value)}}]}
    if prop_type == "select":
        return {"select": {"name": str(value)}}
    if prop_type == "multi_select":
        if isinstance(value, list):
            return {"multi_select": [{"name": str(v)} for v in value if v is not None]}
        # single value fallback
        return {"multi_select": [{"name": str(value)}]}
    if prop_type == "number":
        try:
            return {"number": float(value)}
        except Exception:
            return {"number": None}
    if prop_type == "checkbox":
        return {"checkbox": bool(value)}
    # default to rich_text
    return {"rich_text": [{"text": {"content": str(value)}}]}


def from_notion_prop(prop_type: str, prop_obj: Dict[str, Any]):
    if prop_obj is None:
        return None
    try:
        if prop_type == "title":
            arr = prop_obj.get("title", [])
            return "".join([x.get("plain_text", "") for x in arr]) if arr else None
        if prop_type == "rich_text":
            arr = prop_obj.get("rich_text", [])
            return "".join([x.get("plain_text", "") for x in arr]) if arr else None
        if prop_type == "select":
            sel = prop_obj.get("select")
            return sel.get("name") if sel else None
        if prop_type == "multi_select":
            ms = prop_obj.get("multi_select", [])
            return [x.get("name") for x in ms] if ms else []
        if prop_type == "number":
            return prop_obj.get("number")
        if prop_type == "checkbox":
            return prop_obj.get("checkbox")
    except Exception:
        return None
    # default
    arr = prop_obj.get("rich_text", [])
    return "".join([x.get("plain_text", "") for x in arr]) if arr else None


def build_properties_from_json(entry: Dict[str, Any], mapping: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    props: Dict[str, Any] = {}
    for notion_prop, spec in mapping.items():
        path = spec.get("json")
        typ = spec.get("type")
        val = get_by_path(entry, path)
        payload = to_notion_prop(typ, val)
        if payload is not None:
            props[notion_prop] = payload
    return props


def build_json_from_page(page: Dict[str, Any], mapping: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    props = page.get("properties", {})
    out: Dict[str, Any] = {}
    for notion_prop, spec in mapping.items():
        typ = spec.get("type")
        json_path = spec.get("json")
        po = props.get(notion_prop)
        if po is None:
            continue
        value = from_notion_prop(typ, po)
        set_by_path(out, json_path, value)
    return out


def list_character_files() -> List[Path]:
    if not CHAR_DIR.exists():
        return []
    return sorted([p for p in CHAR_DIR.glob("*.json")])


def find_file_by_name_or_source(name: str) -> Optional[Path]:
    # Try to find a file where JSON name == given name
    for p in list_character_files():
        try:
            data = load_json(p)
            if isinstance(data, dict) and data.get("name") == name:
                return p
        except Exception:
            continue
    return None


def safe_filename(name: str) -> str:
    keep = []
    for c in name:
        if c.isalnum() or c in (" ", "-", "_", "."):
            keep.append(c)
        else:
            keep.append("_")
    base = "".join(keep).strip().replace(" ", "_")
    return base or "character"


def push_characters_to_notion(mapping_path: Optional[Path] = None) -> Dict[str, Any]:
    notion, db_id = get_env_client()
    mapping = load_mapping(mapping_path)
    files = list_character_files()

    created = 0
    updated = 0
    for p in files:
        try:
            entry = load_json(p)
            if not isinstance(entry, dict):
                continue
            name = entry.get("name") or p.stem
            # Ensure source.file is set for round-trip
            entry.setdefault("source", {})
            if not entry["source"].get("file"):
                entry["source"]["file"] = str(p)

            props = build_properties_from_json(entry, mapping)

            # Find existing page by Name
            res = notion.databases.query(
                database_id=db_id,
                filter={"property": "Name", "title": {"equals": name}},
            )
            if res.get("results"):
                page_id = res["results"][0]["id"]
                notion.pages.update(page_id=page_id, properties=props)
                updated += 1
            else:
                notion.pages.create(parent={"database_id": db_id}, properties=props)
                created += 1
        except Exception as e:
            # Best-effort logging; continue
            print(f"Failed to sync '{p.name}': {e}")
            continue

    return {"created": created, "updated": updated, "total": created + updated}


def pull_characters_from_notion(mapping_path: Optional[Path] = None) -> Dict[str, Any]:
    notion, db_id = get_env_client()
    mapping = load_mapping(mapping_path)

    # Paginate through DB
    results: List[Dict[str, Any]] = []
    start_cursor: Optional[str] = None
    while True:
        page = notion.databases.query(database_id=db_id, start_cursor=start_cursor)  # type: ignore
        results.extend(page.get("results", []))
        if not page.get("has_more"):
            break
        start_cursor = page.get("next_cursor")

    written = 0
    for pg in results:
        try:
            data = build_json_from_page(pg, mapping)
            name = data.get("name") or "Unnamed"
            # Determine destination file
            file_path = get_by_path(data, "source.file")
            dest: Optional[Path] = None
            if file_path:
                fp = Path(file_path)
                dest = fp if fp.is_absolute() else Path(str(fp))
            if not dest or not dest.exists():
                # Try find by name
                dest = find_file_by_name_or_source(name) or (CHAR_DIR / f"{safe_filename(name)}.json")

            # If file exists, merge mapped fields into it; else create new skeleton
            if dest.exists():
                try:
                    current = load_json(dest)
                except Exception:
                    current = {}
                if not isinstance(current, dict):
                    current = {}
            else:
                current = {
                    "id": safe_filename(str(name)).lower(),
                    "name": name,
                    "titles": [],
                    "species": None,
                    "gender": None,
                    "age": None,
                    "realm": None,
                    "court": None,
                    "affiliations": None,
                    "domains": [],
                    "role": None,
                    "appearance": {},
                    "personality": {},
                    "lineage": {},
                    "prophecy": {},
                    "abilities": [],
                    "relationships": {},
                    "notes": None,
                    "source": {"file": str(dest), "category": "characters"},
                }

            # Merge mapped fields from Notion
            for notion_prop, spec in mapping.items():
                jpath = spec.get("json")
                val = get_by_path(data, jpath)
                if val is not None:
                    set_by_path(current, jpath, val)

            save_json(dest, current)
            written += 1
        except Exception as e:
            print(f"Failed to pull page: {e}")
            continue

    return {"written": written, "pages": len(results)}


__all__ = [
    "push_characters_to_notion",
    "pull_characters_from_notion",
    "CHAR_MAPPING_PATH",
]

