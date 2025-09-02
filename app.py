from flask import Flask, jsonify, request, send_from_directory
import os
import json
from pathlib import Path
from notion_client import Client
from dotenv import load_dotenv
from difflib import get_close_matches
from typing import List
import threading
import time

# Load environment variables
load_dotenv()

# --- Notion API setup ---
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
notion = None
if NOTION_TOKEN:
    try:
        notion = Client(auth=NOTION_TOKEN)
    except Exception as e:
        print(f"Warning: Failed to initialize Notion client: {e}")
else:
    print("Warning: NOTION_TOKEN not set; Notion sync routes will be disabled.")

NOTION_DATABASES = {
    "characters": os.getenv("CHARACTER_DB_ID"),
    "plots": os.getenv("PLOTS_DB_ID"),
    "magic": os.getenv("MAGIC_DB_ID"),
    "creatures": os.getenv("CREATURES_DB_ID"),
    "realms": os.getenv("REALMS_DB_ID"),
}

# Sanity check (warn instead of crash for optional DBs)
for category, db_id in NOTION_DATABASES.items():
    if not db_id:
        print(f"âš ï¸ Warning: No DB ID set for {category}. Sync for this category will be skipped.")

# --- Flask setup ---
app = Flask(__name__)

# Paths
LORE_ROOT = Path("lore")
INDEX_DIR = LORE_ROOT / "indexes"
CATEGORIES = ["characters", "creatures", "magic", "plots", "realms"]

# Import normalizer utilities (for normalization routes)
try:
    from scripts.format_characters import (
        normalize_file as normalize_character_file,
        save_json as save_json_util,
        build_index as build_character_index,
        set_synonyms as set_character_synonyms,
        load_synonyms as load_character_synonyms,
    )
except Exception as e:
    print(f"Warning: character normalizer not available: {e}")
    normalize_character_file = None

try:
    from scripts.format_creatures import (
        normalize_file as normalize_creatures_file,
        build_index as build_creatures_index,
        load_synonyms as load_creatures_synonyms,
        set_synonyms as set_creatures_synonyms,
        build_region_bundles as build_creatures_region_bundles,
    )
except Exception as e:
    print(f"Warning: creatures normalizer not available: {e}")
    normalize_creatures_file = None

try:
    from scripts.format_realms import (
        normalize_file as normalize_realms_file,
        build_index as build_realms_index,
        load_synonyms as load_realms_synonyms,
        set_synonyms as set_realms_synonyms,
    )
except Exception as e:
    print(f"Warning: realms normalizer not available: {e}")
    normalize_realms_file = None

# Magic normalizer (optional)
try:
    from scripts.format_magic import (
        normalize_file as normalize_magic_file,
        save as save_magic_json,
    )
except Exception as e:
    print(f"Warning: magic normalizer not available: {e}")
    normalize_magic_file = None

# Plots normalizer (optional)
try:
    from scripts.format_plots import (
        normalize_file as normalize_plots_file,
        save as save_plots_json,
    )
except Exception as e:
    print(f"Warning: plots normalizer not available: {e}")
    normalize_plots_file = None

# Notion full sync utilities (characters)
try:
    from scripts.notion_sync import (
        push_characters_to_notion as push_chars_full,
        pull_characters_from_notion as pull_chars_full,
        CHAR_MAPPING_PATH,
        ensure_characters_schema as ensure_chars_schema,
        push_creatures_to_notion as push_creatures_full,
        pull_creatures_from_notion as pull_creatures_full,
        ensure_creatures_schema as ensure_creatures_schema,
        push_realms_to_notion as push_realms_full,
        pull_realms_from_notion as pull_realms_full,
        ensure_realms_schema as ensure_realms_schema,
        push_plots_to_notion as push_plots_full,
        pull_plots_from_notion as pull_plots_full,
        ensure_plots_schema as ensure_plots_schema,
        push_magic_to_notion as push_magic_full,
        pull_magic_from_notion as pull_magic_full,
        ensure_magic_schema as ensure_magic_schema,
    )
except Exception as e:
    print(f"Warning: notion sync utilities not available: {e}")
    push_chars_full = None
    pull_chars_full = None
    CHAR_MAPPING_PATH = None
    ensure_chars_schema = None
    push_creatures_full = None
    pull_creatures_full = None
    ensure_creatures_schema = None
    push_realms_full = None
    pull_realms_full = None
    ensure_realms_schema = None
    push_plots_full = None
    pull_plots_full = None
    ensure_plots_schema = None
    push_magic_full = None
    pull_magic_full = None
    ensure_magic_schema = None
    push_plots_full = None
    pull_plots_full = None
    ensure_plots_schema = None
    push_magic_full = None
    pull_magic_full = None
    ensure_magic_schema = None

# -------- INDEXING --------
def build_category_index(category):
    """Build index of entries from JSON files inside category folder.

    Preference order: lore/<category>/formatted/*.json if exists; otherwise lore/<category>/*.json
    """
    formatted_path = LORE_ROOT / category / "formatted"
    folder_path = formatted_path if formatted_path.exists() else (LORE_ROOT / category)
    index = []

    if not folder_path.exists():
        return []

    for file in sorted(folder_path.glob("*.json")):
        try:
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Handle dicts that contain lists (like characters, plots, etc.)
            if isinstance(data, dict) and category in data:
                for entry in data[category]:
                    entry_name = entry.get("name")
                    if not entry_name:
                        continue
                    index.append({
                        "name": entry_name,
                        "file": str(file.relative_to(LORE_ROOT)),
                        "category": category
                    })
            else:
                entry_name = data.get("name") or file.stem
                index.append({
                    "name": entry_name,
                    "file": str(file.relative_to(LORE_ROOT)),
                    "category": category
                })
        except Exception as e:
            print(f"âš ï¸ Error reading {file}: {e}")
            continue

    return index


