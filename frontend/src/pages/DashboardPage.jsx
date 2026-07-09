import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { motion, AnimatePresence, useReducedMotion } from 'framer-motion';
import {
  Plus, MapPin, Calendar, DollarSign, LogOut, MessageCircle, Send, X,
  Sparkles, Trash2, Plane, Wallet, Award, Crown, ChevronRight,
  Clock, LayoutGrid, List, Gem, Zap,
} from 'lucide-react';
import { API_URL } from '../constants';
import { DASHBOARD, AUTH } from '../constants/testIds';
import EYVLogo from '../components/EYVLogo';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { fadeUp, staggerItem, buttonHover } from '../constants/motion';

/* ─────────────────────────────────────────────────────────────────────
   THEME ENGINE
   Reads the most recent trip's budget_level and returns a full theme
   object. Falls back to 'Budget' when no trips exist.
───────────────────────────────────────────────────────────────────── */

const THEMES = {
  Budget: {
    key: 'budget',
    label: 'Budget Mode',
    badge: '💚 Budget',
    pageBg: 'bg-[#F0FBF4]',
    headerBg: 'bg-[#F0FBF4]/80',
    cardBg: 'bg-white',
    cardBorder: 'border-[#BBF7D0]',
    cardHover: 'hover:border-[#2A7D4F]/40 hover:shadow-green-100',
    accent: '#2A7D4F',
    accentLight: '#D1FAE5',
    accentText: 'text-[#2A7D4F]',
    accentBg: 'bg-[#2A7D4F]',
    accentBgLight: 'bg-[#D1FAE5]',
    stripeBg: 'from-[#2A7D4F] to-[#34D399]',
    pillBg: 'bg-[#D1FAE5] text-[#065F46]',
    sectionBg: 'bg-[#ECFDF5]',
    divider: 'border-[#BBF7D0]',
    heading: 'text-[#064E3B]',
    sub: 'text-[#065F46]',
    muted: 'text-[#6B7280]',
    chatHeader: 'from-[#2A7D4F] to-[#059669]',
    quickActions: [
      { bg: 'from-[#2A7D4F] to-[#34D399]' },
      { bg: 'from-[#0E7490] to-[#06B6D4]' },
      { bg: 'from-[#4B5563] to-[#6B7280]' },
      { bg: 'from-[#D97706] to-[#F59E0B]' },
      { bg: 'from-[#1C1917] to-[#374151]' },
    ],
    ambient: null,
  },
  Premium: {
    key: 'premium',
    label: 'Premium Mode',
    badge: '✨ Premium',
    pageBg: 'bg-[#FDFBF7]',
    headerBg: 'bg-[#FDFBF7]/80',
    cardBg: 'bg-white',
    cardBorder: 'border-[#E7E5E4]',
    cardHover: 'hover:border-[#C47245]/30 hover:shadow-orange-50',
    accent: '#C47245',
    accentLight: '#FEE2C8',
    accentText: 'text-[#C47245]',
    accentBg: 'bg-[#C47245]',
    accentBgLight: 'bg-[#FEE2C8]',
    stripeBg: 'from-[#C47245] to-[#E8B273]',
    pillBg: 'bg-[#FEE2C8] text-[#7C2D12]',
    sectionBg: 'bg-[#F5F2EB]',
    divider: 'border-[#E7E5E4]',
    heading: 'text-[#1C1917]',
    sub: 'text-[#57534E]',
    muted: 'text-[#78716C]',
    chatHeader: 'from-[#C47245] to-[#A85D38]',
    quickActions: [
      { bg: 'from-[#C47245] to-[#E8B273]' },
      { bg: 'from-[#2A4B5C] to-[#3D6B80]' },
      { bg: 'from-[#86A8B3] to-[#5E8D9C]' },
      { bg: 'from-[#E8B273] to-[#C47245]' },
      { bg: 'from-[#1C1917] to-[#2A4B5C]' },
    ],
    ambient: null,
  },
  Luxury: {
    key: 'luxury',
    label: 'Luxury Mode',
    badge: '👑 Luxury',
    pageBg: 'bg-[#0D0A14]',
    headerBg: 'bg-[#0D0A14]/90',
    cardBg: 'bg-[#1A1425]',
    cardBorder: 'border-[#2D2040]',
    cardHover: 'hover:border-[#9B7FD4]/40 hover:shadow-purple-900/20',
    accent: '#C9A84C',
    accentLight: '#2D2040',
    accentText: 'text-[#C9A84C]',
    accentBg: 'bg-[#C9A84C]',
    accentBgLight: 'bg-[#2D2040]',
    stripeBg: 'from-[#C9A84C] to-[#E8CC80]',
    pillBg: 'bg-[#2D2040] text-[#C9A84C]',
    sectionBg: 'bg-[#130F1E]',
    divider: 'border-[#2D2040]',
    heading: 'text-[#F5F0FF]',
    sub: 'text-[#C4B8D8]',
    muted: 'text-[#7B6B95]',
    chatHeader: 'from-[#2D1F50] to-[#1A1030]',
    quickActions: [
      { bg: 'from-[#C9A84C] to-[#E8CC80]' },
      { bg: 'from-[#4C2D8F] to-[#7B5CC5]' },
      { bg: 'from-[#1A3A5C] to-[#2D5E8F]' },
      { bg: 'from-[#7B3F6E] to-[#B05FA0]' },
      { bg: 'from-[#0D0A14] to-[#2D1F50]' },
    ],
    ambient: true,
  },
};

