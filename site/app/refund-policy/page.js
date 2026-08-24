/*
 * DISCLAIMER / LEGAL NOTICE:
 * This is a FIRST DRAFT generated for informational and compliance scaffolding purposes.
 * It must be reviewed, customized, and finalized by qualified legal counsel prior to
 * relying on it for regulatory compliance.
 */

import Link from "next/link";

export const metadata = {
  title: "Refund & Cancellation Policy",
  description:
    "Refund and Cancellation Policy for EYV (Enjoy Your Vacation) — Detailed rules for flight & hotel booking cancellations, support-assisted refund flows, and subscription billing terms.",
};

export default function RefundPolicyPage() {
  return (
    <main className="wrap">
      <Link href="/" className="back-link">
        ← Back to Destination Guides
      </Link>

      <p className="eyebrow">Legal & Compliance</p>
      <h1>Refund & Cancellation Policy</h1>
      <p className="best-time">Last updated: August 17, 2026 · Effective Date: August 17, 2026</p>

      {/* Disclaimer Banner */}
      <div className="verify-note" style={{ marginBottom: "2rem" }}>
        <p className="verify-title">Notice: First Draft Scaffolding</p>
        <p style={{ margin: 0, fontSize: "0.9rem", color: "var(--ink)" }}>
          This document is a draft Refund and Cancellation Policy for EYV (Enjoy Your Vacation). It outlines our
          current cancellation logic and refund procedures. It requires formal legal review and approval before reliance.
        </p>
      </div>

      <div className="description" style={{ maxWidth: "100%", marginBottom: "2.5rem" }}>
        <p>
          At <strong>EYV (Enjoy Your Vacation)</strong>, we prioritize clarity regarding bookings, cancellations, and
          refunds. This policy explains how cancellations and refunds are handled for both trip reservations and EYV Premium
          subscriptions.
        </p>
      </div>

      <section style={{ marginBottom: "2rem" }}>
        <h2>1. Flight & Hotel Bookings Cancellation</h2>
        <div style={{ display: "grid", gap: "1rem", marginTop: "1rem" }}>
          <div style={{ border: "1px solid var(--border)", background: "var(--surface)", borderRadius: "10px", padding: "1.25rem" }}>
            <h3 style={{ margin: "0 0 0.5rem", fontSize: "1.05rem" }}>A. Unpaid & Draft Bookings (Pre-Payment)</h3>
            <p style={{ margin: 0, color: "var(--ink-muted)", fontSize: "0.9rem", lineHeight: 1.5 }}>
              Any booking in a draft or pending payment status (<code style={{ fontSize: "0.85rem", background: "var(--bg)", padding: "0.1rem 0.3rem", borderRadius: "4px" }}>draft</code>, <code style={{ fontSize: "0.85rem", background: "var(--bg)", padding: "0.1rem 0.3rem", borderRadius: "4px" }}>pending</code>, <code style={{ fontSize: "0.85rem", background: "var(--bg)", padding: "0.1rem 0.3rem", borderRadius: "4px" }}>pending_payment</code>)
              can be cancelled immediately with zero cancellation fee from the user dashboard. If loyalty points were reserved at checkout,
              they are immediately refunded back to your loyalty balance upon cancellation or checkout expiration.
            </p>
          </div>

          <div style={{ border: "1px solid var(--border)", background: "var(--surface)", borderRadius: "10px", padding: "1.25rem" }}>
            <h3 style={{ margin: "0 0 0.5rem", fontSize: "1.05rem" }}>B. Paid & Confirmed Bookings (Post-Payment)</h3>
            <p style={{ margin: "0 0 0.75rem", color: "var(--ink-muted)", fontSize: "0.9rem", lineHeight: 1.5 }}>
              Once a booking is paid and confirmed, reservations are locked in with the operating airline or property.
              Because carriers enforce separate non-refundable fare rules:
            </p>
            <ul className="highlights" style={{ fontSize: "0.9rem", color: "var(--ink)" }}>
              <li>Direct 1-click cancellation of paid bookings is not available in the self-service dashboard.</li>
              <li>
                <strong>To cancel a confirmed booking:</strong> Please contact our support team at{" "}
                <a href="mailto:support@eyv.travel">support@eyv.travel</a> with your Booking Reference ID.
              </li>
              <li>
                Our support team will process your cancellation with the operating airline or hotel and credit any applicable
                fare refunds according to the provider's fare rules.
              </li>
            </ul>
          </div>
        </div>
      </section>

      <section style={{ marginBottom: "2rem" }}>
        <h2>2. EYV Premium Subscriptions</h2>
        <ul className="highlights">
          <li>
            <strong>Cancellation Anytime:</strong> You can cancel your Premium membership at any time from your account settings or the Stripe billing portal.
          </li>
          <li>
            <strong>Cancel-at-Period-End:</strong> Cancellations take effect at the end of the current billing cycle (<code style={{ fontSize: "0.85rem", background: "var(--surface)", padding: "0.1rem 0.3rem", borderRadius: "4px" }}>cancel_at_period_end</code>). You retain full access to Premium perks until that date, and no future charges will occur.
          </li>
          <li>
            <strong>Refund Policy:</strong> Subscription fees are generally non-refundable once billed. If you believe a billing error occurred, please contact support within 14 days of the charge.
          </li>
        </ul>
      </section>

      <section style={{ marginBottom: "2rem" }}>
        <h2>3. Refund Processing & Bank Timelines</h2>
        <ul className="highlights">
          <li>Approved refunds are returned directly to the original payment method used during checkout.</li>
          <li>Refunds typically appear on your banking statement within 5 to 10 business days, depending on your financial institution.</li>
        </ul>
      </section>

      <section style={{ marginBottom: "2rem" }}>
        <h2>4. Contact Support</h2>
        <p style={{ color: "var(--ink-muted)", fontSize: "0.95rem" }}>
          For cancellation assistance, refund inquiries, or receipt requests, reach our team directly at{" "}
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
