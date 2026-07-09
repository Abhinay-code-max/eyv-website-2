import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { motion, useInView } from 'framer-motion';
import {
  ArrowLeft, Award, TrendingUp, Gift, Sparkles,
  Plane, Hotel, Star, Users, ChevronRight,
} from 'lucide-react';
import { API_URL } from '../constants';
import { REWARDS } from '../constants/testIds';
import EYVLogo from '../components/EYVLogo';
import { Button } from '../components/ui/button';

/* ── animated count-up ──────────────────────────────────────────── */
const useCountUp = (target, inView, duration = 1400) => {
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (!inView || !target) return;
    let raf;
    const start = performance.now();
    const tick = (now) => {
      const p = Math.min((now - start) / duration, 1);
      setValue(target * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [inView, target, duration]);
  return Math.round(value);
};

const AnimatedNumber = ({ value }) => {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true });
  const n = useCountUp(value, inView);
  return <span ref={ref}>{n.toLocaleString()}</span>;
};

const fadeUp = {
  hidden: { opacity: 0, y: 24 },
  show: (i = 0) => ({
    opacity: 1, y: 0,
    transition: { duration: 0.6, delay: i * 0.1, ease: [0.22, 1, 0.36, 1] },
  }),
};

const RewardsPage = ({ user }) => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);

  useEffect(() => { fetchRewards(); }, []);

  /* ── API call preserved verbatim ── */
  const fetchRewards = async () => {
    try {
      const response = await axios.get(`${API_URL}/rewards`, { withCredentials: true });
      setData(response.data);
    } catch (error) { console.error('Error fetching rewards:', error); }
    finally { setLoading(false); }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[#FDFBF7] flex items-center justify-center">
        <motion.div animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
          className="h-12 w-12 border-4 border-[#C47245] border-t-transparent rounded-full" />
      </div>
    );
  }
  if (!data) return null;

  const tier = data.current_tier;
  const nextTier = data.next_tier;
  const progressPercent = nextTier
    ? Math.min(100, (data.lifetime_points / nextTier.min_points) * 100)
    : 100;

  const earnActions = [
    { icon: Plane,    action: 'booking_flight',      label: 'Flight Booking',    points: data.earn_rules.booking_flight },
    { icon: Hotel,    action: 'booking_hotel',        label: 'Hotel Booking',     points: data.earn_rules.booking_hotel },
    { icon: Star,     action: 'trip_completed',       label: 'Trip Completed',    points: data.earn_rules.trip_completed },
    { icon: Sparkles, action: 'first_booking_bonus',  label: 'First Booking Bonus', points: data.earn_rules.first_booking_bonus },
    { icon: Award,    action: 'premium_subscription', label: 'Premium Signup',    points: data.earn_rules.premium_subscription },
    { icon: Users,    action: 'referral',             label: 'Referral',          points: data.earn_rules.referral },
  ];

  return (
    <motion.div
      data-testid={REWARDS.rewardsContainer}
      className="min-h-screen bg-[#FDFBF7]"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.4 }}
    >
      {/* Header */}
      <motion.div initial={{ y: -60, opacity: 0 }} animate={{ y: 0, opacity: 1 }}
        className="sticky top-0 z-50 bg-[#FDFBF7]/80 backdrop-blur-xl border-b border-[#E7E5E4] shadow-sm">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button onClick={() => navigate('/dashboard')} variant="ghost"
              className="text-[#57534E] hover:text-[#C47245] transition-colors">
              <ArrowLeft size={20} />
            </Button>
            <EYVLogo size="small" />
          </div>
          <h2 className="text-2xl font-medium text-[#2A4B5C]"
            style={{ fontFamily: 'Cormorant Garamond, serif' }}>Travel Rewards</h2>
        </div>
      </motion.div>

      <div className="max-w-7xl mx-auto px-6 py-8">

        {/* Hero tier card */}
        <motion.div variants={fadeUp} initial="hidden" animate="show"
          className="relative overflow-hidden rounded-3xl mb-8"
          style={{ background: `linear-gradient(135deg, ${tier.color}EE, ${tier.color}99)` }}>
          {/* Decorative background Award icon */}
          <div className="absolute top-0 right-0 opacity-8 pointer-events-none select-none">
            <Award size={280} className="text-white -translate-y-10 translate-x-10" />
          </div>
          {/* Subtle shimmer strip */}
          <div className="absolute inset-0 bg-gradient-to-r from-white/0 via-white/8 to-white/0 pointer-events-none" />

          <div className="relative p-8 md:p-10 text-white">
            <div className="flex items-start justify-between mb-8 flex-wrap gap-4">
              <div>
                <p className="text-white/75 text-xs uppercase tracking-[0.22em] mb-2">Current Tier</p>
                <h1 data-testid={REWARDS.tierBadge}
                  className="text-5xl font-semibold"
                  style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  {tier.name}
                </h1>
                <p className="text-white/80 mt-2">{tier.multiplier}x points multiplier</p>
              </div>
              <motion.div animate={{ rotate: [0, 8, -8, 0] }} transition={{ duration: 4, repeat: Infinity }}>
                <Award size={60} className="text-white/70" />
              </motion.div>
            </div>

            <div className="grid grid-cols-2 gap-6 mb-6">
              <div>
                <p className="text-white/75 text-xs uppercase tracking-wider mb-1">Available Points</p>
                <p data-testid={REWARDS.pointsBalance}
                  className="text-4xl font-semibold"
                  style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  <AnimatedNumber value={data.available_points} />
                </p>
                <p className="text-white/70 text-sm mt-1">
                  ≈ ${data.available_discount_usd.toFixed(2)} discount
                </p>
              </div>
              <div>
                <p className="text-white/75 text-xs uppercase tracking-wider mb-1">Lifetime Points</p>
                <p className="text-4xl font-semibold"
                  style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  <AnimatedNumber value={data.lifetime_points} />
                </p>
              </div>
            </div>

            {nextTier && (
              <div className="bg-white/15 backdrop-blur-sm rounded-2xl p-4 border border-white/20">
                <div className="flex justify-between text-sm mb-2">
                  <span>Progress to {nextTier.name}</span>
                  <span>{data.points_to_next_tier.toLocaleString()} pts to go</span>
                </div>
                <div className="bg-white/20 rounded-full h-2.5 overflow-hidden">
                  <motion.div className="bg-white h-full rounded-full"
                    initial={{ width: 0 }}
                    animate={{ width: `${progressPercent}%` }}
                    transition={{ duration: 1.2, ease: 'easeOut', delay: 0.4 }} />
                </div>
              </div>
            )}
          </div>
        </motion.div>

        {/* Tiers overview */}
        <motion.div variants={fadeUp} custom={1} initial="hidden" whileInView="show"
          viewport={{ once: true }}
          className="bg-white rounded-2xl p-8 border border-[#E7E5E4] mb-8 shadow-sm">
          <h2 className="text-2xl font-medium text-[#2A4B5C] mb-6"
            style={{ fontFamily: 'Cormorant Garamond, serif' }}>Loyalty Tiers</h2>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            {data.all_tiers.map((t, idx) => (
              <motion.div key={t.name}
                variants={fadeUp} custom={idx} initial="hidden" whileInView="show"
                viewport={{ once: true }}
                whileHover={{ y: -4 }}
                className={`relative p-6 rounded-2xl border-2 transition-all ${
                  t.name === tier.name
                    ? 'border-[#C47245] bg-[#C47245]/5 shadow-md'
                    : 'border-[#E7E5E4] hover:border-[#C47245]/30'
                }`}>
                {t.name === tier.name && (
                  <motion.div
                    initial={{ scale: 0 }} animate={{ scale: 1 }}
                    className="absolute -top-3 -right-3 bg-[#C47245] text-white text-xs px-3 py-1 rounded-full font-medium">
                    Current
                  </motion.div>
                )}
                <motion.div
                  whileHover={{ rotate: 15 }}
                  className="w-12 h-12 rounded-full mb-3 flex items-center justify-center"
                  style={{ backgroundColor: `${t.color}25` }}>
                  <Award size={24} style={{ color: t.color }} />
                </motion.div>
                <h3 className="text-xl font-medium text-[#1C1917] mb-1"
                  style={{ fontFamily: 'Cormorant Garamond, serif' }}>{t.name}</h3>
                <p className="text-sm text-[#57534E] mb-2">{t.min_points.toLocaleString()}+ points</p>
                <p className="text-sm font-semibold" style={{ color: t.color }}>{t.multiplier}x multiplier</p>
              </motion.div>
            ))}
          </div>
        </motion.div>

        {/* Earn rules */}
        <motion.div variants={fadeUp} custom={2} initial="hidden" whileInView="show"
          viewport={{ once: true }}
          className="bg-white rounded-2xl p-8 border border-[#E7E5E4] mb-8 shadow-sm">
          <h2 className="text-2xl font-medium text-[#2A4B5C] mb-6"
            style={{ fontFamily: 'Cormorant Garamond, serif' }}>How to Earn Points</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {earnActions.map((action, idx) => (
              <motion.div key={action.action}
                variants={fadeUp} custom={idx} initial="hidden" whileInView="show"
                viewport={{ once: true }}
                whileHover={{ x: 4, backgroundColor: '#FEF3EC' }}
                className="flex items-center gap-4 p-4 bg-[#F5F2EB] rounded-2xl transition-all cursor-default">
                <motion.div whileHover={{ scale: 1.15, rotate: 10 }}
                  className="bg-white p-3 rounded-xl shadow-sm">
                  <action.icon size={22} className="text-[#C47245]" />
                </motion.div>
                <div className="flex-1">
                  <p className="font-medium text-[#1C1917] text-sm">{action.label}</p>
                  <p className="text-[#C47245] font-bold text-base">+{action.points} pts</p>
                </div>
                <ChevronRight size={16} className="text-[#C47245] opacity-50" />
              </motion.div>
            ))}
          </div>
        </motion.div>

        {/* Transactions */}
        <motion.div data-testid={REWARDS.transactionsList}
          variants={fadeUp} custom={3} initial="hidden" whileInView="show"
          viewport={{ once: true }}
          className="bg-white rounded-2xl p-8 border border-[#E7E5E4] shadow-sm">
          <h2 className="text-2xl font-medium text-[#2A4B5C] mb-6"
            style={{ fontFamily: 'Cormorant Garamond, serif' }}>Recent Activity</h2>
          {data.transactions.length === 0 ? (
            <motion.div variants={fadeUp} initial="hidden" animate="show"
              className="text-center py-14">
              <div className="w-16 h-16 rounded-full bg-[#C47245]/10 flex items-center justify-center mx-auto mb-4">
                <Gift size={32} className="text-[#C47245]" />
              </div>
              <p className="text-[#57534E] mb-4">No activity yet. Start booking to earn points!</p>
              <Button onClick={() => navigate('/bookings')}
                className="bg-[#C47245] hover:bg-[#A85D38] hover:shadow-lg transition-all gap-2 active:scale-95">
                Book Now <ChevronRight size={16} />
              </Button>
            </motion.div>
          ) : (
            <div className="space-y-3">
              {data.transactions.map((tx, idx) => (
                <motion.div key={tx.transaction_id || idx}
                  variants={fadeUp} custom={idx} initial="hidden" whileInView="show"
                  viewport={{ once: true }}
                  whileHover={{ x: 4 }}
                  className="flex items-center justify-between p-4 border border-[#E7E5E4] rounded-2xl hover:border-[#C47245]/30 transition-all">
                  <div className="flex items-center gap-4">
                    <motion.div whileHover={{ scale: 1.1 }}
                      className={`p-3 rounded-xl ${tx.type === 'earn' ? 'bg-green-100' : 'bg-orange-100'}`}>
                      {tx.type === 'earn'
                        ? <TrendingUp size={19} className="text-green-600" />
                        : <Gift size={19} className="text-orange-600" />}
                    </motion.div>
                    <div>
                      <p className="font-medium text-[#1C1917] text-sm">{tx.description}</p>
                      <p className="text-xs text-[#57534E] mt-0.5">{new Date(tx.created_at).toLocaleString()}</p>
                    </div>
                  </div>
                  <motion.div
                    initial={{ scale: 0.8, opacity: 0 }}
                    whileInView={{ scale: 1, opacity: 1 }}
                    viewport={{ once: true }}
                    transition={{ delay: idx * 0.05 }}
                    className={`text-xl font-bold ${tx.points > 0 ? 'text-green-600' : 'text-orange-600'}`}>
                    {tx.points > 0 ? '+' : ''}{tx.points.toLocaleString()}
                  </motion.div>
                </motion.div>
              ))}
            </div>
          )}
        </motion.div>
      </div>
    </motion.div>
  );
};

export default RewardsPage;
