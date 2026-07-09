import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, MapPin, Calendar, DollarSign, LogOut, MessageCircle, Send, X, Sparkles, Trash2, Plane, Wallet, Award, Crown } from 'lucide-react';
import { API_URL } from '../constants';
import { DASHBOARD, AUTH } from '../constants/testIds';
import EYVLogo from '../components/EYVLogo';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { fadeUp, staggerItem, buttonHover } from '../constants/motion';

const DashboardPage = ({ user }) => {
  const navigate = useNavigate();
  const [trips, setTrips] = useState([]);
  const [loading, setLoading] = useState(true);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatMessage, setChatMessage] = useState('');
  const [chatHistory, setChatHistory] = useState([]);
  const [streamingMessage, setStreamingMessage] = useState('');
  const chatEndRef = useRef(null);

  useEffect(() => {
    fetchTrips();
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory, streamingMessage]);

  const fetchTrips = async () => {
    try {
      const response = await axios.get(`${API_URL}/trips`, {
        withCredentials: true,
      });
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
      await axios.delete(`${API_URL}/trips/${tripId}`, {
        withCredentials: true,
      });
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
        headers: {
          'Content-Type': 'application/json',
        },
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

  return (
    <div data-testid={DASHBOARD.dashboardContainer} className="min-h-screen bg-[#FDFBF7]">
      {/* Header */}
      <div className="glass sticky top-0 z-50 border-b border-[#E7E5E4]">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <EYVLogo size="small" />
          <div className="flex items-center gap-4">
            {user && (
              <div className="flex items-center gap-3">
                <img
                  data-testid={AUTH.userAvatar}
                  src={user.picture || 'https://via.placeholder.com/40'}
                  alt={user.name}
                  className="w-10 h-10 rounded-full border-2 border-[#C47245]"
                />
                <span className="hidden md:block text-[#1C1917] font-medium">{user.name}</span>
              </div>
            )}
            <Button
              data-testid={AUTH.logoutButton}
              onClick={handleLogout}
              variant="ghost"
              className="text-[#57534E]"
            >
              <LogOut size={20} />
              Logout
            </Button>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-12">
        {/* Welcome Section */}
        <motion.div className="mb-12" {...fadeUp}>
          <h1 className="text-5xl font-semibold text-[#1C1917] mb-4" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
            Welcome back, {user?.name?.split(' ')[0]}!
          </h1>
          <p className="text-lg text-[#57534E]">Ready to plan your next adventure?</p>
        </motion.div>

        {/* Quick Actions */}
        <motion.div
          className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 mb-12"
          initial="hidden"
          animate="visible"
          variants={{
            hidden: {},
            visible: { transition: { staggerChildren: 0.08, delayChildren: 0.15 } },
          }}
        >
          <motion.button
            onClick={() => navigate('/trip-planner')}
            className="bg-gradient-to-br from-[#C47245] to-[#E8B273] text-white p-6 rounded-2xl flex items-center justify-between hover:shadow-xl transition-shadow"
            variants={staggerItem.variants}
            {...buttonHover}
          >
            <div className="flex items-center gap-3">
              <div className="bg-white/20 p-3 rounded-full">
                <Plus size={20} />
              </div>
              <div className="text-left">
                <h3 className="text-base font-medium" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Plan Trip
                </h3>
                <p className="text-white/90 text-xs">AI-powered</p>
              </div>
            </div>
          </motion.button>

          <motion.button
            data-testid={DASHBOARD.bookingsNav}
            onClick={() => navigate('/bookings')}
            className="bg-[#2A4B5C] text-white p-6 rounded-2xl flex items-center justify-between hover:shadow-xl transition-shadow"
            variants={staggerItem.variants}
            {...buttonHover}
          >
            <div className="flex items-center gap-3">
              <div className="bg-white/20 p-3 rounded-full">
                <Plane size={20} />
              </div>
              <div className="text-left">
                <h3 className="text-base font-medium" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Book
                </h3>
                <p className="text-white/90 text-xs">Flights & hotels</p>
              </div>
            </div>
          </motion.button>

          <motion.button
            data-testid={DASHBOARD.walletNav}
            onClick={() => navigate('/wallet')}
            className="bg-[#86A8B3] text-white p-6 rounded-2xl flex items-center justify-between hover:shadow-xl transition-shadow"
            variants={staggerItem.variants}
            {...buttonHover}
          >
            <div className="flex items-center gap-3">
              <div className="bg-white/20 p-3 rounded-full">
                <Wallet size={20} />
              </div>
              <div className="text-left">
                <h3 className="text-base font-medium" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Wallet
                </h3>
                <p className="text-white/90 text-xs">Documents</p>
              </div>
            </div>
          </motion.button>

          <motion.button
            data-testid="rewards-nav"
            onClick={() => navigate('/rewards')}
            className="bg-gradient-to-br from-[#E8B273] to-[#C47245] text-white p-6 rounded-2xl flex items-center justify-between hover:shadow-xl transition-shadow"
            variants={staggerItem.variants}
            {...buttonHover}
          >
            <div className="flex items-center gap-3">
              <div className="bg-white/20 p-3 rounded-full">
                <Award size={20} />
              </div>
              <div className="text-left">
                <h3 className="text-base font-medium" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Rewards
                </h3>
                <p className="text-white/90 text-xs">Earn points</p>
              </div>
            </div>
          </motion.button>

          <motion.button
            data-testid="premium-nav"
            onClick={() => navigate('/premium')}
            className="bg-gradient-to-br from-[#1C1917] to-[#2A4B5C] text-white p-6 rounded-2xl flex items-center justify-between hover:shadow-xl transition-shadow relative overflow-hidden"
            variants={staggerItem.variants}
            {...buttonHover}
          >
            <div className="absolute top-1 right-1 text-yellow-400">
              <Sparkles size={14} />
            </div>
            <div className="flex items-center gap-3">
              <div className="bg-white/20 p-3 rounded-full">
                <Crown size={20} />
              </div>
              <div className="text-left">
                <h3 className="text-base font-medium" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Premium
                </h3>
                <p className="text-white/90 text-xs">Unlock perks</p>
              </div>
            </div>
          </motion.button>
        </motion.div>

        {/* Trips List */}
        <div data-testid={DASHBOARD.tripsList}>
          <h2 className="text-3xl font-medium text-[#2A4B5C] mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
            Your Trips
          </h2>
          {loading ? (
            <div className="text-center py-12">
              <div className="animate-spin h-12 w-12 border-4 border-[#C47245] border-t-transparent rounded-full mx-auto"></div>
            </div>
          ) : trips.length === 0 ? (
            <div className="text-center py-12 bg-white rounded-2xl border border-[#E7E5E4]">
              <MapPin size={48} className="mx-auto text-[#E7E5E4] mb-4" />
              <p className="text-[#57534E] text-lg">No trips yet. Start planning your first vacation!</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {trips.map((trip) => (
                <motion.div
                  key={trip.trip_id}
                  data-testid={DASHBOARD.tripCard}
                  className="bg-white rounded-2xl p-6 border border-[#E7E5E4] hover:shadow-xl transition-all cursor-pointer group"
                  whileHover={{ y: -5 }}
                  onClick={() => navigate(`/trip-results/${trip.trip_id}`)}
                >
                  <div className="flex items-start justify-between mb-4">
                    <h3 className="text-xl font-medium text-[#1C1917]" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                      {trip.trip_name}
                    </h3>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeleteTrip(trip.trip_id);
                      }}
                      className="opacity-0 group-hover:opacity-100 transition-opacity text-red-500 hover:text-red-700"
                    >
                      <Trash2 size={18} />
                    </button>
                  </div>
                  <div className="space-y-2 text-sm text-[#57534E]">
                    <div className="flex items-center gap-2">
                      <MapPin size={16} />
                      <span>{trip.preferences.destination}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Calendar size={16} />
                      <span>{trip.preferences.departure_date} to {trip.preferences.return_date}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <DollarSign size={16} />
                      <span>{trip.plans?.length || 0} plans available</span>
                    </div>
                  </div>
                  <div className="mt-4 pt-4 border-t border-[#E7E5E4] text-xs text-[#57534E]">
                    Created {new Date(trip.created_at).toLocaleDateString()}
                  </div>
                </motion.div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* AI Chat Button */}
      <motion.button
        data-testid={DASHBOARD.chatButton}
        onClick={() => setChatOpen(!chatOpen)}
        className="fixed bottom-6 right-6 bg-[#C47245] text-white p-4 rounded-full shadow-2xl hover:bg-[#A85D38] transition-all z-40"
        whileHover={{ scale: 1.1 }}
        whileTap={{ scale: 0.95 }}
      >
        {chatOpen ? <X size={28} /> : <MessageCircle size={28} />}
      </motion.button>

      {/* AI Chat Panel */}
      <AnimatePresence>
        {chatOpen && (
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.95 }}
            className="fixed bottom-24 right-6 w-96 h-[500px] bg-white rounded-2xl shadow-2xl border border-[#E7E5E4] flex flex-col z-40"
          >
            <div className="p-4 border-b border-[#E7E5E4] bg-[#C47245] text-white rounded-t-2xl">
              <h3 className="text-lg font-medium" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                AI Travel Assistant
              </h3>
              <p className="text-sm text-white/80">Ask me anything about your trips!</p>
            </div>
            
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {chatHistory.length === 0 && (
                <div className="text-center text-[#57534E] py-8">
                  <Sparkles size={32} className="mx-auto text-[#C47245] mb-2" />
                  <p>Start a conversation!</p>
                </div>
              )}
              {chatHistory.map((msg, idx) => (
                <div
                  key={idx}
                  className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[80%] p-3 rounded-xl ${
                      msg.role === 'user'
                        ? 'bg-[#C47245] text-white'
                        : 'bg-[#F5F2EB] text-[#1C1917]'
                    }`}
                  >
                    {msg.content}
                  </div>
                </div>
              ))}
              {streamingMessage && (
                <div className="flex justify-start">
                  <div className="max-w-[80%] p-3 rounded-xl bg-[#F5F2EB] text-[#1C1917]">
                    {streamingMessage}
                  </div>
                </div>
              )}
              <div ref={chatEndRef} />
            </div>

            <div className="p-4 border-t border-[#E7E5E4]">
              <div className="flex gap-2">
                <Input
                  data-testid={DASHBOARD.chatInput}
                  value={chatMessage}
                  onChange={(e) => setChatMessage(e.target.value)}
                  onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()}
                  placeholder="Ask me anything..."
                  className="flex-1"
                />
                <Button
                  onClick={handleSendMessage}
                  className="bg-[#C47245] hover:bg-[#A85D38]"
                >
                  <Send size={20} />
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