def generate_master_index():
    """Generate per-category indexes and master index with cross-links."""
    INDEX_DIR.mkdir(exist_ok=True, parents=True)
    master_index = {}

    for category in CATEGORIES:
        index = build_category_index(category)
        index_file = INDEX_DIR / f"{category}_index.json"
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2)

        master_index[category] = {
            "index_file": str(index_file.relative_to(LORE_ROOT)),
            "entry_count": len(index),
        }

    # Simple cross-linking by entry name appearing in multiple categories
    crosslinks = {}
    name_to_category = {}
    for category in CATEGORIES:
        path = INDEX_DIR / f"{category}_index.json"
        if path.exists():
            entries = json.load(open(path, "r", encoding="utf-8"))
            for e in entries:
                n = e["name"]
                if n not in name_to_category:
                    name_to_category[n] = []
                name_to_category[n].append({"category": category, "file": e["file"]})

    for name, cats in name_to_category.items():
        if len(cats) > 1:
            crosslinks[name] = cats

    master_index["crosslinks"] = crosslinks

    # Write master index
    master_path = LORE_ROOT / "masterindex.json"
    with open(master_path, "w", encoding="utf-8") as f:
        json.dump(master_index, f, indent=2)

    return master_index


# -------- NOTION SYNC --------
def sync_index_to_notion(category):
    """Sync entries to Notion DB (create or update)."""
    # Guard if Notion client not initialized
    try:
        _ = notion  # type: ignore
    except NameError:
        return {"error": "Notion client not available in this runtime"}
    db_id = NOTION_DATABASES.get(category)
    if not db_id:
        return {"error": f"No Notion DB configured for '{category}'"}

    index_file = INDEX_DIR / f"{category}_index.json"
    if not index_file.exists():
        return {"error": f"Index file for '{category}' not found"}

    entries = json.load(open(index_file, "r", encoding="utf-8"))
    synced = 0

    for entry in entries:
        try:
            # Check if entry already exists in Notion
            results = notion.databases.query(
                database_id=db_id,
                filter={"property": "Name", "title": {"equals": entry["name"]}}
            )

            if results["results"]:
                # Update existing
                page_id = results["results"][0]["id"]
                notion.pages.update(
                    page_id=page_id,
                    properties={
                        "File Path": {
                            "rich_text": [{"text": {"content": entry["file"]}}]
                        }
                    }
                )
            else:
                # Create new
                notion.pages.create(
                    parent={"database_id": db_id},
                    properties={
                        "Name": {"title": [{"text": {"content": entry["name"]}}]},
                        "Category": {"select": {"name": category.capitalize()}},
                        "File Path": {
                            "rich_text": [{"text": {"content": entry["file"]}}]
                        }
                    }
                )
            synced += 1
        except Exception as e:
            print(f"âŒ Failed to sync {entry['name']}: {e}")

    return {"status": f"âœ… Synced {synced} {category} entries", "count": synced}


# -------- ROUTES --------
@app.route('/')
def home():
    return "ðŸ§š Welcome to the Notion Lore API for Fae-Lore-Vault"


@app.route('/generate-indexes', methods=['POST', 'GET'])
def generate_indexes():
    master_index = generate_master_index()
    return jsonify({"status": "âœ… Indexes generated", "masterindex": master_index})


@app.route('/get-masterindex', methods=['GET'])
def get_masterindex():
    path = LORE_ROOT / "masterindex.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify(data)
    return jsonify({"error": "masterindex.json not found"}), 404


@app.route('/get-index/<category>', methods=['GET'])
def get_category_index(category):
    if category not in CATEGORIES:
        return jsonify({"error": f"Unknown category '{category}'"}), 400

    path = INDEX_DIR / f"{category}_index.json"
    if not path.exists():
        return jsonify({"error": f"No index file for '{category}'"}), 404

    with open(path, "r", encoding="utf-8") as f:
        index_data = json.load(f)
    return jsonify(index_data)


# -------- SEARCH --------
@app.route('/search/<term>', methods=['GET'])
def search(term):
    """Fuzzy search across all indexes."""
    results = []
    for category in CATEGORIES:
        path = INDEX_DIR / f"{category}_index.json"
        if not path.exists():
            continue
        entries = json.load(open(path, "r", encoding="utf-8"))
        names = [e["name"] for e in entries]
        matches = get_close_matches(term, names, n=5, cutoff=0.5)
        for match in matches:
            match_entry = next((e for e in entries if e["name"] == match), None)
            if match_entry:
                results.append({**match_entry, "category": category})
    return jsonify(results)


# -------- CROSSLINK RESOLVER --------
@app.route('/related/<name>', methods=['GET'])
def related(name):
    """Return all categories/files where an entity appears (crosslinks)."""
    path = LORE_ROOT / "masterindex.json"
    if not path.exists():
        return jsonify({"error": "masterindex.json not found"}), 404

    with open(path, "r", encoding="utf-8") as f:
        master_index = json.load(f)

    crosslinks = master_index.get("crosslinks", {})
    related_entries = crosslinks.get(name)

    if not related_entries:
        # fallback fuzzy search if not exact match
        possible = get_close_matches(name, crosslinks.keys(), n=3, cutoff=0.6)
        return jsonify({
            "status": "âŒ No exact match",
            "closest_matches": possible
        })

    return jsonify({
        "name": name,
        "related": related_entries
    })


# -------- SYNC ROUTES --------
@app.route('/sync-<category>-to-notion', methods=['POST', 'GET'])
def sync_single(category):
    if category not in CATEGORIES:
        return jsonify({"error": f"Unknown category '{category}'"}), 400
    return jsonify(sync_index_to_notion(category))


