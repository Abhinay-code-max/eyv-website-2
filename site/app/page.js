import Link from "next/link";
import { getAllDestinations } from "../lib/destinations";

export const metadata = {
  title: "Destination Guides",
  description:
    "Real, reviewed travel guides for 65 destinations across India and worldwide - highlights, best time to visit, and honest notes on anything worth double-checking before you go.",
};

export default function HomePage() {
  const destinations = getAllDestinations().slice().sort((a, b) => (b.popularity ?? 0) - (a.popularity ?? 0));

  return (
    <main className="wrap">
      <p className="eyebrow">EYV Travel</p>
      <h1>Destination guides</h1>
      <p className="description">
        {destinations.length} reviewed destination guides across India and worldwide. Each one links out
        to the EYV trip planner when you're ready to build a real itinerary.
      </p>
      <h2>All destinations</h2>
      <div className="dest-grid">
        {destinations.map((d) => (
          <Link key={d.slug} href={`/destinations/${d.slug}`} className="dest-card">
            <p className="dest-name">{d.name}</p>
            <p className="dest-meta">{d.country}{d.type ? ` · ${d.type}` : ""}</p>
          </Link>
        ))}
      </div>

      <footer className="page-footer">
        <p className="meta">© 2026 EYV. Enjoy Your Vacation — We Plan Everything.</p>
        <div style={{ display: "flex", gap: "1.25rem", fontSize: "0.85rem" }}>
          <Link href="/privacy">Privacy</Link>
          <Link href="/terms">Terms</Link>
          <Link href="/refund-policy">Refund Policy</Link>
        </div>
      </footer>
    </main>
  );
}