const detectTheme = (trips) => {
  if (!trips || trips.length === 0) return THEMES.Budget;
  const latest = [...trips].sort((a, b) => new Date(b.created_at) - new Date(a.created_at))[0];
  const level = latest?.preferences?.budget_level || 'Budget';
  return THEMES[level] || THEMES.Budget;
};

/* ─── Luxury ambient particles ───────────────────────────────────── */
const PARTICLES = Array.from({ length: 12 }, (_, i) => ({
  id: i, left: (i * 73 + 11) % 100, size: 1 + (i % 2),
  delay: i * 0.5, dur: 8 + (i % 5),
}));

const LuxuryAmbient = () => (
  <>
    {PARTICLES.map((p) => (
      <motion.span key={p.id}
        className="fixed rounded-full pointer-events-none z-0"
        style={{ left: `${p.left}%`, bottom: '-2%', width: p.size, height: p.size, background: '#C9A84C', opacity: 0.4 }}
        animate={{ y: ['0vh', '-105vh'], opacity: [0, 0.5, 0] }}
        transition={{ duration: p.dur, delay: p.delay, repeat: Infinity, ease: 'easeOut' }}
      />
    ))}
    <div className="fixed inset-0 pointer-events-none z-0">
      <div className="absolute top-1/4 left-1/4 w-96 h-96 rounded-full blur-[120px]"
        style={{ background: 'rgba(75,45,143,0.15)' }} />
      <div className="absolute bottom-1/4 right-1/4 w-80 h-80 rounded-full blur-[100px]"
        style={{ background: 'rgba(201,168,76,0.08)' }} />
    </div>
  </>
);

/* ─── skeleton ───────────────────────────────────────────────────── */
const SkeletonCard = ({ t }) => (
  <div className={`${t.cardBg} rounded-2xl p-6 border ${t.cardBorder} animate-pulse`}>
    <div className="h-1.5 rounded-full mb-5" style={{ background: t.accent + '33', width: '100%' }} />
    <div className="h-5 rounded mb-4" style={{ background: t.accent + '22', width: '70%' }} />
    <div className="space-y-3">
      {[100, 85, 65].map((w, i) => (
        <div key={i} className="h-3 rounded" style={{ background: t.accent + '15', width: `${w}%` }} />
      ))}
    </div>
  </div>
);

const getGreeting = () => {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
};

