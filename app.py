from flask import Flask, jsonify, request
import os
import json
from pathlib import Path
from notion_client import Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Notion API setup
NOTION_TOKEN = os.getenv("NOTION_TOKEN") or "your_token_here"
notion = Client(auth=NOTION_TOKEN)

NOTION_DATABASES = {
    "characters": os.getenv("CHARACTER_DB_ID") or "your_characters_db_id",
    "plots": os.getenv("PLOTS_DB_ID") or "your_plots_db_id",
    "magic": os.getenv("MAGIC_DB_ID") or "your_magic_db_id",
    "creatures": os.getenv("CREATURES_DB_ID") or "your_creatures_db_id",
    "realms": os.getenv("REALMS_DB_ID") or "your_realms_db_id",
}

app = Flask(__name__)

# Paths
LORE_ROOT = Path("lore")
INDEX_DIR = LORE_ROOT / "indexes"
CATEGORIES = ["characters", "creatures", "magic", "plots", "realms"]

def build_category_index(category):
    folder_path = LORE_ROOT / category
    index = []

    if not folder_path.exists():
        return []

    for file in sorted(folder_path.glob("*.json")):
        try:
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f)
                entry_name = data.get("name") or file.stem
        except Exception:
            entry_name = file.stem  # fallback if JSON is malformed

        index.append({
            "name": entry_name,
            "file": str(file.relative_to(LORE_ROOT))
        })

    return index

def sync_index_to_notion(category):
    db_id = NOTION_DATABASES.get(category)
    if not db_id:
        return {"error": f"No Notion DB configured for '{category}'"}

    index_file = INDEX_DIR / f"{category}_index.json"
    if not index_file.exists():
        return {"error": f"Index file for '{category}' not found"}

    with open(index_file, "r", encoding="utf-8") as f:
        entries = json.load(f)

    synced = 0
    for entry in entries:
        try:
            notion.pages.create(
                parent={"database_id": db_id},
                properties={
                    "Name": {
                        "title": [{"text": {"content": entry["name"]}}]
                    },
                    "Category": {
                        "select": {"name": category.capitalize()}
                    },
                    "File Path": {
                        "rich_text": [{"text": {"content": entry["file"]}}]
                    }
                }
            )
            synced += 1
        except Exception as e:
            print(f"❌ Failed to sync {entry['name']}: {e}")

    return {"status": f"✅ Synced {synced} {category} entries", "count": synced}

@app.route('/')
def home():
    return "🧚 Welcome to the Notion Lore API for Fae-Lore-Vault"

@app.route('/generate-indexes', methods=['POST', 'GET'])
def generate_indexes():
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

    # Write master index
    master_path = LORE_ROOT / "masterindex.json"
    with open(master_path, "w", encoding="utf-8") as f:
        json.dump(master_index, f, indent=2)

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

# Category-specific sync routes
@app.route('/sync-characters-to-notion', methods=['POST', 'GET'])
def sync_characters():
    return jsonify(sync_index_to_notion("characters"))

@app.route('/sync-plots-to-notion', methods=['POST', 'GET'])
def sync_plots():
    return jsonify(sync_index_to_notion("plots"))

@app.route('/sync-magic-to-notion', methods=['POST', 'GET'])
def sync_magic():
    return jsonify(sync_index_to_notion("magic"))

@app.route('/sync-creatures-to-notion', methods=['POST', 'GET'])
def sync_creatures():
    return jsonify(sync_index_to_notion("creatures"))

@app.route('/sync-realms-to-notion', methods=['POST', 'GET'])
def sync_realms():
    return jsonify(sync_index_to_notion("realms"))

# Sync all categories route
@app.route('/sync-all-to-notion', methods=['POST', 'GET'])
def sync_all():
    results = {}
    for category in NOTION_DATABASES.keys():
        results[category] = sync_index_to_notion(category)
    return jsonify(results)

if __name__ == '__main__':
    app.run(debug=True)