/*
 * DISCLAIMER / LEGAL NOTICE:
 * This is a FIRST DRAFT generated for informational and compliance scaffolding purposes.
 * It must be reviewed, customized, and finalized by qualified legal counsel prior to
 * relying on it for regulatory compliance (GDPR, CCPA, DPDP, etc.).
 */

import React from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ArrowLeft, Shield, Lock, Eye, Server, RefreshCw, Mail, AlertTriangle, FileText } from 'lucide-react';
import EYVLogo from '../components/EYVLogo';
import { LEGAL } from '../constants/testIds';
import { Button } from '../components/ui/button';

const PrivacyPolicyPage = () => {
  const navigate = useNavigate();

  return (
    <div data-testid={LEGAL?.privacyPage || 'privacy-policy-page'} className="min-h-screen bg-[#FDFBF7] text-[#1C1917]">
      {/* ── Top Navigation Header ── */}
      <header className="sticky top-0 z-30 bg-[#FDFBF7]/90 backdrop-blur-md border-b border-[#E7E5E4] px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate(-1)}
              className="text-[#57534E] hover:text-[#1C1917] hover:bg-[#F5F2EB] rounded-full p-2"
              aria-label="Go back"
            >
              <ArrowLeft size={20} />
            </Button>
            <Link to="/" className="inline-block">
              <EYVLogo size="small" />
            </Link>
          </div>
          <Link
            to="/login"
            className="text-sm font-medium text-[#C47245] hover:text-[#A85D38] transition-colors"
          >
            Sign In
          </Link>
        </div>
      </header>

      {/* ── Main Content Container ── */}
      <main className="max-w-4xl mx-auto px-6 py-12">
        {/* Legal Review Draft Banner */}
        <div className="mb-8 p-4 rounded-2xl bg-[#FEF3EC] border border-[#F5C7A9] flex items-start gap-3 text-sm text-[#A85D38]">
          <AlertTriangle size={20} className="shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold mb-0.5">Legal Notice & Disclaimer</p>
            <p className="text-xs text-[#8A4826] leading-relaxed">
              This document is a draft privacy policy for EYV (Enjoy Your Vacation). It describes our current technical
              architecture and data practices. It is subject to ongoing updates and requires formal review by qualified legal counsel.
            </p>
          </div>
        </div>

        {/* Page Heading */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="mb-10"
        >
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-[#C47245] font-semibold mb-2">
            <Shield size={16} />
            <span>Transparency & Privacy</span>
          </div>
          <h1
            className="text-4xl md:text-5xl font-semibold text-[#1C1917] mb-4 tracking-tight"
            style={{ fontFamily: 'Cormorant Garamond, serif' }}
          >
            Privacy Policy
          </h1>
          <p className="text-sm text-[#57534E]">
            Last updated: August 17, 2026 · Effective Date: August 17, 2026
          </p>
        </motion.div>

        {/* Policy Body */}
        <div className="space-y-10 text-[#44403C] leading-relaxed text-[15px]">
          {/* Section 1: Introduction */}
          <section className="bg-white p-8 rounded-3xl border border-[#E7E5E4] shadow-sm">
            <h2
              className="text-2xl font-semibold text-[#1C1917] mb-4"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}
            >
              1. Introduction & Overview
            </h2>
            <p className="mb-4">
              Welcome to <strong>EYV (Enjoy Your Vacation)</strong> ("EYV", "we", "our", or "us"). We are committed
              to protecting your personal privacy and safeguarding the travel and identity data you share with us.
            </p>
            <p>
              This Privacy Policy explains what personal information we collect when you use our website (
              <a href="https://eyv.travel" className="text-[#C47245] underline">eyv.travel</a>), our web applications,
              APIs, and related travel-planning services (collectively, the "Services"), how we use that data, the
              third-party processors we work with, and your rights regarding your personal information.
            </p>
          </section>

          {/* Section 2: Information We Collect */}
          <section className="bg-white p-8 rounded-3xl border border-[#E7E5E4] shadow-sm">
            <h2
              className="text-2xl font-semibold text-[#1C1917] mb-4"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}
            >
              2. Information We Collect
            </h2>
            <p className="mb-4">
              We collect information in three categories depending on how you interact with our platform:
            </p>
            <div className="space-y-4">
              <div className="p-4 rounded-2xl bg-[#FAF8F5] border border-[#E7E5E4]">
                <h3 className="font-semibold text-[#1C1917] mb-1 flex items-center gap-2">
                  <Lock size={16} className="text-[#C47245]" />
                  A. Account & Authentication Data (Google OAuth)
                </h3>
                <p className="text-sm text-[#57534E]">
                  When you sign in via Google OAuth, we receive your verified Google User ID, full name, email address,
                  and profile avatar URL. We do not receive or store your Google account password.
                </p>
              </div>

              <div className="p-4 rounded-2xl bg-[#FAF8F5] border border-[#E7E5E4]">
                <h3 className="font-semibold text-[#1C1917] mb-1 flex items-center gap-2">
                  <FileText size={16} className="text-[#C47245]" />
                  B. Travel Wallet Documents (Encrypted GridFS Storage)
                </h3>
                <p className="text-sm text-[#57534E]">
                  If you upload travel items to your personal Travel Wallet (e.g., flight boarding passes, hotel reservation
                  vouchers, tickets, passport scans, or identity documents), the files are stored in our secure, isolated database
                  storage (MongoDB GridFS). Downloads are protected via HMAC-signed, time-limited URLs (180-second expiry).
                </p>
              </div>

              <div className="p-4 rounded-2xl bg-[#FAF8F5] border border-[#E7E5E4]">
                <h3 className="font-semibold text-[#1C1917] mb-1 flex items-center gap-2">
                  <Eye size={16} className="text-[#C47245]" />
                  C. Trip Planning, Preferences & Prompts
                </h3>
                <p className="text-sm text-[#57534E]">
                  We store the travel destinations, departure points, travel dates, passenger group compositions (adults,
                  children, seniors), budget preferences, travel modes (flights, trains, cruises), and interactive chat
                  prompts you provide to generate your custom itineraries.
                </p>
              </div>

              <div className="p-4 rounded-2xl bg-[#FAF8F5] border border-[#E7E5E4]">
                <h3 className="font-semibold text-[#1C1917] mb-1 flex items-center gap-2">
                  <Server size={16} className="text-[#C47245]" />
                  D. Payment & Billing Data
                </h3>
                <p className="text-sm text-[#57534E]">
                  Payments for bookings and Premium subscriptions are processed securely by external, PCI-DSS certified payment
                  gateways (e.g., Stripe or regional processors). EYV stores payment transaction references, customer IDs, and
                  subscription statuses. We never store or handle raw credit card numbers or CVV codes on our servers.
                </p>
              </div>
            </div>
          </section>

          {/* Section 3: How We Use Your Information */}
          <section className="bg-white p-8 rounded-3xl border border-[#E7E5E4] shadow-sm">
            <h2
              className="text-2xl font-semibold text-[#1C1917] mb-4"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}
            >
              3. How We Use Your Information
            </h2>
            <ul className="list-disc pl-5 space-y-2 text-[#57534E]">
              <li><strong>Itinerary Generation:</strong> To generate AI-powered multi-tier travel plans (Budget, Standard, Luxury) matching your travel criteria.</li>
              <li><strong>Travel Booking Coordination:</strong> To search and coordinate flight and hotel inventory via our partner APIs.</li>
              <li><strong>Rewards & Loyalty:</strong> To calculate, award, and track your EYV Rewards points, tier progressions, and redemption discounts.</li>
              <li><strong>Security & Abuse Prevention:</strong> To authenticate user sessions, enforce API rate limits, prevent fraudulent transactions, and protect our infrastructure.</li>
              <li><strong>Customer Support:</strong> To assist you with booking modifications, refund requests, and technical troubleshooting.</li>
            </ul>
          </section>

          {/* Section 4: Third-Party Service Providers */}
          <section className="bg-white p-8 rounded-3xl border border-[#E7E5E4] shadow-sm">
            <h2
              className="text-2xl font-semibold text-[#1C1917] mb-4"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}
            >
              4. Third-Party Service Providers & Subprocessors
            </h2>
            <p className="mb-4">
              To deliver our services, EYV integrates with trusted third-party providers. We only disclose the minimum data
              necessary for each provider to perform their specific function:
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm border-collapse">
                <thead>
                  <tr className="border-b border-[#E7E5E4] text-[#1C1917] bg-[#FAF8F5]">
                    <th className="py-3 px-4 font-semibold">Service Provider</th>
                    <th className="py-3 px-4 font-semibold">Purpose</th>
                    <th className="py-3 px-4 font-semibold">Data Shared</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#E7E5E4] text-[#57534E]">
                  <tr>
                    <td className="py-3 px-4 font-medium text-[#1C1917]">Google OAuth & Gemini API</td>
                    <td className="py-3 px-4">User authentication and AI itinerary generation</td>
                    <td className="py-3 px-4">OAuth profile token, trip planning prompt parameters</td>
                  </tr>
                  <tr>
                    <td className="py-3 px-4 font-medium text-[#1C1917]">Stripe (or Regional Gateway)</td>
                    <td className="py-3 px-4">Payment processing and subscription billing</td>
                    <td className="py-3 px-4">Checkout line items, customer email, billing token</td>
                  </tr>
                  <tr>
                    <td className="py-3 px-4 font-medium text-[#1C1917]">Ignav API</td>
                    <td className="py-3 px-4">Real-time airline flight searches and schedule data</td>
                    <td className="py-3 px-4">Origin/destination airports, flight dates, passenger count</td>
                  </tr>
                  <tr>
                    <td className="py-3 px-4 font-medium text-[#1C1917]">SerpApi</td>
                    <td className="py-3 px-4">Hotel pricing and accommodation aggregation</td>
                    <td className="py-3 px-4">Destination query, check-in and check-out dates</td>
                  </tr>
                  <tr>
                    <td className="py-3 px-4 font-medium text-[#1C1917]">Sentry</td>
                    <td className="py-3 px-4">Error logging, diagnostics and performance monitoring</td>
                    <td className="py-3 px-4">Sanitized application crash telemetry and trace data</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          {/* Section 5: Cookies & Sessions */}
          <section className="bg-white p-8 rounded-3xl border border-[#E7E5E4] shadow-sm">
            <h2
              className="text-2xl font-semibold text-[#1C1917] mb-4"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}
            >
              5. Cookies & Session Management
            </h2>
            <p className="mb-3">
              EYV uses strictly necessary session cookies (<code className="bg-[#FAF8F5] px-2 py-0.5 rounded text-xs border border-[#E7E5E4]">session_token</code>)
              to maintain your authenticated state.
            </p>
            <ul className="list-disc pl-5 space-y-2 text-[#57534E]">
              <li>Cookies are transmitted with <code className="text-xs">HttpOnly</code>, <code className="text-xs">SameSite=Lax</code>, and <code className="text-xs">Secure</code> flags.</li>
              <li>Session tokens are stored using SHA-256 cryptographic hashing with a 7-day automatic time-to-live (TTL).</li>
              <li>You can log out at any time to immediately revoke and destroy your active server-side session.</li>
            </ul>
          </section>

          {/* Section 6: Data Retention & User Rights */}
          <section className="bg-white p-8 rounded-3xl border border-[#E7E5E4] shadow-sm">
            <h2
              className="text-2xl font-semibold text-[#1C1917] mb-4"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}
            >
              6. Data Retention, User Rights & Deletion
            </h2>
            <p className="mb-4">
              You maintain ownership of your personal data. Depending on your jurisdiction (such as GDPR, CCPA, or DPDP),
              you possess the following rights:
            </p>
            <ul className="list-disc pl-5 space-y-2 text-[#57534E] mb-6">
              <li><strong>Right to Access:</strong> Request a copy of your stored personal information and generated trips.</li>
              <li><strong>Right to Deletion:</strong> Delete individual items from your Travel Wallet or request complete account erasure.</li>
              <li><strong>Right to Rectification:</strong> Update your profile or booking information where permissible.</li>
              <li><strong>Right to Withdraw Consent:</strong> Revoke OAuth access or cancel recurring subscriptions at any time.</li>
            </ul>
            <div className="p-4 rounded-2xl bg-[#FAF8F5] border border-[#E7E5E4] flex items-center justify-between">
              <div>
                <p className="font-medium text-[#1C1917]">Need to request data export or deletion?</p>
                <p className="text-xs text-[#57534E]">Contact our privacy team directly.</p>
              </div>
              <a
                href="mailto:support@eyv.travel?subject=Privacy%20Data%20Request"
                className="inline-flex items-center gap-1.5 bg-[#C47245] text-white px-4 py-2 rounded-full text-xs font-medium hover:bg-[#A85D38] transition-colors"
              >
                <Mail size={14} />
                Contact Privacy Team
              </a>
            </div>
          </section>

          {/* Section 7: Contact Us */}
          <section className="bg-[#FAF8F5] p-8 rounded-3xl border border-[#E7E5E4]">
            <h2
              className="text-2xl font-semibold text-[#1C1917] mb-3"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}
            >
              7. Contact & Inquiries
            </h2>
            <p className="text-sm text-[#57534E] mb-4">
              If you have any questions or feedback regarding this Privacy Policy or our security practices, please reach out to us:
            </p>
            <div className="text-sm text-[#1C1917] space-y-1">
              <p><strong>EYV Travel Technologies</strong></p>
              <p>Email: <a href="mailto:support@eyv.travel" className="text-[#C47245] underline">support@eyv.travel</a></p>
              <p>Web: <a href="https://eyv.travel" className="text-[#C47245] underline">https://eyv.travel</a></p>
            </div>
          </section>
        </div>
      </main>

      {/* ── Footer ── */}
      <footer className="py-8 px-6 bg-[#FDFBF7] border-t border-[#E7E5E4] mt-16 text-center text-xs text-[#57534E]">
        <div className="max-w-4xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
          <p>© 2026 EYV. Enjoy Your Vacation — We Plan Everything.</p>
          <div className="flex items-center gap-6">
            <Link to="/privacy" className="text-[#C47245] font-medium">Privacy Policy</Link>
            <Link to="/terms" className="hover:text-[#C47245] transition-colors">Terms of Service</Link>
            <Link to="/refund-policy" className="hover:text-[#C47245] transition-colors">Refund Policy</Link>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default PrivacyPolicyPage;
