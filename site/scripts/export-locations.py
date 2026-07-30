"""
One-off export: snapshot backend/services/locations_service.py's
POPULAR_DESTINATIONS into a static JSON file the Next.js site can read at
build time - Node can't import Python source directly, and Vercel's build
for this site has no Python runtime anyway. Data changes infrequently -
re-run this manually and commit the updated data/locations.json whenever
POPULAR_DESTINATIONS changes; this is a plain static asset, not regenerated
on every build.

Usage:
    cd site
    python scripts/export-locations.py
"""
import json
import os
import sys

BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "backend")
sys.path.insert(0, BACKEND_DIR)

from services.locations_service import POPULAR_DESTINATIONS  # noqa: E402

OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "locations.json")

with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(POPULAR_DESTINATIONS, f, ensure_ascii=False, indent=2)
    f.write("\n")

print(f"Wrote {len(POPULAR_DESTINATIONS)} entries to {OUT_PATH}")
