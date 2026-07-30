import Link from "next/link";
import { notFound } from "next/navigation";
import { getAllDestinations, getDestinationBySlug, getSiteUrl, getPlanTripUrl } from "../../../lib/destinations";

// Only the statically generated slugs below are ever served - an unlisted
// or excluded slug (e.g. hawa-mahal-jaipur, held back for its unresolved
// fee conflict) 404s instead of falling back to on-demand rendering.
export const dynamicParams = false;

export function generateStaticParams() {
  return getAllDestinations().map((d) => ({ slug: d.slug }));
}

function truncate(text, max) {
  if (text.length <= max) return text;
  return text.slice(0, max - 1).trimEnd() + "…";
}

export async function generateMetadata({ params }) {
  // Next's dynamic route `params` is a Promise, not a plain object - awaiting
  // it here is required, not optional; destructuring it synchronously
  // silently resolved to undefined in testing, so every generated page
  // ended up with slug=undefined -> no matching destination -> notFound().
  const { slug } = await params;
  const dest = getDestinationBySlug(slug);
  if (!dest) return {};

  const title = `${dest.name} Travel Guide${dest.country ? ` - ${dest.country}` : ""}`;
  const description = truncate(dest.description, 155);
  const url = `${getSiteUrl()}/destinations/${dest.slug}`;

  return {
    title,
    description,
    alternates: { canonical: url },
    openGraph: {
      title,
      description,
      url,
      type: "website",
      siteName: "EYV Travel",
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
    },
  };
}

export default async function DestinationPage({ params }) {
  const { slug } = await params;
  const dest = getDestinationBySlug(slug);
  if (!dest) notFound();

  const siteUrl = getSiteUrl();
  const pageUrl = `${siteUrl}/destinations/${dest.slug}`;
  const ctaUrl = getPlanTripUrl();

  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "TouristDestination",
    name: dest.name,
    description: dest.description,
    url: pageUrl,
    ...(dest.lat != null && dest.lng != null
      ? { geo: { "@type": "GeoCoordinates", latitude: dest.lat, longitude: dest.lng } }
      : {}),
    includesAttraction: dest.highlights.map((h) => ({
      "@type": "TouristAttraction",
      name: h,
    })),
  };

  return (
    <main className="wrap">
      {/* eslint-disable-next-line react/no-danger */}
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />

      <Link href="/" className="back-link">
        ← All destinations
      </Link>

      <p className="eyebrow">
        {dest.country}
        {dest.type ? ` · ${dest.type}` : ""}
      </p>
      <h1>{dest.name}</h1>
      <p className="best-time">Best time to visit: {dest.best_time_to_visit}</p>
      <a className="cta" href={ctaUrl}>
        Plan a trip here
      </a>

      <p className="description" style={{ marginTop: "1.75rem" }}>
        {dest.description}
      </p>

      <h2>Highlights</h2>
      <ul className="highlights">
        {dest.highlights.map((h) => (
          <li key={h}>{h}</li>
        ))}
      </ul>

      {dest.needs_verification.length > 0 && (
        <aside className="verify-note" role="note" aria-label="Details worth confirming before you go">
          <p className="verify-title">Worth double-checking before you go</p>
          <ul>
            {dest.needs_verification.map((v) => (
              <li key={v}>{v}</li>
            ))}
          </ul>
        </aside>
      )}

      <footer className="page-footer">
        <p className="meta">
          {dest.lat != null && dest.lng != null
            ? `${dest.lat.toFixed(4)}, ${dest.lng.toFixed(4)}`
            : null}
        </p>
        <a className="cta" href={ctaUrl}>
          Plan a trip to {dest.name}
        </a>
      </footer>
    </main>
  );
}
