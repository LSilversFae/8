from flask import Flask, jsonify
import os
import json
from pathlib import Path

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

if __name__ == '__main__':
    app.run(debug=True)