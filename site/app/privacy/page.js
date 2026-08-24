/*
 * DISCLAIMER / LEGAL NOTICE:
 * This is a FIRST DRAFT generated for informational and compliance scaffolding purposes.
 * It must be reviewed, customized, and finalized by qualified legal counsel prior to
 * relying on it for regulatory compliance (GDPR, CCPA, DPDP, etc.).
 */

import Link from "next/link";

export const metadata = {
  title: "Privacy Policy",
  description:
    "Privacy Policy for EYV (Enjoy Your Vacation) — Learn how we handle your personal data, Google OAuth authentication, travel wallet documents, and third-party travel APIs.",
};

export default function PrivacyPolicyPage() {
  return (
    <main className="wrap">
      <Link href="/" className="back-link">
        ← Back to Destination Guides
      </Link>

      <p className="eyebrow">Legal & Compliance</p>
      <h1>Privacy Policy</h1>
      <p className="best-time">Last updated: August 17, 2026 · Effective Date: August 17, 2026</p>

      {/* Disclaimer Banner */}
      <div className="verify-note" style={{ marginBottom: "2rem" }}>
        <p className="verify-title">Notice: First Draft Scaffolding</p>
        <p style={{ margin: 0, fontSize: "0.9rem", color: "var(--ink)" }}>
          This document is a draft privacy policy for EYV (Enjoy Your Vacation). It outlines our data architecture and
          third-party processing integrations. It requires formal legal review before being relied upon for legal compliance.
        </p>
      </div>

      <div className="description" style={{ maxWidth: "100%", marginBottom: "2.5rem" }}>
        <p>
          At <strong>EYV (Enjoy Your Vacation)</strong> ("EYV", "we", "our", or "us"), accessible via{" "}
          <a href="https://eyv.travel">eyv.travel</a>, we are committed to respecting your privacy and protecting the
          personal travel information and wallet documents you entrust to us.
        </p>
      </div>

      <section style={{ marginBottom: "2rem" }}>
        <h2>1. Information We Collect</h2>
        <p style={{ color: "var(--ink-muted)", fontSize: "0.95rem" }}>
          We collect and process the following categories of data when you utilize our platform:
        </p>
        <ul className="highlights" style={{ marginTop: "0.75rem" }}>
          <li>
            <strong>Account Data (Google OAuth):</strong> Verified Google user ID, name, email address, and profile picture. We never access or store your Google password.
          </li>
          <li>
            <strong>Travel Wallet Documents:</strong> Boarding passes, tickets, hotel vouchers, and identity documents uploaded by you, securely stored in isolated database storage (MongoDB GridFS) and served via short-lived, signed URLs (180-second TTL).
          </li>
          <li>
            <strong>Trip Inputs & Preferences:</strong> Destination choices, departure origins, travel dates, passenger group compositions, budget tiers, travel mode preferences (flights, trains, cruises), and AI chat messages.
          </li>
          <li>
            <strong>Payment & Billing Data:</strong> Transaction references, subscription statuses, and customer tokens. Payments are processed directly through PCI-DSS certified gateways (Stripe or regional processors); EYV never retains full credit card details.
          </li>
          <li>
            <strong>Technical Log Data:</strong> Client IP addresses (for rate-limiting and security verification), browser user agent strings, and secure session tokens (<code style={{ fontSize: "0.85rem", background: "var(--surface)", padding: "0.1rem 0.3rem", borderRadius: "4px" }}>session_token</code>) stored with SHA-256 hashing and a 7-day TTL.
          </li>
        </ul>
      </section>

      <section style={{ marginBottom: "2rem" }}>
        <h2>2. How We Use Your Information</h2>
        <ul className="highlights">
          <li>
            <strong>AI Travel Planning:</strong> Generating multi-day itineraries and budget-tiered recommendations tailored to your inputs.
          </li>
          <li>
            <strong>Booking Aggregation & Search:</strong> Querying real-time airline and hotel inventory via partner travel APIs.
          </li>
          <li>
            <strong>Rewards & Loyalty Tracking:</strong> Calculating EYV Rewards points and tier perks based on confirmed bookings.
          </li>
          <li>
            <strong>Security & Fraud Prevention:</strong> Authenticating sessions, preventing automated scraping, and enforcing fair-use rate limits.
          </li>
        </ul>
      </section>

      <section style={{ marginBottom: "2rem" }}>
        <h2>3. Third-Party Service Providers & Subprocessors</h2>
        <p style={{ color: "var(--ink-muted)", fontSize: "0.95rem", marginBottom: "1rem" }}>
          EYV collaborates with select third-party service providers to deliver travel planning and booking infrastructure:
        </p>
        <div style={{ overflowX: "auto", marginBottom: "1rem" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem", textAlign: "left" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)", background: "var(--surface)" }}>
                <th style={{ padding: "0.75rem", color: "var(--ink)" }}>Provider</th>
                <th style={{ padding: "0.75rem", color: "var(--ink)" }}>Function</th>
                <th style={{ padding: "0.75rem", color: "var(--ink)" }}>Data Shared</th>
              </tr>
            </thead>
            <tbody style={{ color: "var(--ink-muted)" }}>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "0.75rem", fontWeight: 600, color: "var(--ink)" }}>Google OAuth & Gemini API</td>
                <td style={{ padding: "0.75rem" }}>Authentication & AI itinerary generation</td>
                <td style={{ padding: "0.75rem" }}>Profile ID, trip prompt criteria</td>
              </tr>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "0.75rem", fontWeight: 600, color: "var(--ink)" }}>Stripe (or Regional Processor)</td>
                <td style={{ padding: "0.75rem" }}>Payment checkout & subscription billing</td>
                <td style={{ padding: "0.75rem" }}>Customer email, checkout line items</td>
              </tr>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "0.75rem", fontWeight: 600, color: "var(--ink)" }}>Ignav API</td>
                <td style={{ padding: "0.75rem" }}>Flight search & fare estimation</td>
                <td style={{ padding: "0.75rem" }}>Origin/destination airport, dates</td>
              </tr>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "0.75rem", fontWeight: 600, color: "var(--ink)" }}>SerpApi</td>
                <td style={{ padding: "0.75rem" }}>Hotel search & live pricing</td>
                <td style={{ padding: "0.75rem" }}>Destination city, check-in dates</td>
              </tr>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "0.75rem", fontWeight: 600, color: "var(--ink)" }}>Sentry</td>
                <td style={{ padding: "0.75rem" }}>Error logging & telemetry</td>
                <td style={{ padding: "0.75rem" }}>Sanitized system crash logs</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section style={{ marginBottom: "2rem" }}>
        <h2>4. Data Retention, User Rights & Deletion</h2>
        <p style={{ color: "var(--ink-muted)", fontSize: "0.95rem", marginBottom: "0.75rem" }}>
          You have full authority to manage your personal information:
        </p>
        <ul className="highlights">
          <li><strong>Document Deletion:</strong> You can delete any uploaded wallet item instantly via the wallet interface.</li>
          <li><strong>Account Erasure & Export:</strong> You may request an export or complete deletion of your account and trip records by contacting support.</li>
          <li><strong>Session Invalidation:</strong> Signing out immediately revokes your active server-side session token.</li>
        </ul>
      </section>

      <section style={{ marginBottom: "2rem" }}>
        <h2>5. Contact Information</h2>
        <p style={{ color: "var(--ink-muted)", fontSize: "0.95rem" }}>
          If you have questions or privacy inquiries, please contact our team at{" "}
          <a href="mailto:support@eyv.travel">support@eyv.travel</a>.
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
