import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Plus, MapPin, Calendar, DollarSign, LogOut, MessageCircle, Send, X,
  Sparkles, Trash2, Plane, Wallet, Award, Crown, ChevronRight,
  Clock, LayoutGrid, List,
} from 'lucide-react';
import { API_URL } from '../constants';
import { DASHBOARD, AUTH } from '../constants/testIds';
import EYVLogo from '../components/EYVLogo';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { fadeUp, staggerItem, buttonHover } from '../constants/motion';

/* ─── tiny helpers ───────────────────────────────────────────────── */

const SkeletonCard = () => (
  <div className="bg-white rounded-2xl p-6 border border-[#E7E5E4] animate-pulse">
    <div className="h-5 bg-[#E7E5E4] rounded w-3/4 mb-4" />
    <div className="space-y-3">
      <div className="h-3 bg-[#E7E5E4] rounded w-full" />
      <div className="h-3 bg-[#E7E5E4] rounded w-5/6" />
      <div className="h-3 bg-[#E7E5E4] rounded w-4/6" />
    </div>
    <div className="mt-4 pt-4 border-t border-[#E7E5E4]">
      <div className="h-3 bg-[#E7E5E4] rounded w-2/5" />
    </div>
  </div>
);

const getGreeting = () => {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
};

/* ─── Page ───────────────────────────────────────────────────────── */

