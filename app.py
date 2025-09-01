from flask import Flask, jsonify, request
import os
import json
from pathlib import Path
from notion_client import Client
from dotenv import load_dotenv
from difflib import get_close_matches

# Load environment variables
load_dotenv()

# --- Notion API setup ---
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
if not NOTION_TOKEN:
    raise ValueError("❌ Missing NOTION_TOKEN in environment variables")

notion = Client(auth=NOTION_TOKEN)

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
        print(f"⚠️ Warning: No DB ID set for {category}. Sync for this category will be skipped.")

# --- Flask setup ---
app = Flask(__name__)

# Paths
LORE_ROOT = Path("lore")
INDEX_DIR = LORE_ROOT / "indexes"
CATEGORIES = ["characters", "creatures", "magic", "plots", "realms"]

# -------- INDEXING --------
def build_category_index(category):
    """Build index of entries from JSON files inside category folder."""
    folder_path = LORE_ROOT / category
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
            print(f"⚠️ Error reading {file}: {e}")
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
            print(f"❌ Failed to sync {entry['name']}: {e}")

    return {"status": f"✅ Synced {synced} {category} entries", "count": synced}


# -------- ROUTES --------
@app.route('/')
def home():
    return "🧚 Welcome to the Notion Lore API for Fae-Lore-Vault"


@app.route('/generate-indexes', methods=['POST', 'GET'])
def generate_indexes():
    master_index = generate_master_index()
    return jsonify({"status": "✅ Indexes generated", "masterindex": master_index})


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
            "status": "❌ No exact match",
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
    for category, db_id in NOTION_DATABASES.items():
        if db_id:  # only sync configured DBs
            results[category] = sync_index_to_notion(category)
        else:
            results[category] = {"status": "⚠️ Skipped (no DB ID configured)"}
    return jsonify(results)


if __name__ == '__main__':
    app.run(debug=True)
