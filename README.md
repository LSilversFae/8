Notion Lore API — Quick Guide

Overview
This service syncs JSON lore files with Notion databases. It supports Characters, Creatures, Realms, Magic, and Plots, and provides both one‑off endpoints and a background auto‑sync.

Environment
- NOTION_TOKEN: ntn_... integration token (must be invited to each DB)
- *_DB_ID: 32‑char database IDs (CHARACTER_DB_ID, CREATURES_DB_ID, REALMS_DB_ID, MAGIC_DB_ID, PLOTS_DB_ID)
- Optional batch endpoint secret: SYNC_SECRET
- Optional autosync flags (defaults shown):
  - AUTO_SYNC_INTERVAL_MINUTES=60
  - AUTO_PULL_ON_START=true
  - AUTO_PULL_EACH_CYCLE=true
  - AUTO_PUBLISH_ON_START=false
  - AUTO_PUBLISH_EACH_CYCLE=false

Core Endpoints
- Health: GET /health/notion
- Generate indexes: GET/POST /generate-indexes

Characters
- Ensure schema: GET/POST /ensure-characters-schema
- Push JSON→Notion: GET/POST /push-characters-to-notion
- Pull Notion→JSON: GET/POST /pull-characters-from-notion

Creatures
- Normalize (split, by region, bundles): POST /normalize-creatures
  Body example:
  {
    "scan": "lore/creatures",
    "outdir": "lore/creatures/formatted",
    "split": true,
    "index": true,
    "mappings": "lore/creatures/mappings.json",
    "by_region": true,
    "region_bundles": true
  }
- Refactor source (split + rewrite creatures.json to an index): GET/POST /refactor-creatures
- Ensure schema: GET/POST /ensure-creatures-schema
- Push: GET/POST /push-creatures-to-notion
- Pull: GET/POST /pull-creatures-from-notion

Realms / Magic / Plots
- Ensure schema: /ensure-realms-schema, /ensure-magic-schema, /ensure-plots-schema
- Push: /push-realms-to-notion, /push-magic-to-notion, /push-plots-to-notion
- Pull: /pull-realms-from-notion, /pull-magic-from-notion, /pull-plots-from-notion

Batch Endpoints
- Publish all (ensure→push each configured category): GET/POST /publish-all
- Pull all: GET/POST /pull-all
- If SYNC_SECRET is set, include ?secret=... or header X-Sync-Secret: ...

Mappings (edit to match your Notion column names/types)
- scripts/notion_mappings/characters.json
- scripts/notion_mappings/creatures.json (includes Region and Realm)
- scripts/notion_mappings/realms.json
- scripts/notion_mappings/magic.json
- scripts/notion_mappings/plots.json

Local Dev (Windows)
- One‑click script: scripts/start_local.ps1
  - Creates venv, installs deps, starts Flask, runs smoke tests.

Notes
- Updates match on Name; to prevent duplicates if a Name changes, the service stores source.notion_page_id for round‑trip updates.
- Select options are auto‑created on push; views with filters may hide new rows in Notion.
- Do not commit .env (tokens/IDs) to source control.

