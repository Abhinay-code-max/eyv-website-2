import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { motion } from 'framer-motion';
import { ArrowLeft, Award, TrendingUp, Gift, Sparkles, Plane, Hotel, Star, Users } from 'lucide-react';
import { API_URL } from '../constants';
import { REWARDS } from '../constants/testIds';
import EYVLogo from '../components/EYVLogo';
import { Button } from '../components/ui/button';

const RewardsPage = ({ user }) => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);

  useEffect(() => {
    fetchRewards();
  }, []);

  const fetchRewards = async () => {
    try {
      const response = await axios.get(`${API_URL}/rewards`, { withCredentials: true });
      setData(response.data);
    } catch (error) {
      console.error('Error fetching rewards:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin h-12 w-12 border-4 border-[#C47245] border-t-transparent rounded-full"></div>
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
    { icon: Plane, action: 'booking_flight', label: 'Flight Booking', points: data.earn_rules.booking_flight },
    { icon: Hotel, action: 'booking_hotel', label: 'Hotel Booking', points: data.earn_rules.booking_hotel },
    { icon: Star, action: 'trip_completed', label: 'Trip Completed', points: data.earn_rules.trip_completed },
    { icon: Sparkles, action: 'first_booking_bonus', label: 'First Booking Bonus', points: data.earn_rules.first_booking_bonus },
    { icon: Award, action: 'premium_subscription', label: 'Premium Signup', points: data.earn_rules.premium_subscription },
    { icon: Users, action: 'referral', label: 'Referral', points: data.earn_rules.referral },
  ];

  return (
    <div data-testid={REWARDS.rewardsContainer} className="min-h-screen bg-[#FDFBF7]">
      <div className="glass sticky top-0 z-50 border-b border-[#E7E5E4]">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button onClick={() => navigate('/dashboard')} variant="ghost" className="text-[#57534E]">
              <ArrowLeft size={20} />
            </Button>
            <EYVLogo size="small" />
          </div>
          <h2 className="text-2xl font-medium text-[#2A4B5C]" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
            Travel Rewards
          </h2>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-8">
        {/* Hero Card */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="relative overflow-hidden rounded-3xl mb-8"
          style={{ background: `linear-gradient(135deg, ${tier.color}DD, ${tier.color}AA)` }}
        >
          <div className="absolute top-0 right-0 opacity-10">
            <Award size={300} className="text-white -translate-y-12 translate-x-12" />
          </div>
          <div className="relative p-10 text-white">
            <div className="flex items-center justify-between mb-6">
              <div>
                <p className="text-white/80 text-sm uppercase tracking-wider mb-2">Current Tier</p>
                <h1
                  data-testid={REWARDS.tierBadge}
                  className="text-5xl font-semibold"
                  style={{ fontFamily: 'Cormorant Garamond, serif' }}
                >
                  {tier.name}
                </h1>
                <p className="text-white/80 mt-2">{tier.multiplier}x points multiplier</p>
              </div>
              <Award size={64} className="text-white/80" />
            </div>

            <div className="grid grid-cols-2 gap-6 mb-6">
              <div>
                <p className="text-white/80 text-sm uppercase tracking-wider mb-1">Available Points</p>
                <p data-testid={REWARDS.pointsBalance} className="text-4xl font-semibold" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  {data.available_points.toLocaleString()}
                </p>
                <p className="text-white/80 text-sm mt-1">≈ ${data.available_discount_usd.toFixed(2)} discount</p>
              </div>
              <div>
                <p className="text-white/80 text-sm uppercase tracking-wider mb-1">Lifetime Points</p>
                <p className="text-4xl font-semibold" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  {data.lifetime_points.toLocaleString()}
                </p>
              </div>
            </div>

            {nextTier && (
              <div className="bg-white/10 rounded-xl p-4">
                <div className="flex justify-between text-sm mb-2">
                  <span>Progress to {nextTier.name}</span>
                  <span>{data.points_to_next_tier.toLocaleString()} points to go</span>
                </div>
                <div className="bg-white/20 rounded-full h-2">
                  <div
                    className="bg-white h-2 rounded-full transition-all duration-500"
                    style={{ width: `${progressPercent}%` }}
                  ></div>
                </div>
              </div>
            )}
          </div>
        </motion.div>

        {/* Tiers Overview */}
        <div className="bg-white rounded-2xl p-8 border border-[#E7E5E4] mb-8">
          <h2 className="text-2xl font-medium text-[#2A4B5C] mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
            Loyalty Tiers
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            {data.all_tiers.map((t, idx) => (
              <div
                key={t.name}
                className={`relative p-6 rounded-2xl border-2 transition-all ${
                  t.name === tier.name ? 'border-[#C47245] bg-[#C47245]/5' : 'border-[#E7E5E4]'
                }`}
              >
                {t.name === tier.name && (
                  <div className="absolute -top-3 -right-3 bg-[#C47245] text-white text-xs px-3 py-1 rounded-full">
                    Current
                  </div>
                )}
                <div
                  className="w-12 h-12 rounded-full mb-3 flex items-center justify-center"
                  style={{ backgroundColor: `${t.color}30` }}
                >
                  <Award size={24} style={{ color: t.color }} />
                </div>
                <h3 className="text-xl font-medium text-[#1C1917] mb-1" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  {t.name}
                </h3>
                <p className="text-sm text-[#57534E] mb-2">
                  {t.min_points.toLocaleString()}+ points
                </p>
                <p className="text-sm text-[#C47245] font-medium">
                  {t.multiplier}x multiplier
                </p>
              </div>
            ))}
          </div>
        </div>

        {/* Earn Rules */}
        <div className="bg-white rounded-2xl p-8 border border-[#E7E5E4] mb-8">
          <h2 className="text-2xl font-medium text-[#2A4B5C] mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
            How to Earn Points
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {earnActions.map((action) => (
              <div
                key={action.action}
                className="flex items-center gap-4 p-4 bg-[#F5F2EB] rounded-xl"
              >
                <div className="bg-white p-3 rounded-lg">
                  <action.icon size={24} className="text-[#C47245]" />
                </div>
                <div className="flex-1">
                  <p className="font-medium text-[#1C1917]">{action.label}</p>
                  <p className="text-[#C47245] font-semibold">+{action.points} pts</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Transactions */}
        <div data-testid={REWARDS.transactionsList} className="bg-white rounded-2xl p-8 border border-[#E7E5E4]">
          <h2 className="text-2xl font-medium text-[#2A4B5C] mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
            Recent Activity
          </h2>
          {data.transactions.length === 0 ? (
            <div className="text-center py-12">
              <Gift size={48} className="mx-auto text-[#E7E5E4] mb-4" />
              <p className="text-[#57534E]">No activity yet. Start booking to earn points!</p>
              <Button onClick={() => navigate('/bookings')} className="mt-4 bg-[#C47245] hover:bg-[#A85D38]">
                Book Now
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              {data.transactions.map((tx, idx) => (
                <div
                  key={tx.transaction_id || idx}
                  className="flex items-center justify-between p-4 border border-[#E7E5E4] rounded-xl"
                >
                  <div className="flex items-center gap-4">
                    <div className={`p-3 rounded-lg ${tx.type === 'earn' ? 'bg-green-100' : 'bg-orange-100'}`}>
                      {tx.type === 'earn' ? (
                        <TrendingUp size={20} className="text-green-600" />
                      ) : (
                        <Gift size={20} className="text-orange-600" />
                      )}
                    </div>
                    <div>
                      <p className="font-medium text-[#1C1917]">{tx.description}</p>
                      <p className="text-xs text-[#57534E]">{new Date(tx.created_at).toLocaleString()}</p>
                    </div>
                  </div>
                  <div className={`text-xl font-semibold ${tx.points > 0 ? 'text-green-600' : 'text-orange-600'}`}>
                    {tx.points > 0 ? '+' : ''}{tx.points.toLocaleString()}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default RewardsPage;