@app.route('/sync-all-to-notion', methods=['POST', 'GET'])
def sync_all():
    results = {}
    try:
        _ = notion  # type: ignore
    except NameError:
        return jsonify({"error": "Notion client not available in this runtime"}), 500
    for category, db_id in NOTION_DATABASES.items():
        if db_id:  # only sync configured DBs
            results[category] = sync_index_to_notion(category)
        else:
            results[category] = {"status": "âš ï¸ Skipped (no DB ID configured)"}
    return jsonify(results)


# -------- CHARACTER FULL SYNC (JSON <-> Notion) --------
@app.route('/push-characters-to-notion', methods=['POST', 'GET'])
def push_characters_to_notion_route():
    if push_chars_full is None:
        return jsonify({"error": "Notion sync module not available"}), 500
    payload = request.get_json(silent=True) or {}
    mapping_path = payload.get("mapping")
    try:
        mp = Path(mapping_path) if mapping_path else None
        result = push_chars_full(mp)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/pull-characters-from-notion', methods=['POST', 'GET'])
def pull_characters_from_notion_route():
    if pull_chars_full is None:
        return jsonify({"error": "Notion sync module not available"}), 500
    payload = request.get_json(silent=True) or {}
    mapping_path = payload.get("mapping")
    try:
        mp = Path(mapping_path) if mapping_path else None
        result = pull_chars_full(mp)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/ensure-characters-schema', methods=['POST', 'GET'])
def ensure_characters_schema_route():
    if ensure_chars_schema is None:
        return jsonify({"error": "Notion sync module not available"}), 500
    payload = request.get_json(silent=True) or {}
    mapping_path = payload.get("mapping")
    try:
        mp = Path(mapping_path) if mapping_path else None
        result = ensure_chars_schema(mp)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -------- CREATURES FULL SYNC --------
@app.route('/ensure-creatures-schema', methods=['POST', 'GET'])
def ensure_creatures_schema_route():
    if ensure_creatures_schema is None:
        return jsonify({"error": "Notion sync module not available"}), 500
    payload = request.get_json(silent=True) or {}
    mapping_path = payload.get("mapping")
    try:
        mp = Path(mapping_path) if mapping_path else None
        result = ensure_creatures_schema(mp)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/push-creatures-to-notion', methods=['POST', 'GET'])
def push_creatures_to_notion_route():
    if push_creatures_full is None:
        return jsonify({"error": "Notion sync module not available"}), 500
    payload = request.get_json(silent=True) or {}
    mapping_path = payload.get("mapping")
    try:
        mp = Path(mapping_path) if mapping_path else None
        result = push_creatures_full(mp)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/pull-creatures-from-notion', methods=['POST', 'GET'])
def pull_creatures_from_notion_route():
    if pull_creatures_full is None:
        return jsonify({"error": "Notion sync module not available"}), 500
    payload = request.get_json(silent=True) or {}
    mapping_path = payload.get("mapping")
    try:
        mp = Path(mapping_path) if mapping_path else None
        result = pull_creatures_full(mp)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -------- REALMS FULL SYNC --------
@app.route('/ensure-realms-schema', methods=['POST', 'GET'])
def ensure_realms_schema_route():
    if ensure_realms_schema is None:
        return jsonify({"error": "Notion sync module not available"}), 500
    payload = request.get_json(silent=True) or {}
    mapping_path = payload.get("mapping")
    try:
        mp = Path(mapping_path) if mapping_path else None
        result = ensure_realms_schema(mp)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/push-realms-to-notion', methods=['POST', 'GET'])
def push_realms_to_notion_route():
    if push_realms_full is None:
        return jsonify({"error": "Notion sync module not available"}), 500
    payload = request.get_json(silent=True) or {}
    mapping_path = payload.get("mapping")
    try:
        mp = Path(mapping_path) if mapping_path else None
        result = push_realms_full(mp)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/pull-realms-from-notion', methods=['POST', 'GET'])
def pull_realms_from_notion_route():
    if pull_realms_full is None:
        return jsonify({"error": "Notion sync module not available"}), 500
    payload = request.get_json(silent=True) or {}
    mapping_path = payload.get("mapping")
    try:
        mp = Path(mapping_path) if mapping_path else None
        result = pull_realms_full(mp)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -------- PLOTS FULL SYNC --------
@app.route('/ensure-plots-schema', methods=['POST', 'GET'])
def ensure_plots_schema_route():
    if ensure_plots_schema is None:
        return jsonify({"error": "Notion sync module not available"}), 500
    payload = request.get_json(silent=True) or {}
    mapping_path = payload.get("mapping")
    try:
        mp = Path(mapping_path) if mapping_path else None
        result = ensure_plots_schema(mp)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/push-plots-to-notion', methods=['POST', 'GET'])
def push_plots_to_notion_route():
    if push_plots_full is None:
        return jsonify({"error": "Notion sync module not available"}), 500
    payload = request.get_json(silent=True) or {}
    mapping_path = payload.get("mapping")
    try:
        mp = Path(mapping_path) if mapping_path else None
        result = push_plots_full(mp)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/pull-plots-from-notion', methods=['POST', 'GET'])
def pull_plots_from_notion_route():
    if pull_plots_full is None:
        return jsonify({"error": "Notion sync module not available"}), 500
    payload = request.get_json(silent=True) or {}
    mapping_path = payload.get("mapping")
    try:
        mp = Path(mapping_path) if mapping_path else None
        result = pull_plots_full(mp)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -------- MAGIC FULL SYNC --------
@app.route('/ensure-magic-schema', methods=['POST', 'GET'])
def ensure_magic_schema_route():
    if ensure_magic_schema is None:
        return jsonify({"error": "Notion sync module not available"}), 500
    payload = request.get_json(silent=True) or {}
    mapping_path = payload.get("mapping")
    try:
        mp = Path(mapping_path) if mapping_path else None
        result = ensure_magic_schema(mp)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/push-magic-to-notion', methods=['POST', 'GET'])
