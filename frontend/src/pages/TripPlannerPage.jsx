import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Calendar, ChevronRight, ChevronLeft, Sparkles, LocateFixed } from 'lucide-react';
import { useNavigate, useLocation } from 'react-router-dom';
import axios from 'axios';
import {
  API_URL, TRANSPORTATION_OPTIONS, ACCOMMODATION_OPTIONS, INTERESTS, TRIP_TYPES, BUDGET_LEVELS,
  ROAD_ROUTE_STYLE_OPTIONS, ROAD_ROUTE_AVOIDANCE_OPTIONS, ROAD_FUEL_TYPE_OPTIONS, ROAD_EV_RECHARGE_OPTIONS,
  ROAD_OVERNIGHT_ACCOMMODATION_OPTIONS, ROAD_FOOD_PREFERENCE_OPTIONS, ROAD_ROUTE_ATTRACTIONS_OPTIONS, ROAD_AVOID_OPTIONS,
  CRUISE_CABIN_TYPE_OPTIONS, CRUISE_DURATION_OPTIONS, CRUISE_DINING_STYLE_OPTIONS, CRUISE_ITINERARY_STYLE_OPTIONS,
} from '../constants';
import { TRIP_PLANNER } from '../constants/testIds';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Checkbox } from '../components/ui/checkbox';
import LocationAutocomplete from '../components/LocationAutocomplete';
import TripLoadingScreen from '../components/TripLoadingScreen';
import { getTotalTravelers, validateTravelers } from '../lib/travelers';
import {
  getDefaultTransportation, getDefaultTripType, getDefaultTravelPace,
  getDefaultAccommodation, getDefaultInterestFromDestinationType,
} from '../lib/tripDefaults';
import { toast } from '../components/ui/sonner';

