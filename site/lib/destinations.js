import fs from "fs";
import path from "path";

// backend/data/destination_content.json remains the single source of truth;
// data/destination_content.json here is a synced copy (scripts/sync-content.js).
// Reaching across the package boundary via a process.cwd()-relative "../backend"
// path was tried first and silently produced empty data under Next's parallel
// static-generation workers (they don't inherit the same cwd the top-level
// `next build` process has) - a plain path.join(process.cwd(), "data", ...)
// that never leaves this directory doesn't have that problem.
const CONTENT_PATH = path.join(process.cwd(), "data", "destination_content.json");

// POPULAR_DESTINATIONS is Python source (backend/services/locations_service.py)
// and can't be imported by Node/Vercel's build directly - data/locations.json
// is a committed snapshot of it (see scripts/export-locations.py), re-run
// manually whenever that list changes rather than regenerated on every build.
const LOCATIONS_PATH = path.join(process.cwd(), "data", "locations.json");

let cached = null;

function loadAll() {
  if (cached) return cached;

  const content = JSON.parse(fs.readFileSync(CONTENT_PATH, "utf-8"));
  const locations = JSON.parse(fs.readFileSync(LOCATIONS_PATH, "utf-8"));

  // Joined by name, not slug - POPULAR_DESTINATIONS (locations.json) has no
  // slug field of its own, and every content_content.json name matches a
  // POPULAR_DESTINATIONS name exactly (verified 66/66 when the content was
  // drafted), so name is the reliable shared key. slug remains the stable
  // per-page URL identifier throughout the rest of this app.
  const locationsByName = new Map(locations.map((l) => [l.name, l]));

  cached = content
    .filter((d) => d.content_reviewed === true)
    .map((d) => {
      const loc = locationsByName.get(d.name) || null;
      return {
        slug: d.slug,
        name: d.name,
        description: d.description,
        highlights: d.highlights,
        best_time_to_visit: d.best_time_to_visit,
        needs_verification: d.needs_verification,
        country: loc?.country ?? null,
        type: loc?.type ?? null,
        lat: loc?.lat ?? null,
        lng: loc?.lng ?? null,
        popularity: loc?.popularity ?? null,
      };
    });

  return cached;
}

export function getAllDestinations() {
  return loadAll();
}

export function getDestinationBySlug(slug) {
  return loadAll().find((d) => d.slug === slug) || null;
}

export function getSiteUrl() {
  return process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3001";
}

// The CRA trip planner has no mechanism today for an external URL to
// pre-fill its destination field: TripPlannerPage seeds that field from
// React Router navigation `state` (only settable by in-app navigate()/Link
// calls), never from the URL's query string, and the ProtectedRoute ->
// login -> redirect round trip drops even `search` when reconstructing the
// post-login destination (see LoginPage.jsx). So this links to the plain
// wizard entry point with an empty destination field rather than a
// `?destination=` param that would silently do nothing. Revisit once the
// CRA app gains real query-param pre-fill support.
export function getPlanTripUrl() {
  return process.env.NEXT_PUBLIC_APP_URL || "http://localhost:3000/trip-planner";
}