def push_magic_to_notion_route():
    if push_magic_full is None:
        return jsonify({"error": "Notion sync module not available"}), 500
    payload = request.get_json(silent=True) or {}
    mapping_path = payload.get("mapping")
    try:
        mp = Path(mapping_path) if mapping_path else None
        result = push_magic_full(mp)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/pull-magic-from-notion', methods=['POST', 'GET'])
def pull_magic_from_notion_route():
    if pull_magic_full is None:
        return jsonify({"error": "Notion sync module not available"}), 500
    payload = request.get_json(silent=True) or {}
    mapping_path = payload.get("mapping")
    try:
        mp = Path(mapping_path) if mapping_path else None
        result = pull_magic_full(mp)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -------- BATCH ENSURE + PUSH --------
def _check_secret():
    secret = os.getenv("SYNC_SECRET")
    if not secret:
        return True
    # Allow either header or query param
    header = request.headers.get("X-Sync-Secret")
    param = request.args.get("secret")
    return header == secret or param == secret


@app.route('/publish-all', methods=['POST', 'GET'])
def publish_all():
    if not _check_secret():
        return jsonify({"error": "Unauthorized"}), 401
    results = {}
    # Characters
    if ensure_chars_schema and push_chars_full and os.getenv("CHARACTER_DB_ID"):
        try:
            ensure_res = ensure_chars_schema(None)
            push_res = push_chars_full(None)
            results["characters"] = {"ensure": ensure_res, "push": push_res}
        except Exception as e:
            results["characters"] = {"error": str(e)}
    # Creatures
    if ensure_creatures_schema and push_creatures_full and os.getenv("CREATURES_DB_ID"):
        try:
            ensure_res = ensure_creatures_schema(None)
            push_res = push_creatures_full(None)
            results["creatures"] = {"ensure": ensure_res, "push": push_res}
        except Exception as e:
            results["creatures"] = {"error": str(e)}
    # Realms
    if ensure_realms_schema and push_realms_full and os.getenv("REALMS_DB_ID"):
        try:
            ensure_res = ensure_realms_schema(None)
            push_res = push_realms_full(None)
            results["realms"] = {"ensure": ensure_res, "push": push_res}
        except Exception as e:
            results["realms"] = {"error": str(e)}
    # Magic
    if ensure_magic_schema and push_magic_full and os.getenv("MAGIC_DB_ID"):
        try:
            ensure_res = ensure_magic_schema(None)
            push_res = push_magic_full(None)
            results["magic"] = {"ensure": ensure_res, "push": push_res}
        except Exception as e:
            results["magic"] = {"error": str(e)}
    # Plots
    if ensure_plots_schema and push_plots_full and os.getenv("PLOTS_DB_ID"):
        try:
            ensure_res = ensure_plots_schema(None)
            push_res = push_plots_full(None)
            results["plots"] = {"ensure": ensure_res, "push": push_res}
        except Exception as e:
            results["plots"] = {"error": str(e)}

    return jsonify({"status": "ok", "results": results})


@app.route('/pull-all', methods=['POST', 'GET'])
def pull_all():
    if not _check_secret():
        return jsonify({"error": "Unauthorized"}), 401
    results = {}
    if pull_chars_full and os.getenv("CHARACTER_DB_ID"):
        try:
            results["characters"] = pull_chars_full(None)
        except Exception as e:
            results["characters"] = {"error": str(e)}
    if pull_creatures_full and os.getenv("CREATURES_DB_ID"):
        try:
            results["creatures"] = pull_creatures_full(None)
        except Exception as e:
            results["creatures"] = {"error": str(e)}
    if pull_realms_full and os.getenv("REALMS_DB_ID"):
        try:
            results["realms"] = pull_realms_full(None)
        except Exception as e:
            results["realms"] = {"error": str(e)}
    if pull_magic_full and os.getenv("MAGIC_DB_ID"):
        try:
            results["magic"] = pull_magic_full(None)
        except Exception as e:
            results["magic"] = {"error": str(e)}
    if pull_plots_full and os.getenv("PLOTS_DB_ID"):
        try:
            results["plots"] = pull_plots_full(None)
        except Exception as e:
            results["plots"] = {"error": str(e)}

    return jsonify({"status": "ok", "results": results})