/* ─────────────────────────────────────────────────────────────────────
   PAGE
───────────────────────────────────────────────────────────────────── */
const DashboardPage = ({ user }) => {
  const navigate = useNavigate();
  const reduce = useReducedMotion();
  const [trips, setTrips] = useState([]);
  const [loading, setLoading] = useState(true);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatMessage, setChatMessage] = useState('');
  const [chatHistory, setChatHistory] = useState([]);
  const [streamingMessage, setStreamingMessage] = useState('');
  const [viewMode, setViewMode] = useState('grid');
  const chatEndRef = useRef(null);

  useEffect(() => { fetchTrips(); }, []);
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory, streamingMessage]);

  /* ── all API calls preserved verbatim ── */
  const fetchTrips = async () => {
    try {
      const response = await axios.get(`${API_URL}/trips`, { withCredentials: true });
      setTrips(response.data.trips);
    } catch (error) {
      console.error('Error fetching trips:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = async () => {
    try {
      await axios.post(`${API_URL}/auth/logout`, {}, { withCredentials: true });
      navigate('/login');
    } catch (error) {
      console.error('Logout error:', error);
    }
  };

  const handleDeleteTrip = async (tripId) => {
    if (!window.confirm('Are you sure you want to delete this trip?')) return;
    try {
      await axios.delete(`${API_URL}/trips/${tripId}`, { withCredentials: true });
      setTrips(trips.filter(t => t.trip_id !== tripId));
    } catch (error) {
      console.error('Error deleting trip:', error);
    }
  };

  const handleSendMessage = async () => {
    if (!chatMessage.trim()) return;
    const userMessage = { role: 'user', content: chatMessage };
    setChatHistory([...chatHistory, userMessage]);
    setChatMessage('');
    setStreamingMessage('');
    try {
      const response = await fetch(`${API_URL}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ message: chatMessage }),
      });
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let fullMessage = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            if (data === '[DONE]') {
              setChatHistory(prev => [...prev, { role: 'assistant', content: fullMessage }]);
              setStreamingMessage('');
              break;
            }
            fullMessage += data;
            setStreamingMessage(fullMessage);
          }
        }
      }
    } catch (error) {
      console.error('Chat error:', error);
      setChatHistory(prev => [...prev, { role: 'assistant', content: 'Sorry, I encountered an error. Please try again.' }]);
      setStreamingMessage('');
    }
  };

  /* ── derive theme from trips ── */
  const t = useMemo(() => detectTheme(trips), [trips]);
  const isLuxury = t.key === 'luxury';
  const firstName = user?.name?.split(' ')[0] || 'Traveler';

  const quickActions = [
    { label: 'Plan Trip', sub: 'AI-powered', Icon: Plus, onClick: () => navigate('/trip-planner'), testId: undefined },
    { label: 'Book', sub: 'Flights & hotels', Icon: Plane, onClick: () => navigate('/bookings'), testId: DASHBOARD.bookingsNav },
    { label: 'Wallet', sub: 'Documents', Icon: Wallet, onClick: () => navigate('/wallet'), testId: DASHBOARD.walletNav },
    { label: 'Rewards', sub: 'Earn points', Icon: Award, onClick: () => navigate('/rewards'), testId: 'rewards-nav' },
    { label: 'Premium', sub: 'Unlock perks', Icon: Crown, onClick: () => navigate('/premium'), testId: 'premium-nav', sparkle: true },
  ];

  return (
    <div
      data-testid={DASHBOARD.dashboardContainer}
      className={`min-h-screen relative transition-colors duration-700 ${t.pageBg}`}
    >
      {/* Luxury ambient layer */}
      {isLuxury && !reduce && <LuxuryAmbient />}

      {/* ── Header ── */}
      <motion.header
        initial={{ y: -60, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
        className={`sticky top-0 z-50 ${t.headerBg} backdrop-blur-xl border-b ${t.divider} shadow-sm transition-colors duration-700`}
      >
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <EYVLogo size="small" />
          <div className="flex items-center gap-3">
            {/* Active theme badge */}
            <motion.span
              key={t.key}
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              className={`hidden sm:inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-full ${t.pillBg} transition-colors duration-700`}
            >
              {t.badge}
            </motion.span>

            {user && (
              <div className="flex items-center gap-3">
                <div className="relative">
                  <img
                    data-testid={AUTH.userAvatar}
                    src={user.picture || 'https://via.placeholder.com/40'}
                    alt={user.name}
                    className="w-10 h-10 rounded-full object-cover"
                    style={{ border: `2px solid ${t.accent}` }}
                  />
                  <span className="absolute -bottom-0.5 -right-0.5 w-3 h-3 bg-green-400 rounded-full border-2 border-white" />
                </div>
                <span className={`hidden md:block font-medium text-sm ${t.heading}`}>{user.name}</span>
              </div>
            )}
            <Button
              data-testid={AUTH.logoutButton}
              onClick={handleLogout}
              variant="ghost"
              className={`${t.muted} hover:${t.accentText} gap-2 transition-all`}
            >
              <LogOut size={18} />
              <span className="hidden sm:inline">Logout</span>
            </Button>
          </div>
        </div>
      </motion.header>

      <div className="relative z-10 max-w-7xl mx-auto px-6 py-10">

        {/* ── Welcome ── */}
        <motion.div className="mb-10" {...fadeUp}>
          <div className="flex items-end justify-between flex-wrap gap-4">
            <div>
              <p className={`text-xs uppercase tracking-[0.22em] font-medium mb-2 ${t.accentText} transition-colors duration-700`}>
                {getGreeting()}
              </p>
              <h1 className={`text-4xl md:text-5xl font-semibold leading-tight ${t.heading} transition-colors duration-700`}
                style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                {firstName}!
              </h1>
              <p className={`mt-2 text-base ${t.sub} transition-colors duration-700`}>
                {trips.length > 0
                  ? `You have ${trips.length} trip${trips.length > 1 ? 's' : ''} planned. Where to next?`
                  : 'Ready to plan your next adventure?'}
              </p>
            </div>
            <div className="flex gap-3 flex-wrap">
              <div className={`${t.cardBg} border ${t.cardBorder} rounded-full px-4 py-2 flex items-center gap-2 text-sm shadow-sm transition-colors duration-700`}>
                <Plane size={14} style={{ color: t.accent }} />
                <span className={`font-medium ${t.heading}`}>{trips.length}</span>
                <span className={t.sub}>trip{trips.length !== 1 ? 's' : ''}</span>
              </div>
              {isLuxury && (
                <div className="bg-[#2D1F50] border border-[#C9A84C]/30 rounded-full px-4 py-2 flex items-center gap-2 text-sm">
                  <Gem size={14} className="text-[#C9A84C]" />
                  <span className="text-[#C9A84C] font-medium">Concierge Ready</span>
                </div>
              )}
              {t.key === 'premium' && (
                <div className="bg-[#FEE2C8] border border-[#C47245]/30 rounded-full px-4 py-2 flex items-center gap-2 text-sm">
                  <Zap size={14} className="text-[#C47245]" />
                  <span className="text-[#C47245] font-medium">Premium Active</span>
                </div>
              )}
            </div>
          </div>

          {/* Luxury VIP banner */}
          {isLuxury && (
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4 }}
              className="mt-6 rounded-2xl px-6 py-4 flex items-center gap-4 border border-[#C9A84C]/30"
              style={{ background: 'linear-gradient(135deg, #1A1030 0%, #2D1F50 100%)' }}
            >
              <Crown size={22} className="text-[#C9A84C] shrink-0" />
              <div>
                <p className="text-[#C9A84C] font-semibold text-sm">VIP Luxury Experience</p>
                <p className="text-[#7B6B95] text-xs mt-0.5">Private jets, butler service & exclusive access — all arranged for you.</p>
              </div>
              <button onClick={() => navigate('/premium')}
                className="ml-auto shrink-0 text-xs font-medium text-[#C9A84C] border border-[#C9A84C]/40 px-4 py-2 rounded-full hover:bg-[#C9A84C]/10 transition-all">
                Explore Perks
              </button>
            </motion.div>
          )}

          {/* Budget tips banner */}
          {t.key === 'budget' && (
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4 }}
              className="mt-6 rounded-2xl px-6 py-4 flex items-center gap-4 border border-[#BBF7D0] bg-[#ECFDF5]"
            >
              <Sparkles size={20} className="text-[#2A7D4F] shrink-0" />
              <div>
                <p className="text-[#064E3B] font-semibold text-sm">Smart Savings Mode</p>
                <p className="text-[#065F46] text-xs mt-0.5">We'll find you the best deals on transport, stays, and activities.</p>
              </div>
            </motion.div>
          )}
        </motion.div>

        {/* ── Quick Actions ── */}
        <motion.div
          className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4 mb-12"
          initial="hidden" animate="show"
          variants={{ hidden: {}, show: { transition: { staggerChildren: 0.08, delayChildren: 0.15 } } }}
          initial="hidden" animate="show"
        >
          {quickActions.map(({ label, sub, Icon, onClick, testId, sparkle }, i) => (
            <motion.button
              key={label}
              data-testid={testId}
              onClick={onClick}
              className={`relative bg-gradient-to-br ${t.quickActions[i]?.bg || 'from-[#C47245] to-[#E8B273]'} text-white p-5 rounded-2xl flex flex-col gap-3 hover:shadow-xl hover:shadow-black/20 transition-all duration-300 overflow-hidden group text-left`}
              variants={staggerItem.variants}
              {...buttonHover}
            >
              <span className="absolute inset-0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700 bg-gradient-to-r from-transparent via-white/15 to-transparent skew-x-12 pointer-events-none" />
              {sparkle && <span className="absolute top-2 right-2 text-yellow-300"><Sparkles size={13} /></span>}
              <div className="bg-white/20 w-10 h-10 rounded-xl flex items-center justify-center backdrop-blur-sm">
                <Icon size={20} />
              </div>
              <div>
                <p className="font-semibold leading-tight"
                  style={{ fontFamily: 'Cormorant Garamond, serif', fontSize: '1.05rem' }}>
                  {label}
                </p>
                <p className="text-white/75 text-xs mt-0.5">{sub}</p>
              </div>
            </motion.button>
          ))}
        </motion.div>

        {/* ── Trips ── */}
        <div data-testid={DASHBOARD.tripsList}>
          <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
            <h2 className={`text-3xl font-medium ${t.heading} transition-colors duration-700`}
              style={{ fontFamily: 'Cormorant Garamond, serif' }}>
              Your Trips
            </h2>
            <div className="flex items-center gap-3">
              {trips.length > 0 && (
                <div className={`flex ${t.cardBg} rounded-full p-1 gap-1 border ${t.cardBorder}`}>
                  {[{ mode: 'grid', Icon: LayoutGrid }, { mode: 'list', Icon: List }].map(({ mode, Icon }) => (
                    <button key={mode} onClick={() => setViewMode(mode)}
                      className={`p-2 rounded-full transition-all ${viewMode === mode ? `shadow-sm` : `${t.muted}`}`}
                      style={viewMode === mode ? { background: t.accent, color: 'white' } : {}}>
                      <Icon size={16} />
                    </button>
                  ))}
                </div>
              )}
              <button onClick={() => navigate('/trip-planner')}
                className="inline-flex items-center gap-2 text-sm font-medium text-white px-4 py-2 rounded-full transition-all hover:shadow-lg active:scale-95"
                style={{ background: t.accent }}>
                <Plus size={16} /> New Trip
              </button>
            </div>
          </div>

          {loading ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {[1, 2, 3].map(i => <SkeletonCard key={i} t={t} />)}
            </div>
          ) : trips.length === 0 ? (
            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
              className={`text-center py-20 ${t.cardBg} rounded-3xl border ${t.cardBorder} border-dashed transition-colors duration-700`}>
              <div className="w-20 h-20 rounded-full flex items-center justify-center mx-auto mb-5"
                style={{ background: t.accent + '18' }}>
                <MapPin size={36} style={{ color: t.accent }} />
              </div>
              <h3 className={`text-2xl font-medium mb-2 ${t.heading}`}
                style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                No trips yet
              </h3>
              <p className={`${t.sub} mb-6`}>Start planning your first vacation!</p>
              <button onClick={() => navigate('/trip-planner')}
                className="inline-flex items-center gap-2 text-white px-6 py-3 rounded-full font-medium hover:shadow-lg active:scale-95 transition-all"
                style={{ background: t.accent }}>
                <Sparkles size={16} /> Plan with AI
              </button>
            </motion.div>
          ) : viewMode === 'grid' ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              <AnimatePresence>
                {trips.map((trip, idx) => (
                  <motion.div key={trip.trip_id}
                    data-testid={DASHBOARD.tripCard}
                    initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.95 }} transition={{ delay: idx * 0.07 }}
                    className={`${t.cardBg} rounded-2xl p-6 border ${t.cardBorder} ${t.cardHover} hover:shadow-xl transition-all cursor-pointer group`}
                    whileHover={{ y: -5 }}
                    onClick={() => navigate(`/trip-results/${trip.trip_id}`)}>
                    <div className={`h-1.5 w-full rounded-full bg-gradient-to-r ${t.stripeBg} mb-5 opacity-60 group-hover:opacity-100 transition-opacity`} />
                    <div className="flex items-start justify-between mb-4">
                      <h3 className={`text-xl font-medium leading-tight pr-2 ${t.heading}`}
                        style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                        {trip.trip_name}
                      </h3>
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDeleteTrip(trip.trip_id); }}
                        className={`opacity-0 group-hover:opacity-100 transition-opacity ${t.muted} hover:text-red-500 p-1 rounded-lg hover:bg-red-50 shrink-0`}>
                        <Trash2 size={16} />
                      </button>
                    </div>
                    <div className="space-y-2.5 text-sm">
                      {[
                        { Icon: MapPin, text: trip.preferences.destination },
                        { Icon: Calendar, text: `${trip.preferences.departure_date} → ${trip.preferences.return_date}` },
                        { Icon: DollarSign, text: `${trip.plans?.length || 0} plans available` },
                      ].map(({ Icon, text }, i) => (
                        <div key={i} className={`flex items-center gap-2 ${t.sub}`}>
                          <Icon size={15} style={{ color: t.accent }} className="shrink-0" />
                          <span className="truncate">{text}</span>
                        </div>
                      ))}
                    </div>
                    <div className={`mt-4 pt-4 border-t ${t.divider} flex items-center justify-between`}>
                      <div className={`flex items-center gap-1.5 text-xs ${t.muted}`}>
                        <Clock size={12} />
                        {new Date(trip.created_at).toLocaleDateString()}
                      </div>
                      <span className={`text-xs font-medium opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1`}
                        style={{ color: t.accent }}>
                        View <ChevronRight size={12} />
                      </span>
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          ) : (
            <div className="space-y-3">
              <AnimatePresence>
                {trips.map((trip, idx) => (
                  <motion.div key={trip.trip_id}
                    data-testid={DASHBOARD.tripCard}
                    initial={{ opacity: 0, x: -16 }} animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: 16 }} transition={{ delay: idx * 0.05 }}
                    className={`${t.cardBg} rounded-2xl px-6 py-4 border ${t.cardBorder} ${t.cardHover} hover:shadow-md transition-all cursor-pointer group flex items-center gap-4`}
                    onClick={() => navigate(`/trip-results/${trip.trip_id}`)}>
                    <div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
                      style={{ background: t.accent + '18' }}>
                      <MapPin size={18} style={{ color: t.accent }} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className={`font-medium truncate ${t.heading}`}
                        style={{ fontFamily: 'Cormorant Garamond, serif', fontSize: '1.1rem' }}>
                        {trip.trip_name}
                      </h3>
                      <p className={`text-xs mt-0.5 truncate ${t.muted}`}>
                        {trip.preferences.destination} · {trip.preferences.departure_date} → {trip.preferences.return_date}
                      </p>
                    </div>
                    <div className={`hidden sm:flex items-center gap-4 text-xs ${t.muted} shrink-0`}>
                      <span>{trip.plans?.length || 0} plans</span>
                      <span>{new Date(trip.created_at).toLocaleDateString()}</span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <button onClick={(e) => { e.stopPropagation(); handleDeleteTrip(trip.trip_id); }}
                        className={`opacity-0 group-hover:opacity-100 transition-opacity ${t.muted} hover:text-red-500 p-1.5 rounded-lg hover:bg-red-50`}>
                        <Trash2 size={15} />
                      </button>
                      <ChevronRight size={16} className={`${t.muted} opacity-0 group-hover:opacity-100 transition-opacity`} />
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          )}
        </div>
      </div>

      {/* ── AI Chat FAB ── */}
      <motion.button
        data-testid={DASHBOARD.chatButton}
        onClick={() => setChatOpen(!chatOpen)}
        className="fixed bottom-6 right-6 text-white p-4 rounded-full shadow-2xl transition-all z-40"
        style={{ background: t.accent, boxShadow: `0 8px 32px -8px ${t.accent}80` }}
        whileHover={{ scale: 1.1 }}
        whileTap={{ scale: 0.95 }}
      >
        <AnimatePresence mode="wait">
          <motion.span key={chatOpen ? 'close' : 'open'}
            initial={{ rotate: -90, opacity: 0 }} animate={{ rotate: 0, opacity: 1 }}
            exit={{ rotate: 90, opacity: 0 }} transition={{ duration: 0.2 }}>
            {chatOpen ? <X size={26} /> : <MessageCircle size={26} />}
          </motion.span>
        </AnimatePresence>
      </motion.button>

      {/* ── AI Chat Panel ── */}
      <AnimatePresence>
        {chatOpen && (
          <motion.div
            initial={{ opacity: 0, y: 24, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.95 }}
            transition={{ type: 'spring', stiffness: 320, damping: 28 }}
            className={`fixed bottom-24 right-6 w-[22rem] md:w-96 h-[520px] ${t.cardBg} rounded-3xl shadow-2xl border ${t.cardBorder} flex flex-col z-40 overflow-hidden transition-colors duration-700`}
          >
            <div className={`relative px-5 py-4 bg-gradient-to-r ${t.chatHeader} text-white shrink-0`}>
              <div className="absolute inset-0 opacity-10"
                style={{ backgroundImage: 'radial-gradient(circle at 80% 50%, white 1px, transparent 1px)', backgroundSize: '20px 20px' }} />
              <div className="relative flex items-center gap-3">
                <div className="w-9 h-9 rounded-full bg-white/20 flex items-center justify-center">
                  <Sparkles size={18} />
                </div>
                <div>
                  <h3 className="font-semibold text-base" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                    AI Travel Assistant
                  </h3>
                  <p className="text-white/75 text-xs">Ask me anything about your trips!</p>
                </div>
              </div>
            </div>

            <div className={`flex-1 overflow-y-auto px-4 py-4 space-y-3 ${t.sectionBg}`}>
              {chatHistory.length === 0 && (
                <div className={`text-center py-10 ${t.sub}`}>
                  <div className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-3"
                    style={{ background: t.accent + '18' }}>
                    <Sparkles size={28} style={{ color: t.accent }} />
                  </div>
                  <p className={`font-medium ${t.heading} mb-1`}>How can I help?</p>
                  <p className={`text-xs ${t.muted}`}>Ask about destinations, itineraries, or travel tips.</p>
                </div>
              )}
              {chatHistory.map((msg, idx) => (
                <motion.div key={idx}
                  initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                  className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[82%] px-4 py-3 rounded-2xl text-sm leading-relaxed ${
                    msg.role === 'user'
                      ? 'text-white rounded-br-sm'
                      : `${t.cardBg} ${t.heading} border ${t.cardBorder} rounded-bl-sm shadow-sm`
                  }`}
                    style={msg.role === 'user' ? { background: t.accent } : {}}>
                    {msg.content}
                  </div>
                </motion.div>
              ))}
              {streamingMessage && (
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex justify-start">
                  <div className={`max-w-[82%] px-4 py-3 rounded-2xl rounded-bl-sm ${t.cardBg} ${t.heading} border ${t.cardBorder} shadow-sm text-sm leading-relaxed`}>
                    {streamingMessage}
                    <span className="inline-block w-1.5 h-4 ml-1 animate-pulse rounded-sm align-middle"
                      style={{ background: t.accent }} />
                  </div>
                </motion.div>
              )}
              <div ref={chatEndRef} />
            </div>

            <div className={`px-4 py-3 ${t.cardBg} border-t ${t.divider} shrink-0`}>
              <div className="flex gap-2 items-center">
                <Input
                  data-testid={DASHBOARD.chatInput}
                  value={chatMessage}
                  onChange={(e) => setChatMessage(e.target.value)}
                  onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()}
                  placeholder="Ask me anything..."
                  className={`flex-1 rounded-xl text-sm ${t.heading}`}
                  style={{ borderColor: t.cardBorder }}
                />
                <Button onClick={handleSendMessage}
                  className="rounded-xl px-3 shrink-0 transition-all hover:opacity-90 hover:shadow-md active:scale-95 text-white"
                  style={{ background: t.accent }}>
                  <Send size={18} />
                </Button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default DashboardPage;
