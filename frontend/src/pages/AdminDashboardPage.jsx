import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  ShieldCheck, 
  Activity, 
  Layers, 
  Send, 
  LifeBuoy, 
  TrendingUp, 
  FileText, 
  CheckCircle2, 
  XCircle, 
  AlertTriangle, 
  Lock, 
  RefreshCw, 
  LogOut,
  Sparkles,
  ExternalLink,
  Clock,
  Eye
} from 'lucide-react';
import axios from 'axios';
import { toast } from 'sonner';

const API_BASE = process.env.REACT_APP_BACKEND_URL || '';

export default function AdminDashboardPage() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [adminKey, setAdminKey] = useState('');
  const [isVerifying, setIsVerifying] = useState(false);
  const [activeTab, setActiveTab] = useState('queue');
  
  // Dashboard Data State
  const [stats, setStats] = useState(null);
  const [queueItems, setQueueItems] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const [tickets, setTickets] = useState([]);
  const [analyticsEvents, setAnalyticsEvents] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [sessionToken, setSessionToken] = useState(null);

  // Bob Draft Creator Form
  const [bobForm, setBobForm] = useState({
    destination: 'Goa',
    discount_percent: 20,
    theme: 'beach_getaway',
    channel: 'multi_channel',
    custom_headline: '',
    custom_caption: '',
  });
  const [isGeneratingDraft, setIsGeneratingDraft] = useState(false);

  // Setup Axios Auth Headers/Credentials
  const getAuthHeaders = useCallback(() => {
    const headers = {};
    if (sessionToken) {
      headers['Authorization'] = `Bearer ${sessionToken}`;
    }
    return headers;
  }, [sessionToken]);

  // Fetch Dashboard Stats & Active Tab Data
  const fetchData = useCallback(async () => {
    if (!isAuthenticated) return;
    try {
      const headers = getAuthHeaders();
      const statsRes = await axios.get(`${API_BASE}/api/admin/dashboard-stats`, { headers, withCredentials: true });
      setStats(statsRes.data);

      if (activeTab === 'queue') {
        const res = await axios.get(`${API_BASE}/api/admin/queue`, { headers, withCredentials: true });
        setQueueItems(res.data.items || []);
      } else if (activeTab === 'marketing') {
        const res = await axios.get(`${API_BASE}/api/admin/marketing/campaigns`, { headers, withCredentials: true });
        setCampaigns(res.data.campaigns || []);
      } else if (activeTab === 'support') {
        const res = await axios.get(`${API_BASE}/api/admin/support/tickets`, { headers, withCredentials: true });
        setTickets(res.data.tickets || []);
      } else if (activeTab === 'analytics') {
        const res = await axios.get(`${API_BASE}/api/admin/analytics/events`, { headers, withCredentials: true });
        setAnalyticsEvents(res.data.events || []);
      } else if (activeTab === 'audit') {
        const res = await axios.get(`${API_BASE}/api/admin/audit-log`, { headers, withCredentials: true });
        setAuditLogs(res.data.logs || []);
      }
    } catch (err) {
      if (err.response?.status === 401 || err.response?.status === 403) {
        setIsAuthenticated(false);
        setSessionToken(null);
        toast.error('Admin session expired. Please re-authenticate.');
      }
    }
  }, [isAuthenticated, activeTab, getAuthHeaders]);

  // Periodic 15-second Polling for Health & Data (Laptop-initiated, no WebSockets)
  useEffect(() => {
    if (isAuthenticated) {
      fetchData();
      const interval = setInterval(fetchData, 15000);
      return () => clearInterval(interval);
    }
  }, [isAuthenticated, fetchData]);

  // Verify Admin Key & Exchange for 2-hour Session
  const handleVerify = async (e) => {
    e.preventDefault();
    if (!adminKey.trim()) return;
    setIsVerifying(true);
    try {
      const res = await axios.post(
        `${API_BASE}/api/admin/verify`,
        { admin_key: adminKey.trim() },
        { withCredentials: true }
      );
      if (res.data.authenticated) {
        setIsAuthenticated(true);
        setSessionToken(res.data.session_token);
        setAdminKey(''); // Clear raw key from form
        toast.success('Admin authentication verified. Welcome, Abhinay.');
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Invalid admin key. Access denied.');
    } finally {
      setIsVerifying(false);
    }
  };

  // Logout Admin
  const handleLogout = async () => {
    try {
      await axios.post(`${API_BASE}/api/admin/logout`, {}, { headers: getAuthHeaders(), withCredentials: true });
    } catch (_) {}
    setIsAuthenticated(false);
    setSessionToken(null);
    toast.info('Logged out from admin console.');
  };

  // Execute JARVIS Decision (Approve / Reject)
  const handleDecision = async (queueItemId, actionType, campaignId = null) => {
    try {
      setIsLoading(true);
      const action = { type: actionType };
      if (campaignId) action.campaign_id = campaignId;

      const payload = {
        queue_item_id: queueItemId,
        action,
        reason: actionType === 'execute_campaign' ? 'Approved via Admin Panel' : 'Rejected via Admin Panel',
        resolution_status: actionType === 'execute_campaign' ? 'resolved' : 'rejected',
      };

      const res = await axios.post(`${API_BASE}/api/admin/decisions`, payload, {
        headers: getAuthHeaders(),
        withCredentials: true,
      });

      if (res.data.status === 'recorded') {
        toast.success(actionType === 'execute_campaign' ? 'Campaign approved & executed live!' : 'Queue item dismissed.');
        fetchData();
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to execute decision.');
    } finally {
      setIsLoading(false);
    }
  };

  // Bob: Generate Campaign Draft
  const handleGenerateDraft = async (e) => {
    e.preventDefault();
    try {
      setIsGeneratingDraft(true);
      const res = await axios.post(
        `${API_BASE}/api/admin/marketing/generate`,
        bobForm,
        { headers: getAuthHeaders(), withCredentials: true }
      );
      toast.success(`Draft created for ${bobForm.destination}! Enqueued for approval.`);
      setActiveTab('queue');
      fetchData();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to generate campaign draft.');
    } finally {
      setIsGeneratingDraft(false);
    }
  };

  // ── Authentication Modal ──────────────────────────────────────────────────
  if (!isAuthenticated) {
    return (
      <div className="min-h-screen bg-[#07090E] flex items-center justify-center p-4">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="max-w-md w-full bg-[#0F141F] border border-slate-800 rounded-2xl p-8 shadow-2xl"
        >
          <div className="flex items-center justify-center mb-6">
            <div className="h-14 w-14 rounded-2xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
              <ShieldCheck className="h-8 w-8" />
            </div>
          </div>
          <h1 className="text-2xl font-semibold text-center text-white mb-2">EYV Admin Console</h1>
          <p className="text-slate-400 text-sm text-center mb-8">
            Multi-Agent Autonomous Command Surface (JARVIS, Denver, Bob, Sara)
          </p>

          <form onSubmit={handleVerify} className="space-y-4">
            <div>
              <label className="block text-xs uppercase tracking-wider text-slate-400 font-medium mb-2">
                Master Admin Key
              </label>
              <div className="relative">
                <input
                  type="password"
                  value={adminKey}
                  onChange={(e) => setAdminKey(e.target.value)}
                  placeholder="Enter ADMIN_API_KEY..."
                  className="w-full bg-[#161C2B] border border-slate-700 rounded-xl px-4 py-3 pl-11 text-white placeholder-slate-500 focus:outline-none focus:border-amber-500 transition-colors"
                  required
                />
                <Lock className="absolute left-4 top-3.5 h-4 w-4 text-slate-500" />
              </div>
            </div>

            <button
              type="submit"
              disabled={isVerifying}
              className="w-full py-3 px-4 bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-600 hover:to-amber-700 text-slate-950 font-semibold rounded-xl transition-all shadow-lg shadow-amber-500/20 disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {isVerifying ? (
                <>
                  <RefreshCw className="h-4 w-4 animate-spin" /> Verifying...
                </>
              ) : (
                <>
                  <ShieldCheck className="h-4 w-4" /> Authenticate Session
                </>
              )}
            </button>
          </form>

          <div className="mt-8 pt-6 border-t border-slate-800/80 text-center">
            <p className="text-xs text-slate-500">
              Target Host: <span className="text-slate-400 font-mono">eyv-website-2.vercel.app</span>
            </p>
          </div>
        </motion.div>
      </div>
    );
  }

  // ── Authenticated Admin Control Panel ─────────────────────────────────────
  return (
    <div className="min-h-screen bg-[#07090E] text-slate-100 flex flex-col">
      {/* Top Navigation Bar */}
      <header className="border-b border-slate-800 bg-[#0B0F17]/90 backdrop-blur sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <span className="font-bold text-white text-base tracking-tight">EYV Brain Center</span>
              <span className="ml-2 px-2 py-0.5 rounded-full text-[10px] font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                LIVE
              </span>
            </div>
          </div>

          {/* Active Agents Status Indicators */}
          <div className="hidden md:flex items-center gap-4 text-xs">
            <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-800/60 border border-slate-700/50">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-slate-300">Denver</span>
            </span>
            <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-800/60 border border-slate-700/50">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-slate-300">Bob</span>
            </span>
            <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-800/60 border border-slate-700/50">
              <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-slate-300">Sara</span>
            </span>
            <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-300 font-medium">
              JARVIS Coordinator
            </span>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={fetchData}
              className="p-2 rounded-xl bg-slate-800/80 hover:bg-slate-700 text-slate-300 transition-colors"
              title="Refresh Data"
            >
              <RefreshCw className="h-4 w-4" />
            </button>
            <button
              onClick={handleLogout}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 text-xs font-medium transition-colors"
            >
              <LogOut className="h-3.5 w-3.5" /> Logout
            </button>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Stat Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          <div className="bg-[#0F141F] border border-slate-800 rounded-xl p-4">
            <span className="text-xs text-slate-400 font-medium">Pending Approvals</span>
            <div className="flex items-baseline gap-2 mt-1">
              <span className="text-2xl font-bold text-white">{stats?.pending_queue_count ?? '—'}</span>
              {stats?.p1_urgent_count > 0 && (
                <span className="text-xs text-rose-400 font-semibold">({stats.p1_urgent_count} P1 Urgent)</span>
              )}
            </div>
          </div>
          <div className="bg-[#0F141F] border border-slate-800 rounded-xl p-4">
            <span className="text-xs text-slate-400 font-medium">Bob Campaigns</span>
            <div className="flex items-baseline gap-2 mt-1">
              <span className="text-2xl font-bold text-white">{stats?.marketing_campaigns_published ?? '—'}</span>
              <span className="text-xs text-slate-400">/ {stats?.marketing_campaigns_total ?? '—'} total</span>
            </div>
          </div>
          <div className="bg-[#0F141F] border border-slate-800 rounded-xl p-4">
            <span className="text-xs text-slate-400 font-medium">Denver Open Tickets</span>
            <div className="text-2xl font-bold text-white mt-1">{stats?.open_tickets_count ?? '—'}</div>
          </div>
          <div className="bg-[#0F141F] border border-slate-800 rounded-xl p-4">
            <span className="text-xs text-slate-400 font-medium">Sara Webhook Events (24h)</span>
            <div className="text-2xl font-bold text-white mt-1">{stats?.revenuecat_events_24h ?? '—'}</div>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center gap-2 border-b border-slate-800 mb-6 overflow-x-auto pb-2">
          {[
            { id: 'queue', label: 'JARVIS Queue', icon: Layers, badge: stats?.pending_queue_count },
            { id: 'marketing', label: 'Bob Marketing Studio', icon: Send },
            { id: 'support', label: 'Denver Support Desk', icon: LifeBuoy },
            { id: 'analytics', label: 'Sara Analytics Stream', icon: TrendingUp },
            { id: 'audit', label: 'Immutable Audit Trail', icon: FileText },
          ].map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium transition-all whitespace-nowrap ${
                  isActive
                    ? 'bg-amber-500 text-slate-950 shadow-md shadow-amber-500/20'
                    : 'text-slate-400 hover:text-white hover:bg-slate-800/60'
                }`}
              >
                <Icon className="h-4 w-4" />
                {tab.label}
                {tab.badge > 0 && (
                  <span
                    className={`px-1.5 py-0.2 rounded-full text-[10px] font-bold ${
                      isActive ? 'bg-slate-950 text-amber-400' : 'bg-rose-500 text-white'
                    }`}
                  >
                    {tab.badge}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* TAB 1: JARVIS Unified Queue */}
        {activeTab === 'queue' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-lg font-semibold text-white">Pending Coordination Queue</h2>
              <span className="text-xs text-slate-400">Sorted by Priority & Oldest First</span>
            </div>

            {queueItems.length === 0 ? (
              <div className="bg-[#0F141F] border border-slate-800 rounded-2xl p-12 text-center">
                <CheckCircle2 className="h-12 w-12 text-emerald-400 mx-auto mb-3 opacity-80" />
                <h3 className="text-white font-medium mb-1">Queue is clear!</h3>
                <p className="text-sm text-slate-400">No pending decisions or escalation items awaiting sign-off.</p>
              </div>
            ) : (
              queueItems.map((item) => {
                const isP1 = item.priority === 1;
                const isBobCampaign = item.source_agent === 'bob' && item.item_type === 'campaign_approval';
                const campaignId = item.payload?.campaign_id;

                return (
                  <div
                    key={item.id}
                    className={`bg-[#0F141F] border rounded-2xl p-5 transition-all ${
                      isP1 ? 'border-rose-500/40 shadow-lg shadow-rose-500/5' : 'border-slate-800'
                    }`}
                  >
                    <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span
                            className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                              isP1
                                ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                                : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                            }`}
                          >
                            Priority {item.priority} {isP1 ? '• EMERGENCY' : '• NORMAL'}
                          </span>
                          <span className="px-2 py-0.5 rounded-full text-[10px] bg-slate-800 text-slate-300 font-mono uppercase">
                            {item.source_agent}
                          </span>
                          <span className="text-xs text-slate-500 font-mono">#{item.id.slice(-6)}</span>
                        </div>
                        <h3 className="text-base font-semibold text-white">
                          {item.payload?.summary || item.payload?.title || item.item_type}
                        </h3>
                        {item.payload?.details && (
                          <p className="text-xs text-slate-400">{JSON.stringify(item.payload.details)}</p>
                        )}
                        {item.payload?.destination && (
                          <div className="flex items-center gap-3 text-xs text-slate-300 mt-2">
                            <span>📍 Destination: {item.payload.destination}</span>
                            {item.payload.discount_percent && (
                              <span>🎟 Discount: {item.payload.discount_percent}%</span>
                            )}
                            {item.payload.channel && <span>📢 Channel: {item.payload.channel}</span>}
                          </div>
                        )}
                      </div>

                      {/* Action Buttons */}
                      <div className="flex items-center gap-2 self-end md:self-center">
                        <button
                          onClick={() => handleDecision(item.id, 'execute_campaign', campaignId)}
                          disabled={isLoading}
                          className="flex items-center gap-1.5 px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-slate-950 font-semibold rounded-xl text-xs transition-colors shadow-md shadow-emerald-500/10"
                        >
                          <CheckCircle2 className="h-3.5 w-3.5" /> Approve & Execute
                        </button>
                        <button
                          onClick={() => handleDecision(item.id, 'reject', campaignId)}
                          disabled={isLoading}
                          className="flex items-center gap-1.5 px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs transition-colors"
                        >
                          <XCircle className="h-3.5 w-3.5" /> Reject
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        )}

        {/* TAB 2: Bob Marketing Studio */}
        {activeTab === 'marketing' && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            {/* Draft Generator Form */}
            <div className="bg-[#0F141F] border border-slate-800 rounded-2xl p-6 h-fit">
              <div className="flex items-center gap-2 mb-4">
                <Send className="h-5 w-5 text-amber-400" />
                <h2 className="text-base font-semibold text-white">Draft Campaign with Bob</h2>
              </div>
              <form onSubmit={handleGenerateDraft} className="space-y-4 text-xs">
                <div>
                  <label className="block text-slate-400 font-medium mb-1">Destination</label>
                  <select
                    value={bobForm.destination}
                    onChange={(e) => setBobForm({ ...bobForm, destination: e.target.value })}
                    className="w-full bg-[#161C2B] border border-slate-700 rounded-xl px-3 py-2 text-white focus:outline-none focus:border-amber-500"
                  >
                    <option value="Goa">Goa (Beaches)</option>
                    <option value="Kerala">Kerala (Backwaters)</option>
                    <option value="Manali">Manali (Mountains)</option>
                    <option value="Jaipur">Jaipur (Royal Palaces)</option>
                    <option value="Ladakh">Ladakh (Adventure)</option>
                    <option value="Kashmir">Kashmir (Paradise)</option>
                    <option value="Bali">Bali (Tropical)</option>
                    <option value="Dubai">Dubai (Luxury)</option>
                  </select>
                </div>

                <div>
                  <label className="block text-slate-400 font-medium mb-1">
                    Discount Percentage ({bobForm.discount_percent}%)
                  </label>
                  <input
                    type="range"
                    min="5"
                    max="50"
                    step="5"
                    value={bobForm.discount_percent}
                    onChange={(e) => setBobForm({ ...bobForm, discount_percent: parseFloat(e.target.value) })}
                    className="w-full accent-amber-500"
                  />
                  {bobForm.discount_percent > 20 && (
                    <span className="text-[10px] text-amber-400 block mt-1">
                      ⚠️ Disount &gt; 20% enqueues with Priority 1 Emergency Review.
                    </span>
                  )}
                </div>

                <div>
                  <label className="block text-slate-400 font-medium mb-1">Theme</label>
                  <select
                    value={bobForm.theme}
                    onChange={(e) => setBobForm({ ...bobForm, theme: e.target.value })}
                    className="w-full bg-[#161C2B] border border-slate-700 rounded-xl px-3 py-2 text-white focus:outline-none focus:border-amber-500"
                  >
                    <option value="beach_getaway">Beach Getaway</option>
                    <option value="mountain_escape">Mountain Escape</option>
                    <option value="monsoon_retreat">Monsoon Retreat</option>
                    <option value="luxury_experience">Luxury Experience</option>
                  </select>
                </div>

                <div>
                  <label className="block text-slate-400 font-medium mb-1">Target Channel</label>
                  <select
                    value={bobForm.channel}
                    onChange={(e) => setBobForm({ ...bobForm, channel: e.target.value })}
                    className="w-full bg-[#161C2B] border border-slate-700 rounded-xl px-3 py-2 text-white focus:outline-none focus:border-amber-500"
                  >
                    <option value="multi_channel">Multi-Channel (Buffer + IG)</option>
                    <option value="instagram">Instagram Graph API</option>
                    <option value="buffer">Buffer Social Scheduler</option>
                    <option value="whatsapp">WhatsApp Business API</option>
                    <option value="promo_code">Promotion Coupon Only</option>
                  </select>
                </div>

                <button
                  type="submit"
                  disabled={isGeneratingDraft}
                  className="w-full py-2.5 bg-amber-500 hover:bg-amber-600 text-slate-950 font-semibold rounded-xl transition-all shadow-md shadow-amber-500/20 disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {isGeneratingDraft ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                  Generate Draft with Bob
                </button>
              </form>
            </div>

            {/* Campaign Catalog */}
            <div className="lg:col-span-2 space-y-4">
              <h2 className="text-base font-semibold text-white">Campaign Catalog</h2>
              {campaigns.length === 0 ? (
                <div className="bg-[#0F141F] border border-slate-800 rounded-2xl p-8 text-center text-slate-400 text-sm">
                  No marketing campaigns created yet.
                </div>
              ) : (
                campaigns.map((camp) => (
                  <div key={camp.id} className="bg-[#0F141F] border border-slate-800 rounded-2xl p-4 flex gap-4">
                    {camp.content?.image_url && (
                      <img
                        src={camp.content.image_url}
                        alt={camp.title}
                        className="h-20 w-20 rounded-xl object-cover bg-slate-800"
                      />
                    )}
                    <div className="flex-1 space-y-1">
                      <div className="flex items-center gap-2">
                        <span
                          className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${
                            camp.status === 'published'
                              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                              : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                          }`}
                        >
                          {camp.status}
                        </span>
                        <span className="text-xs text-slate-400 font-medium">{camp.channel}</span>
                      </div>
                      <h4 className="text-sm font-semibold text-white">{camp.title}</h4>
                      <p className="text-xs text-slate-400 line-clamp-2">{camp.content?.caption}</p>
                      {camp.discount_config?.code && (
                        <span className="inline-block mt-1 font-mono text-[10px] bg-slate-800 px-2 py-0.5 rounded text-amber-300">
                          Promo: {camp.discount_config.code} ({camp.discount_config.discount_value}% OFF)
                        </span>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {/* TAB 3: Denver Support Desk */}
        {activeTab === 'support' && (
          <div className="space-y-4">
            <h2 className="text-base font-semibold text-white">Denver Support & Ticket Feed</h2>
            {tickets.length === 0 ? (
              <div className="bg-[#0F141F] border border-slate-800 rounded-2xl p-8 text-center text-slate-400 text-sm">
                No support tickets recorded.
              </div>
            ) : (
              tickets.map((ticket) => (
                <div key={ticket.id} className="bg-[#0F141F] border border-slate-800 rounded-2xl p-4 space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-800 text-slate-300 uppercase">
                        {ticket.category || 'ticket'}
                      </span>
                      <span className="text-sm font-semibold text-white">{ticket.title}</span>
                    </div>
                    <span className="text-xs font-mono text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-full">
                      Reporters: {ticket.reporters_count || 1}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400">{ticket.description}</p>
                </div>
              ))
            )}
          </div>
        )}

        {/* TAB 4: Sara Analytics Stream */}
        {activeTab === 'analytics' && (
          <div className="space-y-4">
            <h2 className="text-base font-semibold text-white">Sara Subscription & RevenueCat Webhooks Stream</h2>
            <div className="bg-[#0F141F] border border-slate-800 rounded-2xl overflow-hidden">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-900/60 border-b border-slate-800 text-slate-400 font-medium uppercase tracking-wider">
                  <tr>
                    <th className="px-4 py-3">Event Type</th>
                    <th className="px-4 py-3">App User ID</th>
                    <th className="px-4 py-3">Price / Currency</th>
                    <th className="px-4 py-3">Environment</th>
                    <th className="px-4 py-3">Created At</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-mono">
                  {analyticsEvents.length === 0 ? (
                    <tr>
                      <td colSpan="5" className="px-4 py-6 text-center text-slate-500">
                        No RevenueCat events recorded yet.
                      </td>
                    </tr>
                  ) : (
                    analyticsEvents.map((evt) => (
                      <tr key={evt.id} className="hover:bg-slate-800/30">
                        <td className="px-4 py-3 font-semibold text-white">{evt.event_type}</td>
                        <td className="px-4 py-3 text-slate-300">{evt.app_user_id}</td>
                        <td className="px-4 py-3 text-slate-300">
                          {evt.price_in_purchased_currency ? `${evt.price_in_purchased_currency} ${evt.currency || 'USD'}` : '—'}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] ${
                              evt.environment === 'SANDBOX'
                                ? 'bg-amber-500/10 text-amber-400'
                                : 'bg-emerald-500/10 text-emerald-400'
                            }`}
                          >
                            {evt.environment}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-500">{evt.created_at}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* TAB 5: Immutable Audit Trail */}
        {activeTab === 'audit' && (
          <div className="space-y-4">
            <h2 className="text-base font-semibold text-white">Immutable Admin Audit Log</h2>
            <div className="bg-[#0F141F] border border-slate-800 rounded-2xl overflow-hidden">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-900/60 border-b border-slate-800 text-slate-400 font-medium uppercase tracking-wider">
                  <tr>
                    <th className="px-4 py-3">Timestamp</th>
                    <th className="px-4 py-3">Admin</th>
                    <th className="px-4 py-3">Route / Action</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">IP Address</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60 font-mono">
                  {auditLogs.length === 0 ? (
                    <tr>
                      <td colSpan="5" className="px-4 py-6 text-center text-slate-500">
                        No audit records recorded yet.
                      </td>
                    </tr>
                  ) : (
                    auditLogs.map((log) => (
                      <tr key={log.id} className="hover:bg-slate-800/30">
                        <td className="px-4 py-3 text-slate-400">{log.timestamp}</td>
                        <td className="px-4 py-3 text-amber-300">{log.admin_identity}</td>
                        <td className="px-4 py-3 text-white">
                          <span className="font-semibold">{log.method}</span> {log.route} ({log.action})
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`px-1.5 py-0.5 rounded ${
                              log.status_code === 200 ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'
                            }`}
                          >
                            {log.status_code}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-500">{log.client_ip}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