# -------- AUTO SYNC SCHEDULER --------
def _bool_env(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _do_publish_all_internal():
    results = {}
    try:
        if ensure_chars_schema and push_chars_full and os.getenv("CHARACTER_DB_ID"):
            results["characters"] = {"ensure": ensure_chars_schema(None), "push": push_chars_full(None)}
        if ensure_creatures_schema and push_creatures_full and os.getenv("CREATURES_DB_ID"):
            results["creatures"] = {"ensure": ensure_creatures_schema(None), "push": push_creatures_full(None)}
        if ensure_realms_schema and push_realms_full and os.getenv("REALMS_DB_ID"):
            results["realms"] = {"ensure": ensure_realms_schema(None), "push": push_realms_full(None)}
        if ensure_magic_schema and push_magic_full and os.getenv("MAGIC_DB_ID"):
            results["magic"] = {"ensure": ensure_magic_schema(None), "push": push_magic_full(None)}
        if ensure_plots_schema and push_plots_full and os.getenv("PLOTS_DB_ID"):
            results["plots"] = {"ensure": ensure_plots_schema(None), "push": push_plots_full(None)}
    except Exception as e:
        results["error"] = str(e)
    return results


def _do_pull_all_internal():
    results = {}
    try:
        if pull_chars_full and os.getenv("CHARACTER_DB_ID"):
            results["characters"] = pull_chars_full(None)
        if pull_creatures_full and os.getenv("CREATURES_DB_ID"):
            results["creatures"] = pull_creatures_full(None)
        if pull_realms_full and os.getenv("REALMS_DB_ID"):
            results["realms"] = pull_realms_full(None)
        if pull_magic_full and os.getenv("MAGIC_DB_ID"):
            results["magic"] = pull_magic_full(None)
        if pull_plots_full and os.getenv("PLOTS_DB_ID"):
            results["plots"] = pull_plots_full(None)
    except Exception as e:
        results["error"] = str(e)
    return results


def _start_scheduler_if_enabled():
    # Only run when a token is present and at least one DB ID is configured
    if not os.getenv("NOTION_TOKEN"):
        return
    if not any(os.getenv(k) for k in [
        "CHARACTER_DB_ID", "CREATURES_DB_ID", "REALMS_DB_ID", "MAGIC_DB_ID", "PLOTS_DB_ID"
    ]):
        return

    interval_minutes = int(os.getenv("AUTO_SYNC_INTERVAL_MINUTES", "60"))
    pull_on_start = _bool_env("AUTO_PULL_ON_START", True)
    publish_on_start = _bool_env("AUTO_PUBLISH_ON_START", False)
    pull_each_cycle = _bool_env("AUTO_PULL_EACH_CYCLE", True)
    publish_each_cycle = _bool_env("AUTO_PUBLISH_EACH_CYCLE", False)

    def _maybe_refactor_creatures():
        try:
            if not _bool_env("AUTO_REFACTOR_CREATURES_ON_START", True):
                return
            # If formatted creatures are missing or very few, attempt a refactor
            formatted = LORE_ROOT / "creatures" / "formatted"
            existing = list(formatted.glob("**/*.json")) if formatted.exists() else []
            src = LORE_ROOT / "creatures" / "creatures.json"
            if len(existing) < 5 and src.exists() and normalize_creatures_file is not None:
                # Load synonyms
                default_map = LORE_ROOT / "creatures" / "mappings.json"
                try:
                    syn = load_creatures_synonyms(default_map)
                    set_creatures_synonyms(syn)
                except Exception:
                    pass
                # Normalize entries from source file
                entries = normalize_creatures_file(src)
                outdir = formatted
                outdir.mkdir(parents=True, exist_ok=True)
                written = 0
                for e in entries:
                    name = e.get("name") or e.get("id") or "creature"
                    safe = "".join(c if c.isalnum() or c in (".", "_", "-") else "_" for c in name)
                    reg = e.get("region") or "Uncategorized"
                    reg_safe = "".join(c if c.isalnum() or c in (".", "_", "-") else "_" for c in str(reg))
                    sub = outdir / reg_safe
                    sub.mkdir(parents=True, exist_ok=True)
                    save_json_util(sub / f"{safe}.json", e)
                    written += 1
                # Build region bundles
                try:
                    from scripts.format_creatures import build_region_bundles as _bundles
                    bundles = _bundles(entries)
                    base = outdir / "regions"
                    base.mkdir(parents=True, exist_ok=True)
                    for region, data in bundles.items():
                        rsafe = "".join(c if c.isalnum() or c in (".", "_", "-") else "_" for c in region)
                        save_json_util(base / f"{rsafe}.json", data)
                except Exception:
                    pass
                # Rewrite source to compact index with backup
                try:
                    orig = src.read_text(encoding="utf-8")
                    (src.parent / "creatures.json.bak").write_text(orig, encoding="utf-8")
                except Exception:
                    pass
                compact = {
                    "note": "Data split into lore/creatures/formatted and /formatted/regions for bundles.",
                    "total": len(entries),
                }
                save_json_util(src, compact)
                print(f"Auto-refactor creatures completed: {written} entries")
        except Exception as e:
            print(f"Auto-refactor creatures skipped: {e}")

    def _maybe_refactor_magic():
        try:
            if normalize_magic_file is None:
                return
            formatted = LORE_ROOT / "magic" / "formatted"
            existing = list(formatted.glob("**/*.json")) if formatted.exists() else []
            src = LORE_ROOT / "magic" / "magic_and_abilities.json"
            if len(existing) < 5 and src.exists():
                entries = normalize_magic_file(src)
                written = 0
                formatted.mkdir(parents=True, exist_ok=True)
                for e in entries:
                    name = e.get("name") or e.get("id") or "magic"
                    safe = "".join(c if c.isalnum() or c in (".", "_", "-") else "_" for c in name)
                    save_json_util(formatted / f"{safe}.json", e)
                    written += 1
                # backup + compact
                try:
                    orig = src.read_text(encoding="utf-8")
                    (src.parent / "magic_and_abilities.json.bak").write_text(orig, encoding="utf-8")
                except Exception:
                    pass
                compact = {"note": "Data split into lore/magic/formatted", "total": len(entries)}
                save_json_util(src, compact)
                print(f"Auto-refactor magic completed: {written} entries")
        except Exception as e:
            print(f"Auto-refactor magic skipped: {e}")

    def _maybe_refactor_plots():
        try:
            if normalize_plots_file is None:
                return
            formatted = LORE_ROOT / "plots" / "formatted"
            existing = list(formatted.glob("**/*.json")) if formatted.exists() else []
            src = LORE_ROOT / "plots" / "Plots.json"
            if len(existing) < 3 and src.exists():
                entries = normalize_plots_file(src)
                written = 0
                formatted.mkdir(parents=True, exist_ok=True)
                for e in entries:
                    name = e.get("name") or e.get("id") or "plot"
                    safe = "".join(c if c.isalnum() or c in (".", "_", "-") else "_" for c in name)
                    save_json_util(formatted / f"{safe}.json", e)
                    written += 1
                # backup + compact
                try:
                    orig = src.read_text(encoding="utf-8")
                    (src.parent / "Plots.json.bak").write_text(orig, encoding="utf-8")
                except Exception:
                    pass
                compact = {"note": "Data split into lore/plots/formatted", "total": len(entries)}
                save_json_util(src, compact)
                print(f"Auto-refactor plots completed: {written} entries")
        except Exception as e:
            print(f"Auto-refactor plots skipped: {e}")

    def worker():
        # initial delay allows the app to finish booting
        time.sleep(3)
        _maybe_refactor_creatures()
        _maybe_refactor_magic()
        _maybe_refactor_plots()
        if pull_on_start:
            _do_pull_all_internal()
        if publish_on_start:
            _do_publish_all_internal()
        while True:
            time.sleep(interval_minutes * 60)
            if pull_each_cycle:
                _do_pull_all_internal()
            if publish_each_cycle:
                _do_publish_all_internal()

    try:
        t = threading.Thread(target=worker, name="auto-sync", daemon=True)
        t.start()
        print(f"Auto-sync scheduler started: every {interval_minutes} min")
    except Exception as e:
        print(f"Failed to start auto-sync scheduler: {e}")


# Kick off scheduler at import time
_start_scheduler_if_enabled()


# -------- HEALTH CHECKS --------
@app.route('/health/notion', methods=['GET'])
def health_notion():
    token_present = bool(os.getenv("NOTION_TOKEN"))
    char_db_id = os.getenv("CHARACTER_DB_ID")
    try:
        client = Client(auth=os.getenv("NOTION_TOKEN")) if token_present else None
    except Exception:
        client = None
    status = {
        "token_present": token_present,
        "character_db_id": char_db_id,
        "client_initialized": client is not None,
        "access_ok": False,
        "message": None,
    }
    if not token_present:
        status["message"] = "NOTION_TOKEN missing"
        return jsonify(status)
    if not char_db_id:
        status["message"] = "CHARACTER_DB_ID missing"
        return jsonify(status)
    if client is None:
        status["message"] = "Failed to initialize Notion client"
        return jsonify(status)
    try:
        client.databases.query(database_id=char_db_id, page_size=1)
        status["access_ok"] = True
        status["message"] = "OK"
    except Exception as e:
        status["message"] = f"Query failed: {e}"
    return jsonify(status)


# -------- MAPPING VALIDATOR --------
@app.route('/validate-mapping/<category>', methods=['GET'])
def validate_mapping(category):
    try:
        from scripts.notion_sync import get_env_client_for, get_db_property_types, load_mapping
    except Exception as e:
        return jsonify({"error": f"Validator unavailable: {e}"}), 500
    try:
        notion, db_id = get_env_client_for(category)
        actual = get_db_property_types(notion, db_id)
        mp = load_mapping(None, category=category)
        mismatches = []
        missing = []
        for prop, spec in mp.items():
            mtype = spec.get("type")
            atype = actual.get(prop)
            if atype is None:
                missing.append(prop)
            elif atype != mtype:
                mismatches.append({"property": prop, "mapping_type": mtype, "actual_type": atype})
        extras = [p for p in actual.keys() if p not in mp]
        return jsonify({
            "database_id": db_id,
            "missing_in_db": missing,
            "type_mismatches": mismatches,
            "unmapped_properties": extras,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -------- SIMPLE WEB DASHBOARD --------
@app.route('/dashboard', methods=['GET'])
def dashboard():
    cats = CATEGORIES
    tiles = []
    for c in cats:
        tiles.append(f'''
        <div class="tile">
          <h3>{c.title()}</h3>
          <p>Manage {c} data.</p>
          <p>
            <a href="#" onclick="call('/ensure-{c}-schema')">Ensure</a> ·
            <a href="#" onclick="call('/push-{c}-to-notion')">Push</a> ·
            <a href="#" onclick="call('/pull-{c}-from-notion')">Pull</a> ·
            <a href="#" onclick="call('/validate-mapping/{c}')">Validate</a>
          </p>
        </div>
        ''')

    html = f'''<!doctype html>
    <html>
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1"/>
      <title>Notion Lore Control</title>
      <link rel="stylesheet" href="/main.css" />
    </head>
    <body>
      <nav>
        <ul>
          <li><a href="/">Home</a></li>
          <li><a href="#" onclick="call('/health/notion')">Health</a></li>
          <li><a href="#" onclick="call('/generate-indexes')">Generate Indexes</a></li>
          <li><a href="#" onclick="batch('publish')">Publish All</a></li>
          <li><a href="#" onclick="batch('pull')">Pull All</a></li>
        </ul>
      </nav>
      <section id="header">
        <h1>Notion Lore Control</h1>
        <p>Manage sync with a click. Optional secret for batch actions:</p>
        <input id="secret" type="text" placeholder="Optional SYNC_SECRET" />
      </section>
      <section id="links">
        {''.join(tiles)}
      </section>
      <section class="footer">
        <div id="log">Ready.</div>
      </section>
      <script>
        async function call(path) {{
          const log = document.getElementById('log');
          log.textContent = 'Request: ' + path + '\\n';
          try {{
            const res = await fetch(path, {{ method: 'GET' }});
            const txt = await res.text();
            log.textContent += 'Status: ' + res.status + '\\n' + txt;
          }} catch (e) {{
            log.textContent += 'Error: ' + e;
          }}
        }}
        function batch(kind) {{
          const sec = document.getElementById('secret').value;
          const path = kind === 'publish' ? '/publish-all' : '/pull-all';
          const q = sec ? path + '?secret=' + encodeURIComponent(sec) : path;
          call(q);
        }}
      </script>
    </body>
    </html>'''
    return html

@app.route('/main.css')
def serve_main_css():
    return send_from_directory('.', 'main.css', mimetype='text/css')

@app.route('/getLore', methods=['GET'])
def get_lore():
    subject = request.args.get("subject")

    # Search across all categories for exact match
    for category in CATEGORIES:
        index_path = INDEX_DIR / f"{category}_index.json"
        if not index_path.exists():
            continue

        with open(index_path, "r", encoding="utf-8") as f:
            entries = json.load(f)

        for entry in entries:
            if entry["name"] == subject:
                # Locate and load the JSON file
                lore_file = LORE_ROOT / entry["file"]
                if lore_file.exists():
                    with open(lore_file, "r", encoding="utf-8") as lf:
                        lore_data = json.load(lf)
                    return jsonify({
                        "subject": subject,
                        "category": category,
                        "content": lore_data
                    })

    return jsonify({"error": f"No lore entry found for '{subject}'"}), 404


# -------- NORMALIZATION ROUTE --------
@app.route('/normalize-characters', methods=['POST', 'GET'])
def normalize_characters_route():
    if normalize_character_file is None:
        return jsonify({"error": "Character normalizer module not available"}), 500

    # Defaults
    default_input = LORE_ROOT / "characters" / "characters.json"
    default_outdir = LORE_ROOT / "characters" / "formatted"
    payload = request.get_json(silent=True) or {}

    input_path = payload.get("input")
    scan_dir = payload.get("scan")
    outdir = Path(payload.get("outdir") or default_outdir)
    split = bool(payload.get("split", True))
    write_index = bool(payload.get("index", True))
    output_combined = payload.get("output")
    mappings_path = payload.get("mappings")

    inputs: List[Path] = []
    if input_path:
        inputs = [Path(input_path)]
    elif scan_dir:
        inputs = list(Path(scan_dir).glob("*.json"))
    elif default_input.exists():
        inputs = [default_input]
    else:
        return jsonify({"error": "No input provided and default characters.json not found"}), 400

    # Load synonyms and set in module
    if mappings_path:
        synonyms = load_character_synonyms(Path(mappings_path))
    else:
        default_map = LORE_ROOT / "characters" / "mappings.json"
        synonyms = load_character_synonyms(default_map)
    set_character_synonyms(synonyms)

    all_entries = []
    for p in inputs:
        try:
            all_entries.extend(normalize_character_file(p))
        except Exception as e:
            return jsonify({"error": f"Failed to normalize {p}", "details": str(e)}), 500

    written_files = []
    if split:
        outdir.mkdir(parents=True, exist_ok=True)
        for e in all_entries:
            name = e.get("name") or e.get("id") or "character"
            safe = "".join(c if c.isalnum() or c in (".", "_", "-") else "_" for c in name)
            path = outdir / f"{safe}.json"
            save_json_util(path, e)
            written_files.append(str(path))
        if write_index:
            idx_path = outdir / "_index.json"
            save_json_util(idx_path, build_character_index(all_entries))
            written_files.append(str(idx_path))

    if output_combined:
        out_path = Path(output_combined)
        save_json_util(out_path, {"characters": all_entries})
        written_files.append(str(out_path))

    return jsonify({
        "status": "ok",
        "count": len(all_entries),
        "written": written_files,
    })


# -------- CREATURES NORMALIZATION ROUTE --------
@app.route('/normalize-creatures', methods=['POST', 'GET'])
def normalize_creatures_route():
    if normalize_creatures_file is None:
        return jsonify({"error": "Creatures normalizer module not available"}), 500

    default_input = LORE_ROOT / "creatures" / "creatures.json"
    default_outdir = LORE_ROOT / "creatures" / "formatted"
    payload = request.get_json(silent=True) or {}

    input_path = payload.get("input")
    scan_dir = payload.get("scan")
    outdir = Path(payload.get("outdir") or default_outdir)
    split = bool(payload.get("split", True))
    by_region = bool(payload.get("by_region", False))
    region_bundles = bool(payload.get("region_bundles", False))
    write_index = bool(payload.get("index", True))
    output_combined = payload.get("output")
    mappings_path = payload.get("mappings")

    inputs: List[Path] = []
    if input_path:
        inputs = [Path(input_path)]
    elif scan_dir:
        inputs = list(Path(scan_dir).glob("*.json"))
    elif default_input.exists():
        inputs = [default_input]
    else:
        return jsonify({"error": "No input provided and default creatures.json not found"}), 400

    # Synonyms
    if mappings_path:
        synonyms = load_creatures_synonyms(Path(mappings_path))
    else:
        default_map = LORE_ROOT / "creatures" / "mappings.json"
        synonyms = load_creatures_synonyms(default_map)
    set_creatures_synonyms(synonyms)

    all_entries = []
    for p in inputs:
        try:
            all_entries.extend(normalize_creatures_file(p))
        except Exception as e:
            return jsonify({"error": f"Failed to normalize {p}", "details": str(e)}), 500

    written_files = []
    if split:
        outdir.mkdir(parents=True, exist_ok=True)
        for e in all_entries:
            name = e.get("name") or e.get("id") or "creature"
            safe = "".join(c if c.isalnum() or c in (".", "_", "-") else "_" for c in name)
            # Optional region subfolder
            subdir = outdir
            if by_region:
                reg = e.get("region") or "Uncategorized"
                reg_safe = "".join(c if c.isalnum() or c in (".", "_", "-") else "_" for c in str(reg))
                subdir = outdir / reg_safe
                subdir.mkdir(parents=True, exist_ok=True)
            path = subdir / f"{safe}.json"
            save_json_util(path, e)
            written_files.append(str(path))
        if write_index:
            idx_path = outdir / "_index.json"
            save_json_util(idx_path, build_creatures_index(all_entries))
            written_files.append(str(idx_path))

        if region_bundles:
            bundles = build_creatures_region_bundles(all_entries)
            base = outdir / "regions"
            for region, data in bundles.items():
                rsafe = "".join(c if c.isalnum() or c in (".", "_", "-") else "_" for c in region)
                rpath = base / f"{rsafe}.json"
                save_json_util(rpath, data)
                written_files.append(str(rpath))

    if output_combined:
        out_path = Path(output_combined)
        save_json_util(out_path, {"creatures": all_entries})
        written_files.append(str(out_path))

    return jsonify({
        "status": "ok",
        "count": len(all_entries),
        "written": written_files,
    })


# -------- CREATURES REFACTOR (split + rewrite source as lightweight index) --------
@app.route('/refactor-creatures', methods=['POST', 'GET'])
def refactor_creatures_route():
    if normalize_creatures_file is None:
        return jsonify({"error": "Creatures normalizer module not available"}), 500

    default_input = LORE_ROOT / "creatures" / "creatures.json"
    default_outdir = LORE_ROOT / "creatures" / "formatted"
    payload = request.get_json(silent=True) or {}

    input_path = Path(payload.get("input") or default_input)
    outdir = Path(payload.get("outdir") or default_outdir)
    by_region = bool(payload.get("by_region", True))
    region_bundles = bool(payload.get("region_bundles", True))
    rewrite_source = bool(payload.get("rewrite_source", True))
    mappings_path = payload.get("mappings")

    # Synonyms
    if mappings_path:
        synonyms = load_creatures_synonyms(Path(mappings_path))
    else:
        default_map = LORE_ROOT / "creatures" / "mappings.json"
        synonyms = load_creatures_synonyms(default_map)
    set_creatures_synonyms(synonyms)

    # Normalize from the single source file
    try:
        entries = normalize_creatures_file(input_path)
    except Exception as e:
        return jsonify({"error": f"Failed to normalize {input_path}", "details": str(e)}), 500

    written: List[str] = []

    # Write per-creature split files (nested by region if requested)
    outdir.mkdir(parents=True, exist_ok=True)
    for e in entries:
        name = e.get("name") or e.get("id") or "creature"
        safe = "".join(c if c.isalnum() or c in (".", "_", "-") else "_" for c in name)
        sub = outdir
        if by_region:
            reg = e.get("region") or "Uncategorized"
            reg_safe = "".join(c if c.isalnum() or c in (".", "_", "-") else "_" for c in str(reg))
            sub = outdir / reg_safe
            sub.mkdir(parents=True, exist_ok=True)
        path = sub / f"{safe}.json"
        save_json_util(path, e)
        written.append(str(path))

    # Build and write region bundles
    bundle_index = []
    if region_bundles:
        try:
            from scripts.format_creatures import build_region_bundles as _build_bundles
        except Exception as e:
            return jsonify({"error": "Region bundle helper missing", "details": str(e)}), 500
        bundles = _build_bundles(entries)
        base = outdir / "regions"
        base.mkdir(parents=True, exist_ok=True)
        for region, data in bundles.items():
            rsafe = "".join(c if c.isalnum() or c in (".", "_", "-") else "_" for c in region)
            rpath = base / f"{rsafe}.json"
            save_json_util(rpath, data)
            bundle_index.append({"region": region, "file": str(rpath)})
            written.append(str(rpath))

    # Rewrite the original creatures.json to a compact index
    if rewrite_source and default_input.exists():
        compact = {
            "creatures_by_region": bundle_index,
            "total": len(entries),
            "note": "Data split into lore/creatures/formatted (per-creature) and lore/creatures/formatted/regions (bundles).",
        }
        try:
            # simple backup
            try:
                orig_text = default_input.read_text(encoding="utf-8")
                (default_input.parent / "creatures.json.bak").write_text(orig_text, encoding="utf-8")
            except Exception:
                pass
            save_json_util(default_input, compact)
        except Exception as e:
            return jsonify({"error": "Failed to rewrite source creatures.json", "details": str(e)}), 500

    return jsonify({
        "status": "ok",
        "split_count": len(entries),
        "bundle_count": len(bundle_index),
        "written": written,
        "rewrote_source": bool(rewrite_source),
    })


# -------- REALMS NORMALIZATION ROUTE --------
@app.route('/normalize-realms', methods=['POST', 'GET'])
def normalize_realms_route():
    if normalize_realms_file is None:
        return jsonify({"error": "Realms normalizer module not available"}), 500

    default_input = LORE_ROOT / "realms" / "realms.json"
    default_outdir = LORE_ROOT / "realms" / "formatted"
    payload = request.get_json(silent=True) or {}

    input_path = payload.get("input")
    scan_dir = payload.get("scan")
    outdir = Path(payload.get("outdir") or default_outdir)
    split = bool(payload.get("split", True))
    write_index = bool(payload.get("index", True))
    output_combined = payload.get("output")
    mappings_path = payload.get("mappings")

    inputs: List[Path] = []
    if input_path:
        inputs = [Path(input_path)]
    elif scan_dir:
        inputs = list(Path(scan_dir).glob("*.json"))
    elif default_input.exists():
        inputs = [default_input]
    else:
        return jsonify({"error": "No input provided and default realms.json not found"}), 400

    # Synonyms
    if mappings_path:
        synonyms = load_realms_synonyms(Path(mappings_path))
    else:
        default_map = LORE_ROOT / "realms" / "mappings.json"
        synonyms = load_realms_synonyms(default_map)
    set_realms_synonyms(synonyms)

    all_entries = []
    for p in inputs:
        try:
            all_entries.extend(normalize_realms_file(p))
        except Exception as e:
            return jsonify({"error": f"Failed to normalize {p}", "details": str(e)}), 500

    written_files = []
    if split:
        outdir.mkdir(parents=True, exist_ok=True)
        for e in all_entries:
            name = e.get("name") or e.get("id") or "realm"
            safe = "".join(c if c.isalnum() or c in (".", "_", "-") else "_" for c in name)
            path = outdir / f"{safe}.json"
            save_json_util(path, e)
            written_files.append(str(path))
        if write_index:
            idx_path = outdir / "_index.json"
            save_json_util(idx_path, build_realms_index(all_entries))
            written_files.append(str(idx_path))

    if output_combined:
        out_path = Path(output_combined)
        save_json_util(out_path, {"realms": all_entries})
        written_files.append(str(out_path))

    return jsonify({
        "status": "ok",
        "count": len(all_entries),
        "written": written_files,
    })


if __name__ == '__main__':
    app.run(debug=True)

