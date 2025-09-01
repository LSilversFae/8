from flask import Flask, jsonify
import os
import json
from pathlib import Path

app = Flask(__name__)

LORE_ROOT = Path("lore")
INDEX_DIR = LORE_ROOT / "indexes"
CATEGORIES = ["characters", "creatures", "magic", "plots", "realms"]

@app.route('/')
def home():
    return "Hello from Notion Lore API!"

@app.route('/generate-indexes', methods=['POST', 'GET'])
def generate_indexes():
    INDEX_DIR.mkdir(exist_ok=True, parents=True)
    master_index = {}

    for category in CATEGORIES:
        folder_path = LORE_ROOT / category
        index = []

        if not folder_path.exists():
            continue

        for file in sorted(folder_path.glob("*.json")):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    entry_name = data.get("name") or file.stem
            except Exception:
                entry_name = file.stem

            index.append({
                "name": entry_name,
                "file": str(file.relative_to(LORE_ROOT))
            })

        # Write category index
        index_filename = f"{category}_index.json"
        index_path = INDEX_DIR / index_filename
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2)

        # Update master index
        master_index[category] = {
            "index_file": str(index_path.relative_to(LORE_ROOT)),
            "entry_count": len(index),
        }

    # Write master index
    with open(LORE_ROOT / "masterindex.json", "w", encoding="utf-8") as f:
        json.dump(master_index, f, indent=2)

    return jsonify({"status": "✅ Indexes generated", "entries": master_index})

@app.route('/get-masterindex', methods=['GET'])
def get_masterindex():
    path = LORE_ROOT / "masterindex.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify(data)
    return jsonify({"error": "masterindex.json not found"}), 404

if __name__ == '__main__':
    app.run(debug=True)
