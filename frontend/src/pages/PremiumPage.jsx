import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { motion } from 'framer-motion';
import { ArrowLeft, Crown, Check, Sparkles, Zap, Headphones, Star, X, AlertTriangle } from 'lucide-react';
import { API_URL } from '../constants';
import { PREMIUM } from '../constants/testIds';
import { formatCurrency } from '../lib/currency';
import EYVLogo from '../components/EYVLogo';
import { Button } from '../components/ui/button';

const PremiumPage = ({ user }) => {
  const navigate = useNavigate();
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [actionProcessing, setActionProcessing] = useState(null); // null | 'cancel' | 'resume' | 'portal'
  const [selectedPlan, setSelectedPlan] = useState('yearly');

  useEffect(() => {
    fetchStatus();
  }, []);

  const fetchStatus = async () => {
    try {
      const response = await axios.get(`${API_URL}/subscription/status`, { withCredentials: true });
      setStatus(response.data);
    } catch (error) {
      console.error('Error fetching subscription status:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleSubscribe = async () => {
    setProcessing(true);
    try {
      const response = await axios.post(
        `${API_URL}/payments/checkout`,
        {
          package_id: selectedPlan,
          origin_url: window.location.origin,
        },
        { withCredentials: true }
      );

      // Redirect to Stripe Checkout
      if (response.data.url) {
        window.location.href = response.data.url;
      }
    } catch (error) {
      console.error('Subscription error:', error);
      alert('Failed to start checkout. Please try again.');
      setProcessing(false);
    }
  };

  const handleCancel = async () => {
    if (!window.confirm(
      "Cancel your Premium subscription? You'll keep full access until the end of your current billing period - it just won't renew after that."
    )) {
      return;
    }
    setActionProcessing('cancel');
    try {
      const response = await axios.post(`${API_URL}/subscription/cancel`, {}, { withCredentials: true });
      setStatus(response.data);
    } catch (error) {
      console.error('Cancel subscription error:', error);
      alert('Could not cancel your subscription. Please try again.');
    } finally {
      setActionProcessing(null);
    }
  };

  const handleResume = async () => {
    setActionProcessing('resume');
    try {
      const response = await axios.post(`${API_URL}/subscription/resume`, {}, { withCredentials: true });
      setStatus(response.data);
    } catch (error) {
      console.error('Resume subscription error:', error);
      alert('Could not resume your subscription. Please try again.');
    } finally {
      setActionProcessing(null);
    }
  };

  const handleManageBilling = async () => {
    setActionProcessing('portal');
    try {
      const response = await axios.post(
        `${API_URL}/subscription/portal`,
        { return_url: window.location.href },
        { withCredentials: true }
      );
      if (response.data.url) {
        window.location.href = response.data.url;
      }
    } catch (error) {
      console.error('Billing portal error:', error);
      alert('Could not open billing management. Please try again.');
      setActionProcessing(null);
    }
  };

  const benefits = [
    { icon: Zap, title: 'Priority AI Concierge', description: 'Skip the queue with faster AI responses and unlimited trip generations' },
    { icon: Star, title: 'Exclusive Discounts', description: 'Member-only deals on hotels, flights, and activities (up to 20% off)' },
    { icon: Crown, title: 'Luxury Upgrades', description: 'Complimentary room upgrades and amenities at partner hotels' },
    { icon: Headphones, title: '24/7 Priority Support', description: 'Dedicated travel concierge available around the clock' },
    { icon: Sparkles, title: 'Bonus Rewards Points', description: 'Earn 2x points on every booking and 1000 bonus signup points' },
    { icon: Check, title: 'Free Cancellation', description: 'Cancel any booking up to 48 hours before with no fees' },
  ];

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin h-12 w-12 border-4 border-[#C47245] border-t-transparent rounded-full"></div>
      </div>
    );
  }

  const isPremium = status?.is_premium;
  const plans = status?.available_plans || {};

  return (
    <div data-testid={PREMIUM.premiumContainer} className="min-h-screen bg-[#FDFBF7]">
      <div className="glass sticky top-0 z-50 border-b border-[#E7E5E4]">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button onClick={() => navigate('/dashboard')} variant="ghost" className="text-[#57534E]">
              <ArrowLeft size={20} />
            </Button>
            <EYVLogo size="small" />
          </div>
          <h2 className="text-2xl font-medium text-[#2A4B5C]" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
            EYV Premium
          </h2>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-6 py-12">
        {/* Hero */}
        <div className="text-center mb-12">
          <motion.div
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ duration: 0.6, type: 'spring' }}
            className="inline-flex items-center gap-3 bg-gradient-to-r from-[#C47245] to-[#E8B273] text-white px-6 py-2 rounded-full mb-6"
          >
            <Crown size={20} />
            <span className="text-sm font-medium uppercase tracking-wider">Premium Membership</span>
          </motion.div>
          <h1 className="text-5xl md:text-6xl font-semibold text-[#1C1917] mb-4 tracking-tight" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
            Travel Beyond the Ordinary
          </h1>
          <p className="text-xl text-[#57534E] max-w-2xl mx-auto">
            Unlock exclusive perks, priority support, and luxurious experiences with EYV Premium.
          </p>
        </div>

        {/* Current Status */}
        {isPremium && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-gradient-to-r from-[#C47245] to-[#E8B273] text-white rounded-2xl p-8 mb-6 text-center"
          >
            <Crown size={48} className="mx-auto mb-4" />
            <h2 className="text-3xl font-semibold mb-2" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
              You're a Premium Member! 🎉
            </h2>
            <p className="text-white/90">
              {status.premium_plan === 'monthly' ? 'Monthly Plan' : 'Yearly Plan'}
              {status.current_period_end && (
                status.cancel_at_period_end
                  ? ` • Access ends ${new Date(status.current_period_end).toLocaleDateString()}`
                  : ` • Renews ${new Date(status.current_period_end).toLocaleDateString()}`
              )}
            </p>

            <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
              {status.cancel_at_period_end ? (
                <Button
                  data-testid={PREMIUM.resumeButton}
                  onClick={handleResume}
                  disabled={actionProcessing === 'resume'}
                  variant="outline"
                  className="bg-white/10 border-white/40 text-white hover:bg-white/20"
                >
                  {actionProcessing === 'resume' ? 'Resuming…' : 'Resume Subscription'}
                </Button>
              ) : (
                <Button
                  data-testid={PREMIUM.cancelButton}
                  onClick={handleCancel}
                  disabled={actionProcessing === 'cancel'}
                  variant="outline"
                  className="bg-white/10 border-white/40 text-white hover:bg-white/20"
                >
                  {actionProcessing === 'cancel' ? 'Cancelling…' : 'Cancel Subscription'}
                </Button>
              )}
            </div>
            <button
              onClick={handleManageBilling}
              disabled={actionProcessing === 'portal'}
              className="mt-4 text-sm text-white/80 underline hover:text-white"
            >
              {actionProcessing === 'portal' ? 'Opening…' : 'Manage billing & payment methods'}
            </button>
          </motion.div>
        )}

        {/* Past-due notice - access stays on during Stripe's own retry
            window (is_user_premium treats past_due as active - see
            server.py), this is purely informational + a fix-it action,
            not an alarming "you've lost access" message. */}
        {status?.subscription_status === 'past_due' && (
          <motion.div
            data-testid={PREMIUM.pastDueNotice}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-amber-50 border border-amber-200 rounded-2xl p-6 mb-12 flex flex-col sm:flex-row items-start sm:items-center gap-4"
          >
            <AlertTriangle className="text-amber-600 shrink-0" size={22} />
            <div className="flex-1">
              <p className="font-medium text-amber-900">There's an issue with your last payment</p>
              <p className="text-sm text-amber-800 mt-1">
                Your Premium benefits are still active while we retry the charge - update
                your payment method to keep things running smoothly.
              </p>
            </div>
            <Button
              data-testid={PREMIUM.updatePaymentButton}
              onClick={handleManageBilling}
              disabled={actionProcessing === 'portal'}
              className="bg-amber-600 hover:bg-amber-700 text-white shrink-0"
            >
              {actionProcessing === 'portal' ? 'Opening…' : 'Update Payment Method'}
            </Button>
          </motion.div>
        )}

        {/* Benefits Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-12">
          {benefits.map((benefit, idx) => (
            <motion.div
              key={idx}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              transition={{ delay: idx * 0.1 }}
              className="bg-white p-6 rounded-2xl border border-[#E7E5E4]"
            >
              <div className="w-12 h-12 bg-[#C47245]/10 rounded-xl flex items-center justify-center mb-4">
                <benefit.icon size={24} className="text-[#C47245]" />
              </div>
              <h3 className="text-xl font-medium text-[#1C1917] mb-2" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                {benefit.title}
              </h3>
              <p className="text-[#57534E]">{benefit.description}</p>
            </motion.div>
          ))}
        </div>

        {/* Pricing */}
        {!isPremium && (
          <div className="bg-white rounded-3xl p-12 border border-[#E7E5E4]">
            <h2 className="text-3xl font-medium text-[#1C1917] text-center mb-2" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
              Choose Your Plan
            </h2>
            <p className="text-[#57534E] text-center mb-10">Save 17% with yearly billing</p>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-3xl mx-auto mb-8">
              {/* Monthly */}
              <div
                data-testid={PREMIUM.monthlyPlan}
                onClick={() => setSelectedPlan('monthly')}
                className={`relative p-8 rounded-2xl border-2 cursor-pointer transition-all ${
                  selectedPlan === 'monthly' ? 'border-[#C47245] bg-[#C47245]/5' : 'border-[#E7E5E4]'
                }`}
              >
                <h3 className="text-2xl font-medium text-[#1C1917] mb-2" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Monthly
                </h3>
                <div className="flex items-baseline gap-2 mb-4">
                  <span className="text-5xl font-semibold text-[#1C1917]">{formatCurrency(plans.monthly?.amount, plans.monthly?.currency)}</span>
                  <span className="text-[#57534E]">/month</span>
                </div>
                <p className="text-sm text-[#57534E] mb-6">Cancel anytime. Billed monthly.</p>
                <ul className="space-y-2">
                  <li className="flex items-center gap-2 text-sm text-[#1C1917]">
                    <Check size={16} className="text-[#C47245]" />
                    All Premium benefits
                  </li>
                  <li className="flex items-center gap-2 text-sm text-[#1C1917]">
                    <Check size={16} className="text-[#C47245]" />
                    Flexible monthly billing
                  </li>
                </ul>
              </div>

              {/* Yearly */}
              <div
                data-testid={PREMIUM.yearlyPlan}
                onClick={() => setSelectedPlan('yearly')}
                className={`relative p-8 rounded-2xl border-2 cursor-pointer transition-all ${
                  selectedPlan === 'yearly' ? 'border-[#C47245] bg-[#C47245]/5' : 'border-[#E7E5E4]'
                }`}
              >
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-[#C47245] text-white text-xs px-3 py-1 rounded-full font-medium uppercase tracking-wider">
                  Best Value
                </div>
                <h3 className="text-2xl font-medium text-[#1C1917] mb-2" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Yearly
                </h3>
                <div className="flex items-baseline gap-2 mb-1">
                  <span className="text-5xl font-semibold text-[#1C1917]">{formatCurrency(plans.yearly?.amount, plans.yearly?.currency)}</span>
                  <span className="text-[#57534E]">/year</span>
                </div>
                <p className="text-sm text-green-600 font-medium mb-4">
                  Save {formatCurrency((plans.monthly?.amount ?? 0) * 12 - (plans.yearly?.amount ?? 0), plans.yearly?.currency)} vs monthly
                </p>
                <p className="text-sm text-[#57534E] mb-6">Best value. Billed annually.</p>
                <ul className="space-y-2">
                  <li className="flex items-center gap-2 text-sm text-[#1C1917]">
                    <Check size={16} className="text-[#C47245]" />
                    All Premium benefits
                  </li>
                  <li className="flex items-center gap-2 text-sm text-[#1C1917]">
                    <Check size={16} className="text-[#C47245]" />
                    Save 17% vs monthly
                  </li>
                  <li className="flex items-center gap-2 text-sm text-[#1C1917]">
                    <Check size={16} className="text-[#C47245]" />
                    1000 bonus reward points
                  </li>
                </ul>
              </div>
            </div>

            <div className="text-center">
              <Button
                data-testid={PREMIUM.subscribeButton}
                onClick={handleSubscribe}
                disabled={processing}
                className="bg-gradient-to-r from-[#C47245] to-[#E8B273] hover:from-[#A85D38] hover:to-[#C47245] text-white px-12 py-6 text-lg rounded-full"
              >
                {processing ? 'Processing...' : (
                  <>
                    <Crown size={20} />
                    Subscribe to {selectedPlan === 'monthly' ? 'Monthly' : 'Yearly'} - {formatCurrency(plans[selectedPlan]?.amount, plans[selectedPlan]?.currency)}
                  </>
                )}
              </Button>
              <p className="text-xs text-[#57534E] mt-4">
                Secure payment via Stripe. Cancel anytime.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default PremiumPage;
