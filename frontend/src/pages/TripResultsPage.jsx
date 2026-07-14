import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowLeft, DollarSign, Plane, Hotel, Utensils, Activity,
  Calendar, MapPin, Check, ChevronDown, ChevronUp, Sparkles,
} from 'lucide-react';
import { API_URL } from '../constants';
import { TRIP_PLANNER } from '../constants/testIds';
import TripLoadingScreen from '../components/TripLoadingScreen';
import { Button } from '../components/ui/button';
import EYVLogo from '../components/EYVLogo';
import TripMap from '../components/TripMap';

/* ─── plan colour config ─────────────────────────────────────────── */
const PLAN_STYLES = {
  Budget:  { ring: 'border-[#2A7D4F]',  bg: 'bg-[#F0FBF4]',  accent: '#2A7D4F',  badge: 'bg-[#D1FAE5] text-[#065F46]' },
  Premium: { ring: 'border-[#C47245]',  bg: 'bg-[#FDF6F0]',  accent: '#C47245',  badge: 'bg-[#FEE2C8] text-[#7C2D12]' },
  Luxury:  { ring: 'border-[#7C5CBF]',  bg: 'bg-[#FAF6FF]',  accent: '#7C5CBF',  badge: 'bg-[#EDE9FE] text-[#4C1D95]' },
};
const planStyle = (type) => PLAN_STYLES[type] || PLAN_STYLES.Premium;

