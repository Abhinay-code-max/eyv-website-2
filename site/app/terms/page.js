/*
 * DISCLAIMER / LEGAL NOTICE:
 * This is a FIRST DRAFT generated for informational and compliance scaffolding purposes.
 * It must be reviewed, customized, and finalized by qualified legal counsel prior to
 * relying on it for regulatory compliance.
 */

import Link from "next/link";

export const metadata = {
  title: "Terms of Service",
  description:
    "Terms of Service for EYV (Enjoy Your Vacation) — User agreement, AI itinerary advisory terms, booking conditions, and subscription rules.",
};

export default function TermsOfServicePage() {
  return (
    <main className="wrap">
      <Link href="/" className="back-link">
        ← Back to Destination Guides
      </Link>

      <p className="eyebrow">Legal & Compliance</p>
      <h1>Terms of Service</h1>
      <p className="best-time">Last updated: August 17, 2026 · Effective Date: August 17, 2026</p>

      {/* Disclaimer Banner */}
      <div className="verify-note" style={{ marginBottom: "2rem" }}>
        <p className="verify-title">Notice: First Draft Scaffolding</p>
        <p style={{ margin: 0, fontSize: "0.9rem", color: "var(--ink)" }}>
          This document is a draft Terms of Service for EYV (Enjoy Your Vacation). It sets out operational rules, AI
          disclaimers, and subscription terms. It is subject to formal review and finalization by legal counsel.
        </p>
      </div>

      <div className="description" style={{ maxWidth: "100%", marginBottom: "2.5rem" }}>
        <p>
          By accessing or using the services, destination guides, APIs, or applications provided by{" "}
          <strong>EYV (Enjoy Your Vacation)</strong> ("EYV", "we", "us", or "our"), you agree to be bound by these Terms of Service.
        </p>
      </div>

      <section style={{ marginBottom: "2rem" }}>
        <h2>1. Services Provided</h2>
        <p style={{ color: "var(--ink-muted)", fontSize: "0.95rem" }}>
          EYV provides an intelligent travel aggregation and planning platform featuring:
        </p>
        <ul className="highlights" style={{ marginTop: "0.75rem" }}>
          <li>AI-assisted multi-day travel itinerary generation tailored to destination, dates, and budget.</li>
          <li>Flight inventory searches via Ignav and accommodation aggregation via SerpApi.</li>
          <li>A secure, encrypted Travel Wallet for storing boarding passes, booking vouchers, and itineraries.</li>
          <li>An integrated loyalty rewards program with tier benefits and discounts.</li>
          <li>Premium subscription memberships offering priority generation and enhanced features.</li>
        </ul>
      </section>

      <section style={{ marginBottom: "2rem" }}>
        <h2>2. AI Itinerary Generation Disclaimer</h2>
        <div className="verify-note" style={{ background: "var(--surface)", border: "1px solid var(--border)", marginBottom: "1rem" }}>
          <p className="verify-title" style={{ color: "var(--accent)" }}>Advisory Nature of AI Outputs</p>
          <p style={{ margin: 0, fontSize: "0.9rem", color: "var(--ink)" }}>
            Travel itineraries, activity timings, cost estimates (including estimated cruise fares or train schedules),
            visa advisories, and local tips are generated using Google Gemini generative AI and live third-party data feeds.
          </p>
        </div>
        <ul className="highlights">
          <li>All AI-generated itineraries are strictly advisory. Travelers are solely responsible for verifying passport validity (minimum 6 months validity), visa requirements, airline check-in cutoff times, health mandates, and operating hours.</li>
          <li>EYV does not guarantee the availability, price stability, or operating status of third-party attractions, airlines, or accommodations.</li>
        </ul>
      </section>

      <section style={{ marginBottom: "2rem" }}>
        <h2>3. Bookings, Payments & Subscriptions</h2>
        <ul className="highlights">
          <li>
            <strong>Third-Party Fulfillment:</strong> Airline and hotel bookings are governed by the respective terms, fare conditions, and cancellation policies of each operating carrier or hotel property.
          </li>
          <li>
            <strong>Subscription Billing:</strong> EYV Premium is billed automatically on a recurring monthly or annual basis. Subscriptions may be cancelled at any time via your account dashboard; cancellations take effect at the conclusion of the active billing period (<code style={{ fontSize: "0.85rem", background: "var(--surface)", padding: "0.1rem 0.3rem", borderRadius: "4px" }}>cancel_at_period_end</code>).
          </li>
          <li>
            <strong>Reward Points:</strong> EYV Reward points have no cash surrender value and are non-transferable. Points reserved during checkout will be returned if a checkout session expires or fails.
          </li>
        </ul>
      </section>

      <section style={{ marginBottom: "2rem" }}>
        <h2>4. Prohibited Uses</h2>
        <p style={{ color: "var(--ink-muted)", fontSize: "0.95rem", marginBottom: "0.75rem" }}>
          Users agree not to:
        </p>
        <ul className="highlights">
          <li>Engage in automated scraping or bulk harvesting of destination content, guide data, or flight inventory.</li>
          <li>Attempt to bypass rate limits, authentication cookies, or security controls.</li>
          <li>Upload malicious, fraudulent, or infringing documents to the Travel Wallet.</li>
        </ul>
      </section>

      <section style={{ marginBottom: "2rem" }}>
        <h2>5. Limitation of Liability</h2>
        <p style={{ color: "var(--ink-muted)", fontSize: "0.95rem" }}>
          To the maximum extent permitted by law, EYV provides its platform "AS IS" and is not liable for indirect,
          consequential, or travel disruption damages, including airline delays, weather emergencies, or government entry refusals.
        </p>
      </section>

      <section style={{ marginBottom: "2rem" }}>
        <h2>6. Contact Us</h2>
        <p style={{ color: "var(--ink-muted)", fontSize: "0.95rem" }}>
          Questions about these Terms should be sent to <a href="mailto:support@eyv.travel">support@eyv.travel</a>.
        </p>
      </section>

      <footer className="page-footer">
        <p className="meta">© 2026 EYV. Enjoy Your Vacation.</p>
        <div style={{ display: "flex", gap: "1rem", fontSize: "0.85rem" }}>
          <Link href="/privacy">Privacy</Link>
          <Link href="/terms">Terms</Link>
          <Link href="/refund-policy">Refund Policy</Link>
        </div>
      </footer>
    </main>
  );
}