const TripPlannerPage = ({ user }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [formData, setFormData] = useState({
    destination: location.state?.destination || '',
    starting_location: location.state?.starting_location || '',
    departure_date: location.state?.departure_date || '',
    return_date: location.state?.return_date || '',
    adults: Number(location.state?.adults) || 1,
    children: 0,
    seniors: 0,
    transportation: 'Flight',
    trip_direction: 'round_trip',
    budget_level: 'Budget',
    accommodation: ['Hostel'],
    interests: [],
    dietary_preferences: '',
    accessibility_requirements: '',
    travel_pace: 'Moderate',
    trip_type: 'Solo',
    currency: 'INR',
    budget_mode: true,

    // Road trip branch (transportation === 'Road')
    road_drivers: 1,
    road_max_hours_before_break: 2,
    road_break_duration_minutes: 15,
    road_max_driving_hours_per_day: 8,
    road_route_style: 'Fastest',
    road_route_avoidances: [],
    road_fuel_type: 'Petrol',
    road_vehicle_mileage_or_model: '',
    road_ev_battery_percent: 100,
    road_ev_recharge_preference: 'Whichever is convenient',
    road_overnight_accommodation: [],
    road_food_preference: 'Mix of everything',
    road_route_attractions: [],
    road_avoid: [],

    // Cruise branch (transportation === 'Cruise')
    cruise_cabin_type: 'Interior',
    cruise_duration_preference: 'Week-long (6-9 nights)',
    cruise_dining_style: 'Flexible anytime dining',
    cruise_itinerary_style: 'No preference',
  });

  // Location metadata (country/type/lat/lng) captured only when the user
  // picks a LocationAutocomplete suggestion - never sent to the backend,
  // purely a client-side signal for the smart defaults below. null means
  // "no signal" (freehand text, or edited away from a prior selection).
  const [destinationMeta, setDestinationMeta] = useState(null);
  const [startingLocationMeta, setStartingLocationMeta] = useState(null);
  // Tracks which interest (if any) is currently in formData.interests purely
  // because of the destination-type nudge, so a later destination change can
  // swap it out without touching anything the user picked themselves.
  const [autoNudgedInterest, setAutoNudgedInterest] = useState(null);

  // True while the browser geolocation + reverse-geocode round-trip is in flight.
  const [geolocating, setGeolocating] = useState(false);

  /**
   * "Use my current location" handler.
   * 1. Asks the browser for lat/lng via the Geolocation API.
   * 2. Reverse-geocodes to a city name via GET /api/locations/reverse-geocode.
   * 3. Populates formData.starting_location and startingLocationMeta with the
   *    same shape that LocationAutocomplete's onSelect produces, so downstream
   *    road-trip code that relies on startingLocationMeta.lat/.lng keeps working.
   */
  const handleUseMyLocation = () => {
    if (!navigator.geolocation) {
      toast.error('Geolocation is not supported by your browser.');
      return;
    }
    setGeolocating(true);
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        const { latitude: lat, longitude: lng } = position.coords;
        try {
          const res = await axios.get(
            `${API_URL}/locations/reverse-geocode`,
            { params: { lat, lng }, withCredentials: true }
          );
          const { name, city, country, country_code: countryCode } = res.data;
          const displayName = city
            ? country ? `${city}, ${country}` : city
            : name;
          // Populate the text field
          setFormData(prev => ({ ...prev, starting_location: displayName }));
          // Populate meta - matches LocationAutocomplete onSelect shape exactly:
          // { country, type, lat, lng }
          setStartingLocationMeta({
            country: country || countryCode || '',
            type: 'city',
            lat: res.data.lat,
            lng: res.data.lng,
          });
        } catch {
          toast.error('Could not resolve your location to a city name. Try typing it instead.');
        } finally {
          setGeolocating(false);
        }
      },
      (err) => {
        setGeolocating(false);
        if (err.code === 1 /* PERMISSION_DENIED */) {
          toast.error('Location access was denied. Please type your starting city instead.');
        } else if (err.code === 3 /* TIMEOUT */) {
          toast.error('Location request timed out. Please type your starting city instead.');
        } else {
          toast.error('Could not get your location. Please type your starting city instead.');
        }
      },
      { timeout: 10000, maximumAge: 60000 }
    );
  };

  // Fields with a smart default: once true, the auto-fill effects for that
  // field stop overriding it - the user's explicit choice always wins.
  const [touched, setTouched] = useState({
    transportation: false,
    trip_type: false,
    travel_pace: false,
    accommodation: false,
    interests: false,
  });
  const markTouched = (field) => setTouched(prev => (field in prev ? { ...prev, [field]: true } : prev));

  const selectField = (field, value) => {
    setFormData(prev => ({ ...prev, [field]: value }));
    markTouched(field);
  };

  const totalTravelers = getTotalTravelers(formData);
  const travelersError = validateTravelers(formData);

  const [quota, setQuota] = useState(null);

  useEffect(() => {
    let cancelled = false;
    axios.get(`${API_URL}/trips/quota-status`, { withCredentials: true })
      .then(res => { if (!cancelled) setQuota(res.data); })
      .catch(() => {}); // non-critical - just skip the display if this fails
    return () => { cancelled = true; };
  }, []);

  // Smart defaults - each only fires while its field is untouched, and each
  // recomputes from whatever upstream signal changed (dates, budget, party
  // composition, resolved destination) so it keeps tracking the user's
  // answers right up until they interact with the field directly.
  useEffect(() => {
    if (touched.transportation) return;
    const next = getDefaultTransportation(destinationMeta, startingLocationMeta);
    setFormData(prev => (prev.transportation === next ? prev : { ...prev, transportation: next }));
  }, [destinationMeta, startingLocationMeta, touched.transportation]);

  useEffect(() => {
    if (touched.trip_type) return;
    const next = getDefaultTripType(formData.adults, formData.children, formData.seniors);
    setFormData(prev => (prev.trip_type === next ? prev : { ...prev, trip_type: next }));
  }, [formData.adults, formData.children, formData.seniors, touched.trip_type]);

  useEffect(() => {
    if (touched.travel_pace) return;
    const next = getDefaultTravelPace(formData.departure_date, formData.return_date);
    setFormData(prev => (prev.travel_pace === next ? prev : { ...prev, travel_pace: next }));
  }, [formData.departure_date, formData.return_date, touched.travel_pace]);

  useEffect(() => {
    if (touched.accommodation) return;
    const next = getDefaultAccommodation(formData.budget_level);
    setFormData(prev => (
      prev.accommodation.length === next.length && prev.accommodation[0] === next[0]
        ? prev
        : { ...prev, accommodation: next }
    ));
  }, [formData.budget_level, touched.accommodation]);

  useEffect(() => {
    if (touched.interests) return;
    const nudge = destinationMeta ? getDefaultInterestFromDestinationType(destinationMeta.type) : null;
    if (nudge === autoNudgedInterest) return;
    setFormData(prev => {
      let interests = prev.interests;
      if (autoNudgedInterest) interests = interests.filter(i => i !== autoNudgedInterest);
      if (nudge && !interests.includes(nudge)) interests = [...interests, nudge];
      return interests === prev.interests ? prev : { ...prev, interests };
    });
    setAutoNudgedInterest(nudge);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [destinationMeta, touched.interests]);

  const handleNext = () => {
    if (step === 1 && travelersError) return;
    if (step < totalSteps) setStep(step + 1);
  };
  const handlePrev = () => { if (step > 1) setStep(step - 1); };

  const handleSubmit = async () => {
    if (travelersError) return;
    setLoading(true);
    try {
      const payload = { ...formData, num_travelers: totalTravelers };
      const response = await axios.post(
        `${API_URL}/trips/generate`,
        payload,
        { withCredentials: true }
      );
      if (window.posthog) {
        const tripMode = (formData.transportation || 'flight').toLowerCase();
        window.posthog.capture('trip_generated', {
          trip_mode: tripMode,
        });
      }
      navigate(`/trip-results/${response.data.trip_id}`);
    } catch (error) {
      console.error('Error generating trip:', error);
      const data = error.response?.data;
      if (error.response?.status === 429 && data?.reason === 'quota_exceeded') {
        toast.error(data.detail);
        setQuota({ is_premium: false, used: data.used, limit: data.limit, remaining: 0 });
      } else if (error.response?.status === 429) {
        toast.error(data?.detail || "You're doing that too fast - please wait a moment and try again.");
      } else {
        toast.error('Failed to generate trip plans. Please try again.');
      }
      setLoading(false);
    }
  };

  const toggleArrayItem = (field, value) => {
    setFormData(prev => ({
      ...prev,
      [field]: prev[field].includes(value)
        ? prev[field].filter(item => item !== value)
        : [...prev[field], value]
    }));
    markTouched(field);
  };

  // Road/Cruise get their own conditional step (mirrors each other) inserted
  // right after "Travel Preferences", where Transportation is chosen -
  // recomputed every render so switching transportation immediately grows,
  // shrinks, or reorders the wizard without leaving `step` pointing at stale
  // content.
  const activeSteps = [
    'basics',
    'preferences',
    ...(formData.transportation === 'Road' ? ['road'] : []),
    ...(formData.transportation === 'Cruise' ? ['cruise'] : []),
    'interests',
    'details',
  ];
  const totalSteps = activeSteps.length;
  const currentStepKey = activeSteps[step - 1];

  const cardGridButton = (active) => `p-4 rounded-xl border-2 transition-all ${
    active ? 'border-[#C47245] bg-[#C47245]/10' : 'border-[#E7E5E4] hover:border-[#C47245]/50'
  }`;
  const checkboxCard = (active) => `p-3 rounded-lg border-2 cursor-pointer transition-all ${
    active ? 'border-[#C47245] bg-[#C47245]/10' : 'border-[#E7E5E4] hover:border-[#C47245]/50'
  }`;

  /* ── Show cinematic loader during AI generation ── */
  if (loading) {
    return (
      <TripLoadingScreen
        destination={formData.destination || 'your destination'}
      />
    );
  }

  return (
    <div data-testid={TRIP_PLANNER.plannerForm} className="min-h-screen bg-gradient-to-br from-[#FDFBF7] via-[#F5F2EB] to-[#FDFBF7] py-12 px-4">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="text-center mb-12">
          <h1 className="text-5xl font-semibold text-[#1C1917] mb-4" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
            AI Trip Planner
          </h1>
          <p className="text-lg text-[#57534E]">Tell us about your dream vacation</p>

          {quota && !quota.is_premium && (
            <div data-testid={TRIP_PLANNER.quotaBanner}
              className={`inline-flex flex-wrap items-center justify-center gap-1.5 mt-4 px-4 py-2 rounded-full text-sm font-medium ${
                quota.remaining === 0
                  ? 'bg-red-50 text-red-600 border border-red-200'
                  : 'bg-[#F5F2EB] text-[#57534E] border border-[#E7E5E4]'
              }`}>
              {quota.remaining === 0 ? (
                <>
                  You've used all {quota.limit} free trip generations today —{' '}
                  <button type="button" onClick={() => navigate('/premium')}
                    className="underline font-semibold text-[#C47245]">
                    upgrade to Premium
                  </button>{' '}for unlimited planning
                </>
              ) : (
                <>{quota.remaining} of {quota.limit} free trip generations left today</>
              )}
            </div>
          )}

          {/* Progress */}
          <div className="flex items-center justify-center gap-2 mt-8">
            {activeSteps.map((key, idx) => (
              <div
                key={key}
                className={`h-2 rounded-full transition-all ${idx + 1 <= step ? 'w-12 bg-[#C47245]' : 'w-8 bg-[#E7E5E4]'}`}
              />
            ))}
          </div>
          <p className="text-sm text-[#57534E] mt-2">Step {step} of {totalSteps}</p>
        </div>

        {/* Form */}
        <motion.div
          className="bg-white/70 backdrop-blur-xl rounded-2xl p-8 border border-[#E7E5E4] shadow-xl"
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
        >
          <AnimatePresence mode="wait">
            {currentStepKey === 'basics' && (
              <motion.div key="basics" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }} className="space-y-6">
                <h2 className="text-2xl font-medium text-[#2A4B5C] mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Trip Basics
                </h2>
                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium">Destination</Label>
                  <div className="mt-2">
                    <LocationAutocomplete
                      testId={TRIP_PLANNER.destinationInput}
                      value={formData.destination}
                      onChange={(val) => { setFormData(prev => ({ ...prev, destination: val })); setDestinationMeta(null); }}
                      onSelect={(s) => setDestinationMeta({ country: s.country, type: s.type, lat: s.lat, lng: s.lng })}
                      placeholder="Where do you want to go?"
                    />
                  </div>
                </div>
                <div>
                  <div className="flex items-center justify-between">
                    <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium">Starting Location</Label>
                    <button
                      type="button"
                      onClick={handleUseMyLocation}
                      disabled={geolocating}
                      className="flex items-center gap-1 text-xs text-[#C47245] hover:text-[#a05a30] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      title="Auto-fill your current location"
                    >
                      {geolocating ? (
                        <>
                          <svg className="animate-spin h-3 w-3" viewBox="0 0 24 24" fill="none">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                          </svg>
                          Detecting…
                        </>
                      ) : (
                        <>
                          <LocateFixed size={12} />
                          Use my location
                        </>
                      )}
                    </button>
                  </div>
                  <div className="mt-2">
                    <LocationAutocomplete
                      testId={TRIP_PLANNER.startLocationInput}
                      value={formData.starting_location}
                      onChange={(val) => { setFormData(prev => ({ ...prev, starting_location: val })); setStartingLocationMeta(null); }}
                      onSelect={(s) => setStartingLocationMeta({ country: s.country, type: s.type, lat: s.lat, lng: s.lng })}
                      placeholder="Where are you starting from?"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium">Departure Date</Label>
                    <div className="flex items-center gap-2 mt-2">
                      <Calendar size={20} className="text-[#57534E]" />
                      <Input
                        data-testid={TRIP_PLANNER.departureDateInput}
                        type="date"
                        value={formData.departure_date}
                        onChange={(e) => setFormData({ ...formData, departure_date: e.target.value })}
                        className="border-[#E7E5E4]"
                      />
                    </div>
                  </div>
                  <div>
                    <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium">Return Date</Label>
                    <div className="flex items-center gap-2 mt-2">
                      <Calendar size={20} className="text-[#57534E]" />
                      <Input
                        data-testid={TRIP_PLANNER.returnDateInput}
                        type="date"
                        value={formData.return_date}
                        onChange={(e) => setFormData({ ...formData, return_date: e.target.value })}
                        className="border-[#E7E5E4]"
                      />
                    </div>
                  </div>
                </div>
                <div
                  data-testid={TRIP_PLANNER.oneWayCheckbox}
                  onClick={() => setFormData({
                    ...formData,
                    trip_direction: formData.trip_direction === 'round_trip' ? 'one_way' : 'round_trip',
                  })}
                  className="inline-flex items-center gap-2 cursor-pointer select-none"
                >
                  <Checkbox checked={formData.trip_direction === 'one_way'} />
                  <span className="text-sm text-[#57534E]">One-way trip (not booking a return leg)</span>
                </div>
                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Travelers</Label>
                  <div className="grid grid-cols-3 gap-4">
                    {[['adults','Adults',TRIP_PLANNER.adultsInput],['children','Children',TRIP_PLANNER.childrenInput],['seniors','Seniors',TRIP_PLANNER.seniorsInput]].map(([field, label, testId]) => (
                      <div key={field}>
                        <label className="text-sm text-[#57534E]">{label}</label>
                        <Input data-testid={testId} type="number" min="0" step="1" value={formData[field]}
                          onChange={(e) => setFormData({ ...formData, [field]: e.target.value === '' ? 0 : Number(e.target.value) })}
                          className="border-[#E7E5E4] mt-1" />
                      </div>
                    ))}
                  </div>
                  <p data-testid={TRIP_PLANNER.travelersTotalDisplay} className="text-sm text-[#57534E] mt-3">
                    Total travelers: {totalTravelers}
                  </p>
                  {travelersError && (
                    <p data-testid={TRIP_PLANNER.travelersError} className="text-sm text-red-600 mt-1">
                      {travelersError}
                    </p>
                  )}
                </div>
              </motion.div>
            )}

            {currentStepKey === 'preferences' && (
              <motion.div key="preferences" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }} className="space-y-6">
                <h2 className="text-2xl font-medium text-[#2A4B5C] mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Travel Preferences
                </h2>
                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Transportation</Label>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {TRANSPORTATION_OPTIONS.map(option => (
                      <button key={option.value}
                        onClick={() => selectField('transportation', option.value)}
                        className={cardGridButton(formData.transportation === option.value)}>
                        <div className="text-2xl mb-1">{option.icon}</div>
                        <div className="text-sm font-medium text-[#1C1917]">{option.label}</div>
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Budget Level</Label>
                  <div className="space-y-2">
                    {BUDGET_LEVELS.map(level => (
                      <button key={level.value}
                        onClick={() => setFormData({ ...formData, budget_level: level.value })}
                        className={`w-full p-4 rounded-xl border-2 transition-all text-left ${
                          formData.budget_level === level.value
                            ? 'border-[#C47245] bg-[#C47245]/10'
                            : 'border-[#E7E5E4] hover:border-[#C47245]/50'
                        }`}>
                        <div className="font-medium text-[#1C1917]">{level.label}</div>
                        <div className="text-sm text-[#57534E]">{level.description}</div>
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Accommodation Preferences</Label>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                    {ACCOMMODATION_OPTIONS.map(option => (
                      <div key={option} onClick={() => toggleArrayItem('accommodation', option)}
                        className={checkboxCard(formData.accommodation.includes(option))}>
                        <div className="flex items-center gap-2">
                          <Checkbox checked={formData.accommodation.includes(option)} />
                          <span className="text-sm text-[#1C1917]">{option}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </motion.div>
            )}

            {currentStepKey === 'road' && (
              <motion.div key="road" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }} className="space-y-6">
                <h2 className="text-2xl font-medium text-[#2A4B5C] mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Road Trip Details
                </h2>

                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Driver Details</Label>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    {[
                      ['road_drivers', 'Number of Drivers'],
                      ['road_max_hours_before_break', 'Max Hours Before Break'],
                      ['road_break_duration_minutes', 'Break Duration (min)'],
                      ['road_max_driving_hours_per_day', 'Max Driving Hours/Day'],
                    ].map(([field, label]) => (
                      <div key={field}>
                        <label className="text-sm text-[#57534E]">{label}</label>
                        <Input type="number" min="0" step="1" value={formData[field]}
                          onChange={(e) => setFormData({ ...formData, [field]: e.target.value === '' ? 0 : Number(e.target.value) })}
                          className="border-[#E7E5E4] mt-1" />
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Route Style</Label>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {ROAD_ROUTE_STYLE_OPTIONS.map(opt => (
                      <button key={opt} onClick={() => selectField('road_route_style', opt)}
                        className={cardGridButton(formData.road_route_style === opt)}>
                        <div className="text-sm font-medium text-[#1C1917]">{opt}</div>
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Route Avoidances (optional)</Label>
                  <div className="grid grid-cols-2 gap-3">
                    {ROAD_ROUTE_AVOIDANCE_OPTIONS.map(opt => (
                      <div key={opt} onClick={() => toggleArrayItem('road_route_avoidances', opt)}
                        className={checkboxCard(formData.road_route_avoidances.includes(opt))}>
                        <div className="flex items-center gap-2">
                          <Checkbox checked={formData.road_route_avoidances.includes(opt)} />
                          <span className="text-sm text-[#1C1917]">{opt}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Vehicle - Fuel Type</Label>
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                    {ROAD_FUEL_TYPE_OPTIONS.map(opt => (
                      <button key={opt} onClick={() => selectField('road_fuel_type', opt)}
                        className={cardGridButton(formData.road_fuel_type === opt)}>
                        <div className="text-sm font-medium text-[#1C1917]">{opt}</div>
                      </button>
                    ))}
                  </div>
                </div>

                {formData.road_fuel_type === 'Electric' ? (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium">Current Battery %</Label>
                      <Input type="number" min="0" max="100" value={formData.road_ev_battery_percent}
                        onChange={(e) => setFormData({ ...formData, road_ev_battery_percent: e.target.value === '' ? 0 : Number(e.target.value) })}
                        className="border-[#E7E5E4] mt-2" />
                    </div>
                    <div>
                      <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Recharge Preference</Label>
                      <div className="space-y-2">
                        {ROAD_EV_RECHARGE_OPTIONS.map(opt => (
                          <button key={opt} onClick={() => selectField('road_ev_recharge_preference', opt)}
                            className={`w-full p-2 rounded-lg border-2 transition-all text-left text-sm ${
                              formData.road_ev_recharge_preference === opt
                                ? 'border-[#C47245] bg-[#C47245]/10'
                                : 'border-[#E7E5E4] hover:border-[#C47245]/50'
                            }`}>
                            {opt}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div>
                    <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium">Vehicle Mileage or Model</Label>
                    <Input value={formData.road_vehicle_mileage_or_model}
                      onChange={(e) => setFormData({ ...formData, road_vehicle_mileage_or_model: e.target.value })}
                      placeholder="E.g., 18 km/l, or Toyota Innova"
                      className="border-[#E7E5E4] mt-2" />
                  </div>
                )}

                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Overnight Stop Accommodation</Label>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {ROAD_OVERNIGHT_ACCOMMODATION_OPTIONS.map(opt => (
                      <div key={opt} onClick={() => toggleArrayItem('road_overnight_accommodation', opt)}
                        className={checkboxCard(formData.road_overnight_accommodation.includes(opt))}>
                        <div className="flex items-center gap-2">
                          <Checkbox checked={formData.road_overnight_accommodation.includes(opt)} />
                          <span className="text-sm text-[#1C1917]">{opt}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Food Preference</Label>
                  <div className="grid grid-cols-2 gap-3">
                    {ROAD_FOOD_PREFERENCE_OPTIONS.map(opt => (
                      <button key={opt} onClick={() => selectField('road_food_preference', opt)}
                        className={cardGridButton(formData.road_food_preference === opt)}>
                        <div className="text-sm font-medium text-[#1C1917]">{opt}</div>
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Attractions You'd Enjoy Along the Route</Label>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                    {ROAD_ROUTE_ATTRACTIONS_OPTIONS.map(opt => (
                      <div key={opt} onClick={() => toggleArrayItem('road_route_attractions', opt)}
                        className={checkboxCard(formData.road_route_attractions.includes(opt))}>
                        <div className="flex items-center gap-2">
                          <Checkbox checked={formData.road_route_attractions.includes(opt)} />
                          <span className="text-sm text-[#1C1917]">{opt}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Things to Avoid</Label>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                    {ROAD_AVOID_OPTIONS.map(opt => (
                      <div key={opt} onClick={() => toggleArrayItem('road_avoid', opt)}
                        className={checkboxCard(formData.road_avoid.includes(opt))}>
                        <div className="flex items-center gap-2">
                          <Checkbox checked={formData.road_avoid.includes(opt)} />
                          <span className="text-sm text-[#1C1917]">{opt}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </motion.div>
            )}

            {currentStepKey === 'cruise' && (
              <motion.div key="cruise" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }} className="space-y-6">
                <h2 className="text-2xl font-medium text-[#2A4B5C] mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Cruise Preferences
                </h2>

                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Cabin Type</Label>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {CRUISE_CABIN_TYPE_OPTIONS.map(opt => (
                      <button key={opt} onClick={() => selectField('cruise_cabin_type', opt)}
                        className={cardGridButton(formData.cruise_cabin_type === opt)}>
                        <div className="text-sm font-medium text-[#1C1917]">{opt}</div>
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Cruise Duration Preference</Label>
                  <div className="space-y-2">
                    {CRUISE_DURATION_OPTIONS.map(opt => (
                      <button key={opt} onClick={() => selectField('cruise_duration_preference', opt)}
                        className={`w-full p-4 rounded-xl border-2 transition-all text-left ${
                          formData.cruise_duration_preference === opt
                            ? 'border-[#C47245] bg-[#C47245]/10'
                            : 'border-[#E7E5E4] hover:border-[#C47245]/50'
                        }`}>
                        <div className="font-medium text-[#1C1917]">{opt}</div>
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Dining Style</Label>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    {CRUISE_DINING_STYLE_OPTIONS.map(opt => (
                      <button key={opt} onClick={() => selectField('cruise_dining_style', opt)}
                        className={cardGridButton(formData.cruise_dining_style === opt)}>
                        <div className="text-sm font-medium text-[#1C1917]">{opt}</div>
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Itinerary Style</Label>
                  <div className="grid grid-cols-2 gap-3">
                    {CRUISE_ITINERARY_STYLE_OPTIONS.map(opt => (
                      <button key={opt} onClick={() => selectField('cruise_itinerary_style', opt)}
                        className={cardGridButton(formData.cruise_itinerary_style === opt)}>
                        <div className="text-sm font-medium text-[#1C1917]">{opt}</div>
                      </button>
                    ))}
                  </div>
                </div>
              </motion.div>
            )}

            {currentStepKey === 'interests' && (
              <motion.div key="interests" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }} className="space-y-6">
                <h2 className="text-2xl font-medium text-[#2A4B5C] mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Interests & Activities
                </h2>
                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">What interests you?</Label>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                    {INTERESTS.map(interest => (
                      <div key={interest} onClick={() => toggleArrayItem('interests', interest)}
                        className={checkboxCard(formData.interests.includes(interest))}>
                        <div className="flex items-center gap-2">
                          <Checkbox checked={formData.interests.includes(interest)} />
                          <span className="text-sm text-[#1C1917]">{interest}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Trip Type</Label>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {TRIP_TYPES.map(type => (
                      <button key={type.value}
                        onClick={() => selectField('trip_type', type.value)}
                        className={cardGridButton(formData.trip_type === type.value)}>
                        <div className="text-sm font-medium text-[#1C1917]">{type.label}</div>
                      </button>
                    ))}
                  </div>
                </div>
              </motion.div>
            )}

            {currentStepKey === 'details' && (
              <motion.div key="details" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }} className="space-y-6">
                <h2 className="text-2xl font-medium text-[#2A4B5C] mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Additional Details
                </h2>
                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium">Dietary Preferences (Optional)</Label>
                  <Input value={formData.dietary_preferences}
                    onChange={(e) => setFormData({ ...formData, dietary_preferences: e.target.value })}
                    placeholder="E.g., Vegetarian, Vegan, Halal, etc."
                    className="border-[#E7E5E4] mt-2" />
                </div>
                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium">Accessibility Requirements (Optional)</Label>
                  <Input value={formData.accessibility_requirements}
                    onChange={(e) => setFormData({ ...formData, accessibility_requirements: e.target.value })}
                    placeholder="Any special accessibility needs?"
                    className="border-[#E7E5E4] mt-2" />
                </div>
                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Travel Pace</Label>
                  <div className="grid grid-cols-3 gap-3">
                    {['Relaxed', 'Moderate', 'Fast-paced'].map(pace => (
                      <button key={pace}
                        onClick={() => selectField('travel_pace', pace)}
                        className={cardGridButton(formData.travel_pace === pace)}>
                        <div className="text-sm font-medium text-[#1C1917]">{pace}</div>
                      </button>
                    ))}
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Navigation */}
          <div className="flex items-center justify-between mt-8 pt-6 border-t border-[#E7E5E4]">
            <Button onClick={handlePrev} disabled={step === 1} variant="outline" className="border-[#E7E5E4]">
              <ChevronLeft size={20} />
              Previous
            </Button>
            {step < totalSteps ? (
              <Button data-testid={TRIP_PLANNER.submitButton} onClick={handleNext}
                disabled={step === 1 && !!travelersError} className="bg-[#C47245] hover:bg-[#A85D38]">
                Next
                <ChevronRight size={20} />
              </Button>
            ) : (
              <Button data-testid={TRIP_PLANNER.submitButton} onClick={handleSubmit}
                disabled={loading || !!travelersError} className="bg-[#C47245] hover:bg-[#A85D38]">
                <Sparkles size={20} />
                Generate Plans
              </Button>
            )}
          </div>
        </motion.div>
      </div>
    </div>
  );
};

export default TripPlannerPage;