/* ─── collapsible day card ───────────────────────────────────────── */
const DayCard = ({ day, details, formatCost, accent }) => {
  const [open, setOpen] = useState(true);
  return (
    <div className="rounded-2xl border border-[#E7E5E4] overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-6 py-4 bg-[#F5F2EB] hover:bg-[#EDE9E0] transition-colors"
      >
        <div className="flex items-baseline gap-3">
          <h4 className="text-lg font-semibold text-[#1C1917]"
            style={{ fontFamily: 'Cormorant Garamond, serif' }}>
            {day.replace('_', ' ').toUpperCase()}
            {details.date && ` — ${details.date}`}
          </h4>
          {details.daily_total != null && (
            <span className="text-sm font-medium" style={{ color: accent }}>
              {formatCost(details.daily_total)}
            </span>
          )}
        </div>
        {open ? <ChevronUp size={18} className="text-[#57534E]" /> : <ChevronDown size={18} className="text-[#57534E]" />}
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3 }}
            className="overflow-hidden"
          >
            <div className="px-6 py-5 space-y-5">
              {/* Transportation */}
              {details.transportation && (
                <div>
                  <div className="flex items-center gap-2 mb-2" style={{ color: accent }}>
                    <Plane size={16} />
                    <span className="text-sm font-semibold uppercase tracking-wider">Transportation</span>
                  </div>
                  <p className="text-sm text-[#57534E] ml-6">
                    <span className="font-medium capitalize">{details.transportation.mode}:</span>{' '}
                    {details.transportation.details}
                    {details.transportation.cost != null && (
                      <span className="font-medium" style={{ color: accent }}> — {formatCost(details.transportation.cost)}</span>
                    )}
                  </p>
                </div>
              )}

              {/* Activities */}
              {details.activities?.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-2" style={{ color: accent }}>
                    <Activity size={16} />
                    <span className="text-sm font-semibold uppercase tracking-wider">Activities</span>
                  </div>
                  <div className="space-y-1.5 ml-6">
                    {details.activities.map((a, i) => (
                      <p key={i} className="text-sm text-[#57534E]">
                        <span className="font-medium">{a.time}:</span> {a.activity}
                        {a.location && ` at ${a.location}`}
                        {a.cost != null && (
                          <span className="font-medium" style={{ color: accent }}>
                            {' '}— {a.cost === 0 ? 'Free' : formatCost(a.cost)}
                          </span>
                        )}
                      </p>
                    ))}
                  </div>
                </div>
              )}

              {/* Accommodation */}
              {details.accommodation && (
                <div>
                  <div className="flex items-center gap-2 mb-2" style={{ color: accent }}>
                    <Hotel size={16} />
                    <span className="text-sm font-semibold uppercase tracking-wider">Accommodation</span>
                  </div>
                  <p className="text-sm text-[#57534E] ml-6">
                    {details.accommodation.name} ({details.accommodation.type})
                    {details.accommodation.cost != null && (
                      <span className="font-medium" style={{ color: accent }}> — {formatCost(details.accommodation.cost)}</span>
                    )}
                  </p>
                </div>
              )}

              {/* Meals */}
              {details.meals?.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-2" style={{ color: accent }}>
                    <Utensils size={16} />
                    <span className="text-sm font-semibold uppercase tracking-wider">Meals</span>
                  </div>
                  <div className="space-y-1.5 ml-6">
                    {details.meals.map((m, i) => (
                      <p key={i} className="text-sm text-[#57534E]">
                        <span className="font-medium capitalize">{m.time}:</span> {m.restaurant}
                        {m.cuisine && ` (${m.cuisine})`}
                        {m.cost != null && (
                          <span className="font-medium" style={{ color: accent }}> — {formatCost(m.cost)}</span>
                        )}
                      </p>
                    ))}
                  </div>
                </div>
              )}

              {/* Cumulative total */}
              {details.cumulative_total != null && (
                <div className="pt-3 border-t border-[#E7E5E4] flex justify-between text-sm text-[#57534E]">
                  <span>Cumulative trip total</span>
                  <span className="font-medium" style={{ color: accent }}>{formatCost(details.cumulative_total)}</span>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

/* ─── Page ───────────────────────────────────────────────────────── */
const TripResultsPage = () => {
  const { tripId } = useParams();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [trip, setTrip] = useState(null);
  const [selectedPlan, setSelectedPlan] = useState(null);
  const [mapCenter, setMapCenter] = useState(null);
  const [mapMarkers, setMapMarkers] = useState([]);
  const [regenerating, setRegenerating] = useState(false);
  const [regenerateError, setRegenerateError] = useState(null);

  useEffect(() => { fetchTrip(); }, [tripId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (trip?.preferences?.destination) {
      fetchDestinationCoords(trip.preferences.destination);
    }
  }, [trip]);

  /* ── API calls — preserved verbatim ── */
  const fetchDestinationCoords = async (destination) => {
    try {
      const response = await axios.get(
        `${API_URL}/destinations/${encodeURIComponent(destination)}/coords`,
        { withCredentials: true }
      );
      const { lat, lng } = response.data;
      setMapCenter([lat, lng]);
      setMapMarkers([{ lat, lng, title: destination, description: 'Your destination' }]);
    } catch (error) {
      console.error('Coords fetch error:', error);
    }
  };

  const fetchTrip = async () => {
    try {
      const response = await axios.get(`${API_URL}/trips/${tripId}`, { withCredentials: true });
      setTrip(response.data);
      setSelectedPlan(response.data.plans[1]); // Default to Premium
    } catch (error) {
      console.error('Error fetching trip:', error);
    } finally {
      setLoading(false);
    }
  };

  // One click = one server-side attempt (which itself retries a few times
  // with backoff before giving up - see generate_single_plan). No client-side
  // retry loop here on purpose - the user drives each further attempt.
  const handleRegenerate = async (planType) => {
    setRegenerating(true);
    setRegenerateError(null);
    try {
      const response = await axios.post(
        `${API_URL}/trips/${tripId}/regenerate/${planType}`,
        {},
        { withCredentials: true }
      );
      const freshPlan = response.data.plan;
      setTrip((prev) => ({
        ...prev,
        plans: prev.plans.map((p) => (p.plan_type === planType ? freshPlan : p)),
      }));
      setSelectedPlan(freshPlan);
    } catch (error) {
      console.error('Error regenerating plan:', error);
      setRegenerateError(
        error.response?.data?.detail || `${planType} plan regeneration failed, please try again.`
      );
    } finally {
      setRegenerating(false);
    }
  };

  /* ── loading state — cinematic screen ── */
  if (loading) {
    return (
      <TripLoadingScreen
        destination={trip?.preferences?.destination || 'your destination'}
      />
    );
  }

  if (!trip) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#FDFBF7]">
        <div className="text-center">
          <p className="text-xl text-[#57534E] mb-4">Trip not found</p>
          <Button onClick={() => navigate('/dashboard')} className="bg-[#C47245] hover:bg-[#A85D38]">
            Back to Dashboard
          </Button>
        </div>
      </div>
    );
  }

  const ps = planStyle(selectedPlan?.plan_type);
  const currencySymbol = selectedPlan?.currency_symbol || (selectedPlan?.currency === 'INR' ? '₹' : '$');
  const formatCost = (val) => `${currencySymbol}${(val ?? 0).toLocaleString()}`;

  return (
    <div data-testid={TRIP_PLANNER.plannerForm} className="min-h-screen bg-[#FDFBF7]">

      {/* ── Header ── */}
      <div className="sticky top-0 z-50 bg-[#FDFBF7]/80 backdrop-blur-xl border-b border-[#E7E5E4] shadow-sm">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <Button onClick={() => navigate('/dashboard')} variant="ghost"
            className="text-[#57534E] hover:text-[#C47245] gap-2">
            <ArrowLeft size={18} /> Back to Dashboard
          </Button>
          <EYVLogo size="small" />
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-12">

        {/* ── Trip header ── */}
        <motion.div className="mb-12"
          initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }}>
          <span className="text-xs uppercase tracking-[0.25em] font-medium text-[#C47245]">Your Trip</span>
          <h1 className="text-5xl md:text-6xl font-semibold text-[#1C1917] mt-2 mb-4 leading-tight"
            style={{ fontFamily: 'Cormorant Garamond, serif' }}>
            {trip.trip_name}
          </h1>
          <div className="flex flex-wrap items-center gap-5 text-[#57534E]">
            <div className="flex items-center gap-2">
              <MapPin size={17} className="text-[#C47245]" />
              <span>{trip.preferences.destination}</span>
            </div>
            <div className="flex items-center gap-2">
              <Calendar size={17} className="text-[#C47245]" />
              <span>{trip.preferences.departure_date} → {trip.preferences.return_date}</span>
            </div>
          </div>
        </motion.div>

        {/* ── Plan selection ── */}
        <motion.div className="mb-12"
          initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, delay: 0.1 }}>
          <h2 className="text-3xl font-medium text-[#2A4B5C] mb-6"
            style={{ fontFamily: 'Cormorant Garamond, serif' }}>
            Choose Your Plan
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {trip.plans.map((plan, idx) => {
              const style = planStyle(plan.plan_type);
              const active = selectedPlan?.plan_type === plan.plan_type;
              return (
                <motion.div
                  key={idx}
                  data-testid={`${plan.plan_type.toLowerCase()}-plan-card`}
                  onClick={() => { setSelectedPlan(plan); setRegenerateError(null); }}
                  className={`relative p-6 rounded-2xl border-2 cursor-pointer transition-all hover:shadow-xl ${
                    active ? `${style.ring} ${style.bg}` : 'border-[#E7E5E4] hover:border-[#C47245]/30'
                  }`}
                  whileHover={{ y: -5 }}
                >
                  {active && (
                    <motion.div
                      layoutId="plan-check"
                      className="absolute -top-3 -right-3 text-white rounded-full p-1.5"
                      style={{ background: style.accent }}
                    >
                      <Check size={18} />
                    </motion.div>
                  )}
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-2xl font-medium text-[#1C1917]"
                      style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                      {plan.plan_type}
                    </h3>
                    <span className={`text-xs font-semibold px-3 py-1 rounded-full ${style.badge}`}>
                      {plan.plan_type === 'Budget' ? '💚' : plan.plan_type === 'Premium' ? '✨' : '👑'}
                    </span>
                  </div>
                  {plan.generation_failed ? (
                    <div className="mb-4 text-sm font-medium text-red-600">
                      Generation failed — tap to see details
                    </div>
                  ) : (
                    <div className="flex items-baseline gap-1 mb-4">
                      <span className="text-2xl font-semibold" style={{ color: style.accent }}>
                        {plan.currency_symbol || (plan.currency === 'INR' ? '₹' : '$')}
                      </span>
                      <span className="text-4xl font-semibold text-[#1C1917]">
                        {plan.total_cost?.toLocaleString() || 'N/A'}
                      </span>
                    </div>
                  )}
                  <div className="space-y-2 text-sm text-[#57534E]">
                    {plan.highlights?.slice(0, 3).map((h, i) => (
                      <div key={i} className="flex items-start gap-2">
                        <Check size={15} className="mt-0.5 shrink-0" style={{ color: style.accent }} />
                        <span>{h}</span>
                      </div>
                    ))}
                  </div>
                </motion.div>
              );
            })}
          </div>
        </motion.div>

        {/* ── Selected plan details ── */}
        {selectedPlan && (
          <AnimatePresence mode="wait">
            <motion.div
              key={selectedPlan.plan_type}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -16 }}
              transition={{ duration: 0.4 }}
              className="space-y-8"
            >
              {selectedPlan.generation_failed ? (
                <div data-testid="plan-generation-error" className="bg-white rounded-2xl p-8 border border-red-200 shadow-sm text-center">
                  <h3 className="text-2xl font-medium text-red-600 mb-3"
                    style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                    {selectedPlan.plan_type} plan generation failed
                  </h3>
                  <p className="text-[#57534E] mb-6">
                    {selectedPlan.error || 'Please try again.'}
                  </p>
                  <Button
                    data-testid="regenerate-plan-button"
                    onClick={() => handleRegenerate(selectedPlan.plan_type)}
                    disabled={regenerating}
                    className="text-white px-8 py-5 rounded-xl gap-2"
                    style={{ background: `linear-gradient(135deg, ${ps.accent}, ${ps.accent}CC)` }}
                  >
                    <Sparkles size={18} />
                    {regenerating ? 'Regenerating…' : 'Regenerate this plan'}
                  </Button>
                  {regenerateError && (
                    <p className="text-sm text-red-600 mt-4">{regenerateError}</p>
                  )}
                </div>
              ) : (
                <>
              {/* Map */}
              {mapCenter && (
                <div className="bg-white rounded-2xl p-8 border border-[#E7E5E4] shadow-sm">
                  <h3 className="text-2xl font-medium text-[#2A4B5C] mb-6"
                    style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                    Destination Map
                  </h3>
                  <TripMap center={mapCenter} markers={mapMarkers} height="400px" zoom={11} />
                </div>
              )}

              {/* Cost breakdown */}
              <div data-testid="cost-breakdown" className="bg-white rounded-2xl p-8 border border-[#E7E5E4] shadow-sm">
                <h3 className="text-2xl font-medium text-[#2A4B5C] mb-6"
                  style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Cost Breakdown
                </h3>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-6">
                  {selectedPlan.cost_breakdown && Object.entries(selectedPlan.cost_breakdown).map(([key, value]) => (
                    <div key={key} className="text-center">
                      <div className="text-3xl font-semibold mb-1" style={{ color: ps.accent }}>
                        {formatCost(value)}
                      </div>
                      <div className="text-sm text-[#57534E] capitalize">{key}</div>
                    </div>
                  ))}
                </div>
                {selectedPlan.hotel_inventory_note && (
                  <div className="mt-6 pt-6 border-t border-[#E7E5E4] text-sm text-[#57534E] italic">
                    {selectedPlan.hotel_inventory_note}
                  </div>
                )}
                {selectedPlan.train_placeholder_pricing && (
                  <div className="mt-6 pt-6 border-t border-[#E7E5E4] text-sm text-[#57534E] italic">
                    Estimated train fares — not live pricing. Check IRCTC or Rome2rio for current fares.
                  </div>
                )}
                {selectedPlan.budget_tips?.length > 0 && (
                  <div className="mt-6 pt-6 border-t border-[#E7E5E4]">
                    <h4 className="text-xs uppercase tracking-wider font-medium mb-3" style={{ color: ps.accent }}>
                      Budget Tips
                    </h4>
                    <ul className="space-y-2">
                      {selectedPlan.budget_tips.map((tip, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-[#57534E]">
                          <Check size={14} className="mt-0.5 shrink-0" style={{ color: ps.accent }} />
                          <span>{tip}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              {/* Itinerary */}
              <div data-testid="itinerary-view" className="bg-white rounded-2xl p-8 border border-[#E7E5E4] shadow-sm">
                <h3 className="text-2xl font-medium text-[#2A4B5C] mb-6"
                  style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Day-by-Day Itinerary
                </h3>
                {selectedPlan.itinerary && Object.entries(selectedPlan.itinerary).length > 0 ? (
                  <div className="space-y-4">
                    {Object.entries(selectedPlan.itinerary).map(([day, details]) => (
                      <DayCard
                        key={day}
                        day={day}
                        details={details}
                        formatCost={formatCost}
                        accent={ps.accent}
                      />
                    ))}
                  </div>
                ) : (
                  <p className="text-[#57534E]">Itinerary is being generated. Please check back soon.</p>
                )}
              </div>
                </>
              )}

              {/* Save CTA */}
              <div className="flex justify-center pb-8">
                <motion.div whileHover={{ scale: 1.03 }} whileTap={{ scale: 0.97 }}>
                  <Button
                    onClick={() => navigate('/dashboard')}
                    className="text-white px-10 py-6 text-lg rounded-2xl shadow-xl hover:shadow-2xl transition-all gap-2"
                    style={{ background: `linear-gradient(135deg, ${ps.accent}, ${ps.accent}CC)` }}
                  >
                    <Sparkles size={20} />
                    Save to Dashboard
                  </Button>
                </motion.div>
              </div>
            </motion.div>
          </AnimatePresence>
        )}
      </div>
    </div>
  );
};

export default TripResultsPage;