const DashboardPage = ({ user }) => {
  const navigate = useNavigate();
  const [trips, setTrips] = useState([]);
  const [loading, setLoading] = useState(true);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatMessage, setChatMessage] = useState('');
  const [chatHistory, setChatHistory] = useState([]);
  const [streamingMessage, setStreamingMessage] = useState('');
  const [viewMode, setViewMode] = useState('grid'); // 'grid' | 'list'
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

  /* ── quick-action nav cards ── */
  const quickActions = [
    {
      label: 'Plan Trip', sub: 'AI-powered', Icon: Plus,
      bg: 'from-[#C47245] to-[#E8B273]',
      onClick: () => navigate('/trip-planner'),
      testId: undefined,
    },
    {
      label: 'Book', sub: 'Flights & hotels', Icon: Plane,
      bg: 'from-[#2A4B5C] to-[#3D6B80]',
      onClick: () => navigate('/bookings'),
      testId: DASHBOARD.bookingsNav,
    },
    {
      label: 'Wallet', sub: 'Documents', Icon: Wallet,
      bg: 'from-[#86A8B3] to-[#5E8D9C]',
      onClick: () => navigate('/wallet'),
      testId: DASHBOARD.walletNav,
    },
    {
      label: 'Rewards', sub: 'Earn points', Icon: Award,
      bg: 'from-[#E8B273] to-[#C47245]',
      onClick: () => navigate('/rewards'),
      testId: 'rewards-nav',
    },
    {
      label: 'Premium', sub: 'Unlock perks', Icon: Crown,
      bg: 'from-[#1C1917] to-[#2A4B5C]',
      onClick: () => navigate('/premium'),
      testId: 'premium-nav',
      sparkle: true,
    },
  ];

  const firstName = user?.name?.split(' ')[0] || 'Traveler';

  return (
    <div data-testid={DASHBOARD.dashboardContainer} className="min-h-screen bg-[#FDFBF7]">

      {/* ── Header ── */}
      <motion.header
        initial={{ y: -60, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
        className="sticky top-0 z-50 bg-[#FDFBF7]/80 backdrop-blur-xl border-b border-[#E7E5E4] shadow-[0_4px_24px_-8px_rgba(28,25,23,0.1)]"
      >
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <EYVLogo size="small" />
          <div className="flex items-center gap-4">
            {user && (
              <div className="flex items-center gap-3">
                <div className="relative">
                  <img
                    data-testid={AUTH.userAvatar}
                    src={user.picture || 'https://via.placeholder.com/40'}
                    alt={user.name}
                    className="w-10 h-10 rounded-full border-2 border-[#C47245] object-cover"
                  />
                  <span className="absolute -bottom-0.5 -right-0.5 w-3 h-3 bg-green-400 rounded-full border-2 border-white" />
                </div>
                <span className="hidden md:block text-[#1C1917] font-medium text-sm">{user.name}</span>
              </div>
            )}
            <Button
              data-testid={AUTH.logoutButton}
              onClick={handleLogout}
              variant="ghost"
              className="text-[#57534E] hover:text-[#C47245] hover:bg-[#C47245]/8 gap-2 transition-all"
            >
              <LogOut size={18} />
              <span className="hidden sm:inline">Logout</span>
            </Button>
          </div>
        </div>
      </motion.header>

      <div className="max-w-7xl mx-auto px-6 py-10">

        {/* ── Welcome ── */}
        <motion.div className="mb-10" {...fadeUp}>
          <div className="flex items-end justify-between flex-wrap gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.22em] text-[#C47245] font-medium mb-2">
                {getGreeting()}
              </p>
              <h1 className="text-4xl md:text-5xl font-semibold text-[#1C1917] leading-tight"
                style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                {firstName}!
              </h1>
              <p className="text-[#57534E] mt-2 text-base">
                {trips.length > 0
                  ? `You have ${trips.length} trip${trips.length > 1 ? 's' : ''} planned. Where to next?`
                  : 'Ready to plan your next adventure?'}
              </p>
            </div>
            {/* mini stat pills */}
            <div className="flex gap-3 flex-wrap">
              <div className="bg-white border border-[#E7E5E4] rounded-full px-4 py-2 flex items-center gap-2 text-sm shadow-sm">
                <Plane size={14} className="text-[#C47245]" />
                <span className="font-medium text-[#1C1917]">{trips.length}</span>
                <span className="text-[#57534E]">trip{trips.length !== 1 ? 's' : ''}</span>
              </div>
              <div className="bg-white border border-[#E7E5E4] rounded-full px-4 py-2 flex items-center gap-2 text-sm shadow-sm">
                <Sparkles size={14} className="text-[#C47245]" />
                <span className="text-[#57534E]">AI Ready</span>
              </div>
            </div>
          </div>
        </motion.div>

        {/* ── Quick Actions ── */}
        <motion.div
          className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4 mb-12"
          initial="hidden"
          animate="visible"
          variants={{
            hidden: {},
            visible: { transition: { staggerChildren: 0.08, delayChildren: 0.15 } },
          }}
        >
          {quickActions.map(({ label, sub, Icon, bg, onClick, testId, sparkle }) => (
            <motion.button
              key={label}
              data-testid={testId}
              onClick={onClick}
              className={`relative bg-gradient-to-br ${bg} text-white p-5 rounded-2xl flex flex-col gap-3 hover:shadow-xl hover:shadow-black/15 transition-all duration-300 overflow-hidden group text-left`}
              variants={staggerItem.variants}
              {...buttonHover}
            >
              {/* Shine sweep on hover */}
              <span className="absolute inset-0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700 bg-gradient-to-r from-transparent via-white/15 to-transparent skew-x-12 pointer-events-none" />
              {sparkle && (
                <span className="absolute top-2 right-2 text-yellow-300">
                  <Sparkles size={13} />
                </span>
              )}
              <div className="bg-white/20 w-10 h-10 rounded-xl flex items-center justify-center backdrop-blur-sm">
                <Icon size={20} />
              </div>
              <div>
                <p className="font-semibold text-sm leading-tight"
                  style={{ fontFamily: 'Cormorant Garamond, serif', fontSize: '1.05rem' }}>
                  {label}
                </p>
                <p className="text-white/75 text-xs mt-0.5">{sub}</p>
              </div>
            </motion.button>
          ))}
        </motion.div>

        {/* ── Trips section ── */}
        <div data-testid={DASHBOARD.tripsList}>
          <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
            <h2 className="text-3xl font-medium text-[#2A4B5C]"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}>
              Your Trips
            </h2>
            <div className="flex items-center gap-3">
              {/* View toggle */}
              {trips.length > 0 && (
                <div className="flex bg-[#F5F2EB] rounded-full p-1 gap-1">
                  <button onClick={() => setViewMode('grid')}
                    className={`p-2 rounded-full transition-all ${viewMode === 'grid' ? 'bg-white shadow-sm text-[#C47245]' : 'text-[#57534E]'}`}>
                    <LayoutGrid size={16} />
                  </button>
                  <button onClick={() => setViewMode('list')}
                    className={`p-2 rounded-full transition-all ${viewMode === 'list' ? 'bg-white shadow-sm text-[#C47245]' : 'text-[#57534E]'}`}>
                    <List size={16} />
                  </button>
                </div>
              )}
              <button onClick={() => navigate('/trip-planner')}
                className="inline-flex items-center gap-2 text-sm font-medium text-white bg-[#C47245] hover:bg-[#A85D38] px-4 py-2 rounded-full transition-all hover:shadow-lg active:scale-95">
                <Plus size={16} /> New Trip
              </button>
            </div>
          </div>

          {loading ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {[1, 2, 3].map((i) => <SkeletonCard key={i} />)}
            </div>
          ) : trips.length === 0 ? (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="text-center py-20 bg-white rounded-3xl border border-[#E7E5E4] border-dashed"
            >
              <div className="w-20 h-20 rounded-full bg-[#F5F2EB] flex items-center justify-center mx-auto mb-5">
                <MapPin size={36} className="text-[#C47245]" />
              </div>
              <h3 className="text-2xl font-medium text-[#1C1917] mb-2"
                style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                No trips yet
              </h3>
              <p className="text-[#57534E] mb-6">Start planning your first vacation!</p>
              <button onClick={() => navigate('/trip-planner')}
                className="inline-flex items-center gap-2 bg-[#C47245] text-white px-6 py-3 rounded-full font-medium hover:bg-[#A85D38] transition-all hover:shadow-lg active:scale-95">
                <Sparkles size={16} /> Plan with AI
              </button>
            </motion.div>
          ) : viewMode === 'grid' ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              <AnimatePresence>
                {trips.map((trip, idx) => (
                  <motion.div
                    key={trip.trip_id}
                    data-testid={DASHBOARD.tripCard}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.95 }}
                    transition={{ delay: idx * 0.07 }}
                    className="bg-white rounded-2xl p-6 border border-[#E7E5E4] hover:border-[#C47245]/30 hover:shadow-xl transition-all cursor-pointer group"
                    whileHover={{ y: -5 }}
                    onClick={() => navigate(`/trip-results/${trip.trip_id}`)}
                  >
                    {/* Card top stripe */}
                    <div className="h-1.5 w-full rounded-full bg-gradient-to-r from-[#C47245] to-[#E8B273] mb-5 opacity-60 group-hover:opacity-100 transition-opacity" />

                    <div className="flex items-start justify-between mb-4">
                      <h3 className="text-xl font-medium text-[#1C1917] leading-tight pr-2"
                        style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                        {trip.trip_name}
                      </h3>
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDeleteTrip(trip.trip_id); }}
                        className="opacity-0 group-hover:opacity-100 transition-opacity text-[#57534E] hover:text-red-500 p-1 rounded-lg hover:bg-red-50 shrink-0"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>

                    <div className="space-y-2.5 text-sm text-[#57534E]">
                      <div className="flex items-center gap-2">
                        <MapPin size={15} className="text-[#C47245] shrink-0" />
                        <span className="truncate">{trip.preferences.destination}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Calendar size={15} className="text-[#C47245] shrink-0" />
                        <span>{trip.preferences.departure_date} → {trip.preferences.return_date}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <DollarSign size={15} className="text-[#C47245] shrink-0" />
                        <span>{trip.plans?.length || 0} plans available</span>
                      </div>
                    </div>

                    <div className="mt-4 pt-4 border-t border-[#E7E5E4] flex items-center justify-between">
                      <div className="flex items-center gap-1.5 text-xs text-[#57534E]">
                        <Clock size={12} />
                        {new Date(trip.created_at).toLocaleDateString()}
                      </div>
                      <span className="text-xs text-[#C47245] font-medium opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1">
                        View <ChevronRight size={12} />
                      </span>
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          ) : (
            /* List view */
            <div className="space-y-3">
              <AnimatePresence>
                {trips.map((trip, idx) => (
                  <motion.div
                    key={trip.trip_id}
                    data-testid={DASHBOARD.tripCard}
                    initial={{ opacity: 0, x: -16 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: 16 }}
                    transition={{ delay: idx * 0.05 }}
                    className="bg-white rounded-2xl px-6 py-4 border border-[#E7E5E4] hover:border-[#C47245]/30 hover:shadow-md transition-all cursor-pointer group flex items-center gap-4"
                    onClick={() => navigate(`/trip-results/${trip.trip_id}`)}
                  >
                    <div className="w-10 h-10 rounded-xl bg-[#C47245]/10 flex items-center justify-center shrink-0">
                      <MapPin size={18} className="text-[#C47245]" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className="font-medium text-[#1C1917] truncate"
                        style={{ fontFamily: 'Cormorant Garamond, serif', fontSize: '1.1rem' }}>
                        {trip.trip_name}
                      </h3>
                      <p className="text-xs text-[#57534E] mt-0.5 truncate">
                        {trip.preferences.destination} · {trip.preferences.departure_date} → {trip.preferences.return_date}
                      </p>
                    </div>
                    <div className="hidden sm:flex items-center gap-4 text-xs text-[#57534E] shrink-0">
                      <span>{trip.plans?.length || 0} plans</span>
                      <span>{new Date(trip.created_at).toLocaleDateString()}</span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDeleteTrip(trip.trip_id); }}
                        className="opacity-0 group-hover:opacity-100 transition-opacity text-[#57534E] hover:text-red-500 p-1.5 rounded-lg hover:bg-red-50"
                      >
                        <Trash2 size={15} />
                      </button>
                      <ChevronRight size={16} className="text-[#57534E] opacity-0 group-hover:opacity-100 transition-opacity" />
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
        className="fixed bottom-6 right-6 bg-[#C47245] text-white p-4 rounded-full shadow-2xl shadow-[#C47245]/30 hover:bg-[#A85D38] transition-all z-40"
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
            className="fixed bottom-24 right-6 w-[22rem] md:w-96 h-[520px] bg-white rounded-3xl shadow-[0_24px_60px_-12px_rgba(28,25,23,0.3)] border border-[#E7E5E4] flex flex-col z-40 overflow-hidden"
          >
            {/* Chat header */}
            <div className="relative px-5 py-4 bg-gradient-to-r from-[#C47245] to-[#A85D38] text-white shrink-0">
              <div className="absolute inset-0 opacity-10"
                style={{ backgroundImage: 'radial-gradient(circle at 80% 50%, white 1px, transparent 1px)', backgroundSize: '20px 20px' }} />
              <div className="relative flex items-center gap-3">
                <div className="w-9 h-9 rounded-full bg-white/20 flex items-center justify-center">
                  <Sparkles size={18} />
                </div>
                <div>
                  <h3 className="font-semibold text-base leading-tight"
                    style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                    AI Travel Assistant
                  </h3>
                  <p className="text-white/75 text-xs">Ask me anything about your trips!</p>
                </div>
              </div>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3 bg-[#FDFBF7]">
              {chatHistory.length === 0 && (
                <div className="text-center text-[#57534E] py-10">
                  <div className="w-14 h-14 rounded-2xl bg-[#C47245]/10 flex items-center justify-center mx-auto mb-3">
                    <Sparkles size={28} className="text-[#C47245]" />
                  </div>
                  <p className="font-medium text-[#1C1917] mb-1">How can I help?</p>
                  <p className="text-xs text-[#57534E]">Ask about destinations, itineraries, or travel tips.</p>
                </div>
              )}
              {chatHistory.map((msg, idx) => (
                <motion.div key={idx}
                  initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                  className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[82%] px-4 py-3 rounded-2xl text-sm leading-relaxed ${
                    msg.role === 'user'
                      ? 'bg-[#C47245] text-white rounded-br-sm'
                      : 'bg-white text-[#1C1917] border border-[#E7E5E4] rounded-bl-sm shadow-sm'
                  }`}>
                    {msg.content}
                  </div>
                </motion.div>
              ))}
              {streamingMessage && (
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex justify-start">
                  <div className="max-w-[82%] px-4 py-3 rounded-2xl rounded-bl-sm bg-white text-[#1C1917] border border-[#E7E5E4] shadow-sm text-sm leading-relaxed">
                    {streamingMessage}
                    <span className="inline-block w-1.5 h-4 bg-[#C47245] ml-1 animate-pulse rounded-sm align-middle" />
                  </div>
                </motion.div>
              )}
              <div ref={chatEndRef} />
            </div>

            {/* Input */}
            <div className="px-4 py-3 bg-white border-t border-[#E7E5E4] shrink-0">
              <div className="flex gap-2 items-center">
                <Input
                  data-testid={DASHBOARD.chatInput}
                  value={chatMessage}
                  onChange={(e) => setChatMessage(e.target.value)}
                  onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()}
                  placeholder="Ask me anything..."
                  className="flex-1 rounded-xl border-[#E7E5E4] focus:border-[#C47245] focus:ring-[#C47245]/20 text-sm"
                />
                <Button
                  onClick={handleSendMessage}
                  className="bg-[#C47245] hover:bg-[#A85D38] rounded-xl px-3 shrink-0 transition-all hover:shadow-md active:scale-95"
                >
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
