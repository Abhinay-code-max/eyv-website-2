/*
 * DISCLAIMER / LEGAL NOTICE:
 * This is a FIRST DRAFT generated for informational and compliance scaffolding purposes.
 * It must be reviewed, customized, and finalized by qualified legal counsel prior to
 * relying on it for regulatory compliance.
 */

import React from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { ArrowLeft, RefreshCcw, HelpCircle, CheckCircle, Clock, AlertTriangle, ShieldCheck, Mail } from 'lucide-react';
import EYVLogo from '../components/EYVLogo';
import { LEGAL } from '../constants/testIds';
import { Button } from '../components/ui/button';

const RefundPolicyPage = () => {
  const navigate = useNavigate();

  return (
    <div data-testid={LEGAL?.refundPage || 'refund-policy-page'} className="min-h-screen bg-[#FDFBF7] text-[#1C1917]">
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
              This document is a draft Cancellation and Refund Policy for EYV (Enjoy Your Vacation). It details our
              cancellation workflows, support contact mechanisms, and subscription refund rules. It is subject to formal legal review.
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
            <RefreshCcw size={16} />
            <span>Fair & Clear Terms</span>
          </div>
          <h1
            className="text-4xl md:text-5xl font-semibold text-[#1C1917] mb-4 tracking-tight"
            style={{ fontFamily: 'Cormorant Garamond, serif' }}
          >
            Refund & Cancellation Policy
          </h1>
          <p className="text-sm text-[#57534E]">
            Last updated: August 17, 2026 · Effective Date: August 17, 2026
          </p>
        </motion.div>

        {/* Policy Body */}
        <div className="space-y-10 text-[#44403C] leading-relaxed text-[15px]">
          {/* Section 1: Overview */}
          <section className="bg-white p-8 rounded-3xl border border-[#E7E5E4] shadow-sm">
            <h2
              className="text-2xl font-semibold text-[#1C1917] mb-4"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}
            >
              1. Policy Overview
            </h2>
            <p className="mb-3">
              At <strong>EYV (Enjoy Your Vacation)</strong>, we want travel planning to be transparent and stress-free.
              This Refund & Cancellation Policy outlines how cancellations, modifications, and refunds work across our
              platform for both travel bookings (flights, accommodations, activities) and EYV Premium subscriptions.
            </p>
          </section>

          {/* Section 2: Trip Bookings Cancellation & Refunds */}
          <section className="bg-white p-8 rounded-3xl border border-[#E7E5E4] shadow-sm">
            <h2
              className="text-2xl font-semibold text-[#1C1917] mb-4"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}
            >
              2. Flight & Hotel Bookings Cancellation
            </h2>
            <div className="space-y-6">
              {/* Pre-payment cancellation */}
              <div className="p-5 rounded-2xl bg-[#FAF8F5] border border-[#E7E5E4]">
                <h3 className="font-semibold text-[#1C1917] mb-2 flex items-center gap-2">
                  <CheckCircle size={18} className="text-green-600" />
                  A. Unpaid & Draft Bookings (Pre-Payment)
                </h3>
                <p className="text-sm text-[#57534E] leading-relaxed mb-2">
                  Any booking in a draft or pending status (e.g. <code className="text-xs bg-white px-1.5 py-0.5 rounded border border-[#E7E5E4]">pending_payment</code>)
                  can be cancelled immediately with a single click in your Bookings Dashboard without any penalty or charge.
                </p>
                <p className="text-sm text-[#57534E] leading-relaxed">
                  If you applied EYV Reward Points to that reservation, all reserved points are automatically unlocked and returned
                  to your loyalty balance immediately upon cancellation or checkout expiration.
                </p>
              </div>

              {/* Paid booking cancellation */}
              <div className="p-5 rounded-2xl bg-[#FAF8F5] border border-[#E7E5E4]">
                <h3 className="font-semibold text-[#1C1917] mb-2 flex items-center gap-2">
                  <HelpCircle size={18} className="text-[#C47245]" />
                  B. Paid & Confirmed Bookings (Post-Payment)
                </h3>
                <p className="text-sm text-[#57534E] leading-relaxed mb-3">
                  Once a booking is paid and confirmed, third-party carrier reservations (with airlines via Ignav or hotels via SerpApi partners)
                  are locked in. Because each airline and hotel provider enforces independent fare conditions (refundable vs. non-refundable tickets):
                </p>
                <ul className="list-disc pl-5 space-y-2 text-sm text-[#57534E] mb-4">
                  <li>Direct automated 1-click cancellation of paid bookings is not available in the self-service UI to prevent unintended non-refundable carrier losses.</li>
                  <li><strong>How to cancel a paid booking:</strong> Please reach out to our dedicated Support Team via the in-app <strong>Support Widget</strong> or by emailing <a href="mailto:support@eyv.travel" className="text-[#C47245] underline">support@eyv.travel</a> with your Booking Reference Number.</li>
                  <li>Our support specialists will coordinate directly with the airline or property to process any available refund or travel credit in accordance with the ticket's fare rules.</li>
                </ul>
              </div>
            </div>
          </section>

          {/* Section 3: Premium Subscriptions */}
          <section className="bg-white p-8 rounded-3xl border border-[#E7E5E4] shadow-sm">
            <h2
              className="text-2xl font-semibold text-[#1C1917] mb-4"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}
            >
              3. Premium Subscriptions & Billing
            </h2>
            <div className="space-y-4 text-sm text-[#57534E]">
              <div>
                <h3 className="font-semibold text-[#1C1917] mb-1">A. Self-Service Cancellation Anytime</h3>
                <p>
                  You can cancel your EYV Premium subscription (Monthly or Yearly) at any time through the <Link to="/premium" className="text-[#C47245] underline">Premium Page</Link> or
                  via the Stripe Customer Billing Portal.
                </p>
              </div>
              <div>
                <h3 className="font-semibold text-[#1C1917] mb-1">B. Cancel-at-Period-End</h3>
                <p>
                  When you cancel your subscription, it is scheduled to end at the conclusion of your current paid billing period
                  (<code className="text-xs bg-[#FAF8F5] px-1.5 py-0.5 rounded border border-[#E7E5E4]">cancel_at_period_end</code>). You will retain full access to all Premium benefits until the end of that period, and you will not be billed again.
                  If you change your mind, you can resume your subscription with one click before the period concludes.
                </p>
              </div>
              <div>
                <h3 className="font-semibold text-[#1C1917] mb-1">C. Subscription Refund Requests</h3>
                <p>
                  Subscription fees are generally non-refundable once the billing cycle begins. However, if you experienced technical
                  difficulties or were charged unintentionally, please contact <a href="mailto:support@eyv.travel" className="text-[#C47245] underline">support@eyv.travel</a> within 14 days of the charge for an evaluation.
                </p>
              </div>
            </div>
          </section>

          {/* Section 4: Refund Processing Timelines */}
          <section className="bg-white p-8 rounded-3xl border border-[#E7E5E4] shadow-sm">
            <h2
              className="text-2xl font-semibold text-[#1C1917] mb-4"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}
            >
              4. Refund Processing & Timelines
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm text-[#57534E]">
              <div className="p-4 rounded-2xl bg-[#FAF8F5] border border-[#E7E5E4]">
                <div className="flex items-center gap-2 font-semibold text-[#1C1917] mb-1">
                  <Clock size={16} className="text-[#C47245]" />
                  Original Payment Method
                </div>
                <p>
                  All approved refunds are credited back directly to the original card or payment instrument used during checkout via Stripe.
                </p>
              </div>
              <div className="p-4 rounded-2xl bg-[#FAF8F5] border border-[#E7E5E4]">
                <div className="flex items-center gap-2 font-semibold text-[#1C1917] mb-1">
                  <ShieldCheck size={16} className="text-[#C47245]" />
                  5–10 Business Days
                </div>
                <p>
                  Once initiated by EYV Support, funds typically appear on your statement within 5 to 10 business days depending on your bank.
                </p>
              </div>
            </div>
          </section>

          {/* Section 5: How to Get Help */}
          <section className="bg-[#FAF8F5] p-8 rounded-3xl border border-[#E7E5E4]">
            <h2
              className="text-2xl font-semibold text-[#1C1917] mb-3"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}
            >
              5. Contact Support for Assistance
            </h2>
            <p className="text-sm text-[#57534E] mb-4">
              Our travel support team is here to assist with booking cancellations, change requests, or payment questions:
            </p>
            <div className="flex flex-wrap gap-4">
              <a
                href="mailto:support@eyv.travel?subject=Cancellation%20or%20Refund%20Request"
                className="inline-flex items-center gap-2 bg-[#C47245] text-white px-5 py-2.5 rounded-full text-sm font-medium hover:bg-[#A85D38] transition-colors"
              >
                <Mail size={16} />
                Email Support Team
              </a>
              <Link
                to="/dashboard"
                className="inline-flex items-center gap-2 bg-white border border-[#E7E5E4] text-[#1C1917] px-5 py-2.5 rounded-full text-sm font-medium hover:border-[#C47245] transition-colors"
              >
                Go to Dashboard
              </Link>
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
            <Link to="/terms" className="hover:text-[#C47245] transition-colors">Terms of Service</Link>
            <Link to="/refund-policy" className="text-[#C47245] font-medium">Refund Policy</Link>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default RefundPolicyPage;
