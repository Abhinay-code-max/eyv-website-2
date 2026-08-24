/*
 * DISCLAIMER / LEGAL NOTICE:
 * This is a FIRST DRAFT generated for informational and compliance scaffolding purposes.
 * It must be reviewed, customized, and finalized by qualified legal counsel prior to
 * relying on it for regulatory compliance.
 */

import React from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ArrowLeft, Scale, CheckCircle2, AlertCircle, FileCheck, ShieldAlert, Sparkles, AlertTriangle } from 'lucide-react';
import EYVLogo from '../components/EYVLogo';
import { LEGAL } from '../constants/testIds';
import { Button } from '../components/ui/button';

const TermsOfServicePage = () => {
  const navigate = useNavigate();

  return (
    <div data-testid={LEGAL?.termsPage || 'terms-of-service-page'} className="min-h-screen bg-[#FDFBF7] text-[#1C1917]">
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
              This document is a draft Terms of Service for EYV (Enjoy Your Vacation). It sets forth operational terms
              and boundaries for our AI travel planning and booking services. It is subject to formal review by qualified legal counsel.
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
            <Scale size={16} />
            <span>Terms of Agreement</span>
          </div>
          <h1
            className="text-4xl md:text-5xl font-semibold text-[#1C1917] mb-4 tracking-tight"
            style={{ fontFamily: 'Cormorant Garamond, serif' }}
          >
            Terms of Service
          </h1>
          <p className="text-sm text-[#57534E]">
            Last updated: August 17, 2026 · Effective Date: August 17, 2026
          </p>
        </motion.div>

        {/* Terms Body */}
        <div className="space-y-10 text-[#44403C] leading-relaxed text-[15px]">
          {/* Section 1: Agreement to Terms */}
          <section className="bg-white p-8 rounded-3xl border border-[#E7E5E4] shadow-sm">
            <h2
              className="text-2xl font-semibold text-[#1C1917] mb-4"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}
            >
              1. Acceptance of Terms
            </h2>
            <p className="mb-4">
              By accessing or using the website, applications, and services provided by <strong>EYV (Enjoy Your Vacation)</strong>
              ("EYV", "we", "us", or "our"), you agree to be bound by these Terms of Service ("Terms") and our Privacy Policy.
            </p>
            <p>
              If you do not agree to these Terms, you must not access or use our Services. By registering an account,
              you represent that you are at least 18 years old or the age of legal majority in your jurisdiction.
            </p>
          </section>

          {/* Section 2: Description of Services */}
          <section className="bg-white p-8 rounded-3xl border border-[#E7E5E4] shadow-sm">
            <h2
              className="text-2xl font-semibold text-[#1C1917] mb-4"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}
            >
              2. Description of Services
            </h2>
            <p className="mb-4">
              EYV provides an intelligent travel technology platform designed to streamline vacation planning:
            </p>
            <ul className="list-disc pl-5 space-y-2 text-[#57534E]">
              <li><strong>AI-Powered Itinerary Generation:</strong> Multi-day travel itineraries with customizable budget tiers (Budget, Standard, Luxury).</li>
              <li><strong>Travel Search & Aggregation:</strong> Flight search powered by Ignav and hotel aggregation powered by SerpApi.</li>
              <li><strong>Secure Travel Wallet:</strong> Document storage for flight tickets, hotel vouchers, and identification.</li>
              <li><strong>EYV Loyalty & Rewards:</strong> Points accrual on completed bookings and redemption discounts.</li>
              <li><strong>Premium Subscriptions:</strong> Advanced features including priority AI generation, unlimited trip plans, and real-time support.</li>
            </ul>
          </section>

          {/* Section 3: AI Output & Advisory Disclaimer */}
          <section className="bg-white p-8 rounded-3xl border border-[#E7E5E4] shadow-sm">
            <h2
              className="text-2xl font-semibold text-[#1C1917] mb-4"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}
            >
              3. AI Itinerary Generation Disclaimer & Accuracy
            </h2>
            <div className="p-4 rounded-2xl bg-[#FAF8F5] border border-[#E7E5E4] mb-4">
              <div className="flex items-start gap-3">
                <Sparkles size={20} className="text-[#C47245] shrink-0 mt-0.5" />
                <p className="text-sm text-[#57534E]">
                  Itineraries, estimates, recommendations, opening hours, local customs, transit options, and visa advisory
                  notes generated by EYV are produced using artificial intelligence models (Google Gemini) and live data feeds.
                </p>
              </div>
            </div>
            <p className="text-sm text-[#57534E] mb-3">
              While we strive to provide reliable and high-quality suggestions, <strong>AI-generated itineraries are strictly advisory</strong>.
              Travel conditions change rapidly. You acknowledge and agree that:
            </p>
            <ul className="list-disc pl-5 space-y-2 text-sm text-[#57534E]">
              <li>You are solely responsible for verifying operating hours, ticket requirements, passport validity (minimum 6 months), visa eligibility, and health regulations.</li>
              <li>Prices and availability displayed in AI estimates (e.g. cruise fares, train schedules) are estimates and may vary at final booking.</li>
              <li>EYV is not responsible for missed connections, closed attractions, weather disruptions, or government entry denials.</li>
            </ul>
          </section>

          {/* Section 4: Bookings, Payments & Subscriptions */}
          <section className="bg-white p-8 rounded-3xl border border-[#E7E5E4] shadow-sm">
            <h2
              className="text-2xl font-semibold text-[#1C1917] mb-4"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}
            >
              4. Bookings, Payments & Subscriptions
            </h2>
            <div className="space-y-4 text-sm text-[#57534E]">
              <div>
                <h3 className="font-semibold text-[#1C1917] mb-1">A. Third-Party Fulfillment</h3>
                <p>
                  Travel bookings (flights, accommodations, activities) are fulfilled by respective airlines, hotels, or travel providers.
                  Your booking is subject to the specific fare rules, baggage policies, and terms of each third-party merchant.
                </p>
              </div>
              <div>
                <h3 className="font-semibold text-[#1C1917] mb-1">B. Payment Processing</h3>
                <p>
                  All transactions are billed in the specified currency through our certified payment gateways (Stripe or regional providers).
                  By confirming a booking or subscription, you authorize EYV and our payment partners to charge your designated payment method.
                </p>
              </div>
              <div>
                <h3 className="font-semibold text-[#1C1917] mb-1">C. Premium Subscriptions & Renewal</h3>
                <p>
                  Premium memberships are billed on a recurring monthly or annual basis. Subscriptions automatically renew
                  unless cancelled prior to the end of the current billing cycle. You may cancel your subscription at any time via
                  your Premium dashboard; cancellations take effect at the end of the active billing period (cancel-at-period-end).
                </p>
              </div>
              <div>
                <h3 className="font-semibold text-[#1C1917] mb-1">D. Rewards Points Program</h3>
                <p>
                  Rewards points earned through EYV have no cash value outside the EYV platform and cannot be transferred,
                  assigned, or redeemed for cash. Points reserved at checkout will be returned if a checkout session is not completed.
                </p>
              </div>
            </div>
          </section>

          {/* Section 5: User Conduct & Prohibited Uses */}
          <section className="bg-white p-8 rounded-3xl border border-[#E7E5E4] shadow-sm">
            <h2
              className="text-2xl font-semibold text-[#1C1917] mb-4"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}
            >
              5. User Conduct & Prohibited Activities
            </h2>
            <p className="mb-4 text-sm text-[#57534E]">
              When using EYV, you agree not to engage in any of the following prohibited behaviors:
            </p>
            <ul className="list-disc pl-5 space-y-2 text-sm text-[#57534E]">
              <li>Scraping, crawling, or automated harvesting of destination guides, pricing data, or flight inventory.</li>
              <li>Circumventing rate limits, authentication barriers, or security mechanisms.</li>
              <li>Uploading malicious files, executable scripts, or unauthorized copyright/trademark materials to the Travel Wallet.</li>
              <li>Impersonating any person or entity or misrepresenting your identity during booking.</li>
              <li>Using EYV for unlawful purposes, fraudulent chargebacks, or unauthorized commercial resale.</li>
            </ul>
          </section>

          {/* Section 6: Limitation of Liability */}
          <section className="bg-white p-8 rounded-3xl border border-[#E7E5E4] shadow-sm">
            <h2
              className="text-2xl font-semibold text-[#1C1917] mb-4"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}
            >
              6. Disclaimers & Limitation of Liability
            </h2>
            <p className="mb-3 text-sm text-[#57534E]">
              TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, EYV SERVICES ARE PROVIDED ON AN "AS IS" AND "AS AVAILABLE" BASIS
              WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED.
            </p>
            <p className="text-sm text-[#57534E]">
              IN NO EVENT SHALL EYV, ITS OFFICERS, DIRECTORS, EMPLOYEES, OR PARTNERS BE LIABLE FOR ANY INDIRECT, INCIDENTAL,
              SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, INCLUDING BUT NOT LIMITED TO LOSS OF PROFITS, TRAVEL DISRUPTIONS,
              CANCELLATION PENALTIES LEVIED BY AIRLINES/HOTELS, OR PERSONAL INJURY ARISING FROM YOUR USE OF OUR SERVICES.
            </p>
          </section>

          {/* Section 7: Termination */}
          <section className="bg-white p-8 rounded-3xl border border-[#E7E5E4] shadow-sm">
            <h2
              className="text-2xl font-semibold text-[#1C1917] mb-4"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}
            >
              7. Account Termination
            </h2>
            <p className="text-sm text-[#57534E]">
              We reserve the right to suspend or terminate your account or access to the Services at our sole discretion,
              without prior notice, if we believe you have violated these Terms, engaged in fraudulent activities, or
              abused the platform.
            </p>
          </section>

          {/* Section 8: Contact */}
          <section className="bg-[#FAF8F5] p-8 rounded-3xl border border-[#E7E5E4]">
            <h2
              className="text-2xl font-semibold text-[#1C1917] mb-3"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}
            >
              8. Contact Information
            </h2>
            <p className="text-sm text-[#57534E] mb-2">
              For questions regarding these Terms of Service or legal notices, please reach out to:
            </p>
            <div className="text-sm text-[#1C1917] space-y-1">
              <p><strong>EYV Legal Operations</strong></p>
              <p>Email: <a href="mailto:support@eyv.travel" className="text-[#C47245] underline">support@eyv.travel</a></p>
            </div>
          </section>
        </div>
      </main>

      {/* ── Footer ── */}
      <footer className="py-8 px-6 bg-[#FDFBF7] border-t border-[#E7E5E4] mt-16 text-center text-xs text-[#57534E]">
        <div className="max-w-4xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
          <p>© 2026 EYV. Enjoy Your Vacation — We Plan Everything.</p>
          <div className="flex items-center gap-6">
            <Link to="/privacy" className="hover:text-[#C47245] transition-colors">Privacy Policy</Link>
            <Link to="/terms" className="text-[#C47245] font-medium">Terms of Service</Link>
            <Link to="/refund-policy" className="hover:text-[#C47245] transition-colors">Refund Policy</Link>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default TermsOfServicePage;
