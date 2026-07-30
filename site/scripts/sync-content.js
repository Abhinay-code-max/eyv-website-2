// Copies backend/data/destination_content.json into site/data/ so the
// build never reaches across the package boundary via a process.cwd()-
// relative path - that turned out to be unreliable under Next's parallel
// static-generation workers (each apparently doesn't inherit the same cwd
// the top-level `next build` process has), which silently produced empty
// data during static generation instead of an error.
//
// backend/data/destination_content.json remains the single source of
// truth; re-run this manually and commit the result whenever that file
// changes, same convention as scripts/export-locations.py for locations.json.
//
// Usage: node scripts/sync-content.js
const fs = require("fs");
const path = require("path");

const SRC = path.join(__dirname, "..", "..", "backend", "data", "destination_content.json");
const DEST = path.join(__dirname, "..", "data", "destination_content.json");

const raw = fs.readFileSync(SRC, "utf-8");
const parsed = JSON.parse(raw); // fail fast if the source isn't valid JSON
fs.writeFileSync(DEST, JSON.stringify(parsed, null, 2) + "\n", "utf-8");

console.log(`Synced ${parsed.length} entries from ${SRC} to ${DEST}`);
