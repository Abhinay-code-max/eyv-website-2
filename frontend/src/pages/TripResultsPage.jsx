import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { motion } from 'framer-motion';
import { ArrowLeft, DollarSign, Plane, Hotel, Utensils, Activity, Calendar, MapPin, Check } from 'lucide-react';
import { API_URL } from '../constants';
import { TRIP_PLANNER } from '../constants/testIds';
import LoadingAnimation from '../components/LoadingAnimation';
import { Button } from '../components/ui/button';
import EYVLogo from '../components/EYVLogo';
import TripMap from '../components/TripMap';

const TripResultsPage = () => {
  const { tripId } = useParams();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [trip, setTrip] = useState(null);
  const [selectedPlan, setSelectedPlan] = useState(null);
  const [mapCenter, setMapCenter] = useState(null);
  const [mapMarkers, setMapMarkers] = useState([]);

  useEffect(() => {
    fetchTrip();
  }, [tripId]);

  useEffect(() => {
    if (trip?.preferences?.destination) {
      fetchDestinationCoords(trip.preferences.destination);
    }
  }, [trip]);

  const fetchDestinationCoords = async (destination) => {
    try {
      const response = await axios.get(
        `${API_URL}/destinations/${encodeURIComponent(destination)}/coords`,
        { withCredentials: true }
      );
      const { lat, lng } = response.data;
      setMapCenter([lat, lng]);
      setMapMarkers([
        {
          lat,
          lng,
          title: destination,
          description: 'Your destination',
        },
      ]);
    } catch (error) {
      console.error('Coords fetch error:', error);
    }
  };

  const fetchTrip = async () => {
    try {
      const response = await axios.get(`${API_URL}/trips/${tripId}`, {
        withCredentials: true,
      });
      setTrip(response.data);
      setSelectedPlan(response.data.plans[1]); // Default to Premium
    } catch (error) {
      console.error('Error fetching trip:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <LoadingAnimation />;
  if (!trip) return <div className="min-h-screen flex items-center justify-center">Trip not found</div>;

  const getPlanColor = (planType) => {
    if (planType === 'Budget') return 'border-[#86A8B3] bg-[#86A8B3]/10';
    if (planType === 'Premium') return 'border-[#C47245] bg-[#C47245]/10';
    return 'border-[#E8B273] bg-[#E8B273]/10';
  };

  const currencySymbol = selectedPlan?.currency_symbol || (selectedPlan?.currency === 'INR' ? '₹' : '$');
  const formatCost = (val) => `${currencySymbol}${(val ?? 0).toLocaleString()}`;

  return (
    <div className="min-h-screen bg-[#FDFBF7]">
      {/* Header */}
      <div className="sticky top-0 z-50 glass border-b border-[#E7E5E4]">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <Button
            onClick={() => navigate('/dashboard')}
            variant="ghost"
            className="text-[#57534E]"
          >
            <ArrowLeft size={20} />
            Back to Dashboard
          </Button>
          <EYVLogo size="small" />
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-12">
        {/* Trip Header */}
        <div className="mb-12">
          <h1 className="text-5xl font-semibold text-[#1C1917] mb-4" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
            {trip.trip_name}
          </h1>
          <div className="flex flex-wrap items-center gap-4 text-[#57534E]">
            <div className="flex items-center gap-2">
              <MapPin size={18} />
              <span>{trip.preferences.destination}</span>
            </div>
            <div className="flex items-center gap-2">
              <Calendar size={18} />
              <span>{trip.preferences.departure_date} to {trip.preferences.return_date}</span>
            </div>
          </div>
        </div>

        {/* Plan Selection */}
        <div className="mb-12">
          <h2 className="text-3xl font-medium text-[#2A4B5C] mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
            Choose Your Plan
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {trip.plans.map((plan, idx) => (
              <motion.div
                key={idx}
                data-testid={`${plan.plan_type.toLowerCase()}-plan-card`}
                onClick={() => setSelectedPlan(plan)}
                className={`relative p-6 rounded-2xl border-2 cursor-pointer transition-all hover:shadow-xl ${
                  selectedPlan?.plan_type === plan.plan_type ? getPlanColor(plan.plan_type) : 'border-[#E7E5E4]'
                }`}
                whileHover={{ y: -5 }}
              >
                {selectedPlan?.plan_type === plan.plan_type && (
                  <div className="absolute -top-3 -right-3 bg-[#C47245] text-white rounded-full p-2">
                    <Check size={20} />
                  </div>
                )}
                <h3 className="text-2xl font-medium text-[#1C1917] mb-2" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  {plan.plan_type}
                </h3>
                <div className="flex items-baseline gap-2 mb-4">
                  <span className="text-3xl font-semibold text-[#C47245]">
                    {plan.currency_symbol || (plan.currency === 'INR' ? '₹' : '$')}
                  </span>
                  <span className="text-4xl font-semibold text-[#1C1917]">
                    {plan.total_cost?.toLocaleString() || 'N/A'}
                  </span>
                </div>
                <div className="space-y-2 text-sm text-[#57534E]">
                  {plan.highlights?.slice(0, 3).map((highlight, i) => (
                    <div key={i} className="flex items-start gap-2">
                      <Check size={16} className="text-[#C47245] mt-0.5 flex-shrink-0" />
                      <span>{highlight}</span>
                    </div>
                  ))}
                </div>
              </motion.div>
            ))}
          </div>
        </div>

        {/* Selected Plan Details */}
        {selectedPlan && (
          <div className="space-y-8">
            {/* Map View */}
            {mapCenter && (
              <div className="bg-white rounded-2xl p-8 border border-[#E7E5E4]">
                <h3 className="text-2xl font-medium text-[#2A4B5C] mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Destination Map
                </h3>
                <TripMap center={mapCenter} markers={mapMarkers} height="400px" zoom={11} />
              </div>
            )}

            {/* Cost Breakdown */}
            <div data-testid="cost-breakdown" className="bg-white rounded-2xl p-8 border border-[#E7E5E4]">
              <h3 className="text-2xl font-medium text-[#2A4B5C] mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                Cost Breakdown
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-6">
                {selectedPlan.cost_breakdown && Object.entries(selectedPlan.cost_breakdown).map(([key, value]) => (
                  <div key={key} className="text-center">
                    <div className="text-3xl font-semibold text-[#C47245] mb-1">
                      {formatCost(value)}
                    </div>
                    <div className="text-sm text-[#57534E] capitalize">{key}</div>
                  </div>
                ))}
              </div>
              {selectedPlan.budget_tips && selectedPlan.budget_tips.length > 0 && (
                <div className="mt-6 pt-6 border-t border-[#E7E5E4]">
                  <h4 className="text-sm uppercase tracking-wider text-[#C47245] font-medium mb-3">Budget Tips</h4>
                  <ul className="space-y-2">
                    {selectedPlan.budget_tips.map((tip, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-[#57534E]">
                        <Check size={14} className="text-[#C47245] mt-0.5 flex-shrink-0" />
                        <span>{tip}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>

            {/* Itinerary */}
            <div data-testid="itinerary-view" className="bg-white rounded-2xl p-8 border border-[#E7E5E4]">
              <h3 className="text-2xl font-medium text-[#2A4B5C] mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                Day-by-Day Itinerary
              </h3>
              {selectedPlan.itinerary && Object.entries(selectedPlan.itinerary).length > 0 ? (
                <div className="space-y-8">
                  {Object.entries(selectedPlan.itinerary).map(([day, details], idx) => (
                    <div key={day} className="border-l-4 border-[#C47245] pl-6">
                      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-4">
                        <h4 className="text-xl font-medium text-[#1C1917]" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                          {day.replace('_', ' ').toUpperCase()}
                          {details.date && ` — ${details.date}`}
                        </h4>
                        {details.daily_total ? (
                          <div className="text-right">
                            <div className="text-2xl font-semibold text-[#C47245]" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                              {formatCost(details.daily_total)}
                            </div>
                            <div className="text-xs text-[#57534E]">Day total</div>
                          </div>
                        ) : null}
                      </div>
                      
                      {/* Transportation */}
                      {details.transportation && (
                        <div className="mb-4">
                          <div className="flex items-center gap-2 text-[#C47245] mb-2">
                            <Plane size={18} />
                            <span className="font-medium">Transportation</span>
                          </div>
                          <div className="ml-6 text-[#57534E]">
                            <span className="font-medium capitalize">{details.transportation.mode}:</span> {details.transportation.details}
                            {details.transportation.cost !== undefined && (
                              <span className="text-[#C47245] font-medium"> — {formatCost(details.transportation.cost)}</span>
                            )}
                          </div>
                        </div>
                      )}

                      {/* Activities */}
                      {details.activities && details.activities.length > 0 && (
                        <div className="mb-4">
                          <div className="flex items-center gap-2 text-[#C47245] mb-2">
                            <Activity size={18} />
                            <span className="font-medium">Activities</span>
                          </div>
                          <div className="space-y-2 ml-6">
                            {details.activities.map((activity, i) => (
                              <div key={i} className="text-[#57534E]">
                                <span className="font-medium">{activity.time}:</span> {activity.activity}
                                {activity.location && ` at ${activity.location}`}
                                {activity.cost !== undefined && (
                                  <span className="text-[#C47245] font-medium"> — {activity.cost === 0 ? 'Free' : formatCost(activity.cost)}</span>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Accommodation */}
                      {details.accommodation && (
                        <div className="mb-4">
                          <div className="flex items-center gap-2 text-[#C47245] mb-2">
                            <Hotel size={18} />
                            <span className="font-medium">Accommodation</span>
                          </div>
                          <div className="ml-6 text-[#57534E]">
                            {details.accommodation.name} ({details.accommodation.type})
                            {details.accommodation.cost !== undefined && (
                              <span className="text-[#C47245] font-medium"> — {formatCost(details.accommodation.cost)}</span>
                            )}
                          </div>
                        </div>
                      )}

                      {/* Meals */}
                      {details.meals && details.meals.length > 0 && (
                        <div className="mb-3">
                          <div className="flex items-center gap-2 text-[#C47245] mb-2">
                            <Utensils size={18} />
                            <span className="font-medium">Meals</span>
                          </div>
                          <div className="space-y-1 ml-6">
                            {details.meals.map((meal, i) => (
                              <div key={i} className="text-[#57534E]">
                                <span className="font-medium capitalize">{meal.time}:</span> {meal.restaurant}
                                {meal.cuisine && ` (${meal.cuisine})`}
                                {meal.cost !== undefined && (
                                  <span className="text-[#C47245] font-medium"> — {formatCost(meal.cost)}</span>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Cumulative total */}
                      {details.cumulative_total !== undefined && (
                        <div className="mt-3 pt-3 border-t border-[#E7E5E4] text-sm text-[#57534E] flex justify-between">
                          <span>Cumulative trip total:</span>
                          <span className="font-medium text-[#C47245]">{formatCost(details.cumulative_total)}</span>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-[#57534E]">Itinerary is being generated. Please check back soon.</p>
              )}
            </div>

            {/* Action Button */}
            <div className="flex justify-center">
              <Button
                onClick={() => navigate('/dashboard')}
                className="bg-[#C47245] hover:bg-[#A85D38] px-8 py-6 text-lg"
              >
                Save to Dashboard
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default TripResultsPage;
