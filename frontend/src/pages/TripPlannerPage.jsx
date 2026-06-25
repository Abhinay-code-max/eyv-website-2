import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { MapPin, Calendar, Users, Plane, DollarSign, Hotel, Heart, ChevronRight, ChevronLeft, Sparkles } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API_URL, TRANSPORTATION_OPTIONS, ACCOMMODATION_OPTIONS, INTERESTS, TRIP_TYPES, BUDGET_LEVELS } from '../constants';
import { TRIP_PLANNER } from '../constants/testIds';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Checkbox } from '../components/ui/checkbox';
import LocationAutocomplete from '../components/LocationAutocomplete';

const TripPlannerPage = ({ user }) => {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [formData, setFormData] = useState({
    destination: '',
    starting_location: '',
    departure_date: '',
    return_date: '',
    num_travelers: 1,
    adults: 1,
    children: 0,
    seniors: 0,
    transportation: 'Train',
    budget_level: 'Budget',
    accommodation: ['Hostel'],
    interests: [],
    dietary_preferences: '',
    accessibility_requirements: '',
    travel_pace: 'Moderate',
    trip_type: 'Solo',
    currency: 'INR',
    budget_mode: true,
  });

  const totalSteps = 4;

  const handleNext = () => {
    if (step < totalSteps) setStep(step + 1);
  };

  const handlePrev = () => {
    if (step > 1) setStep(step - 1);
  };

  const handleSubmit = async () => {
    setLoading(true);
    try {
      const response = await axios.post(
        `${API_URL}/trips/generate`,
        formData,
        { withCredentials: true }
      );
      navigate(`/trip-results/${response.data.trip_id}`);
    } catch (error) {
      console.error('Error generating trip:', error);
      alert('Failed to generate trip plans. Please try again.');
    } finally {
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
  };

  return (
    <div data-testid={TRIP_PLANNER.plannerForm} className="min-h-screen bg-gradient-to-br from-[#FDFBF7] via-[#F5F2EB] to-[#FDFBF7] py-12 px-4">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="text-center mb-12">
          <h1 className="text-5xl font-semibold text-[#1C1917] mb-4" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
            AI Trip Planner
          </h1>
          <p className="text-lg text-[#57534E]">Tell us about your dream vacation</p>
          
          {/* Progress */}
          <div className="flex items-center justify-center gap-2 mt-8">
            {[1, 2, 3, 4].map(s => (
              <div
                key={s}
                className={`h-2 rounded-full transition-all ${s <= step ? 'w-12 bg-[#C47245]' : 'w-8 bg-[#E7E5E4]'}`}
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
            {step === 1 && (
              <motion.div
                key="step1"
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                className="space-y-6"
              >
                <h2 className="text-2xl font-medium text-[#2A4B5C] mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Trip Basics
                </h2>
                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium">Destination</Label>
                  <div className="mt-2">
                    <LocationAutocomplete
                      testId={TRIP_PLANNER.destinationInput}
                      value={formData.destination}
                      onChange={(val) => setFormData({ ...formData, destination: val })}
                      placeholder="Where do you want to go?"
                    />
                  </div>
                </div>
                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium">Starting Location</Label>
                  <div className="mt-2">
                    <LocationAutocomplete
                      testId={TRIP_PLANNER.startLocationInput}
                      value={formData.starting_location}
                      onChange={(val) => setFormData({ ...formData, starting_location: val })}
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
                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Travelers</Label>
                  <div className="grid grid-cols-3 gap-4">
                    <div>
                      <label className="text-sm text-[#57534E]">Adults</label>
                      <Input
                        type="number"
                        min="0"
                        value={formData.adults}
                        onChange={(e) => setFormData({ ...formData, adults: parseInt(e.target.value) || 0 })}
                        className="border-[#E7E5E4] mt-1"
                      />
                    </div>
                    <div>
                      <label className="text-sm text-[#57534E]">Children</label>
                      <Input
                        type="number"
                        min="0"
                        value={formData.children}
                        onChange={(e) => setFormData({ ...formData, children: parseInt(e.target.value) || 0 })}
                        className="border-[#E7E5E4] mt-1"
                      />
                    </div>
                    <div>
                      <label className="text-sm text-[#57534E]">Seniors</label>
                      <Input
                        type="number"
                        min="0"
                        value={formData.seniors}
                        onChange={(e) => setFormData({ ...formData, seniors: parseInt(e.target.value) || 0 })}
                        className="border-[#E7E5E4] mt-1"
                      />
                    </div>
                  </div>
                </div>
              </motion.div>
            )}

            {step === 2 && (
              <motion.div
                key="step2"
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                className="space-y-6"
              >
                <h2 className="text-2xl font-medium text-[#2A4B5C] mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Travel Preferences
                </h2>
                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Transportation</Label>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {TRANSPORTATION_OPTIONS.map(option => (
                      <button
                        key={option.value}
                        onClick={() => setFormData({ ...formData, transportation: option.value })}
                        className={`p-4 rounded-xl border-2 transition-all ${
                          formData.transportation === option.value
                            ? 'border-[#C47245] bg-[#C47245]/10'
                            : 'border-[#E7E5E4] hover:border-[#C47245]/50'
                        }`}
                      >
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
                      <button
                        key={level.value}
                        onClick={() => setFormData({ ...formData, budget_level: level.value })}
                        className={`w-full p-4 rounded-xl border-2 transition-all text-left ${
                          formData.budget_level === level.value
                            ? 'border-[#C47245] bg-[#C47245]/10'
                            : 'border-[#E7E5E4] hover:border-[#C47245]/50'
                        }`}
                      >
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
                      <div
                        key={option}
                        onClick={() => toggleArrayItem('accommodation', option)}
                        className={`p-3 rounded-lg border-2 cursor-pointer transition-all ${
                          formData.accommodation.includes(option)
                            ? 'border-[#C47245] bg-[#C47245]/10'
                            : 'border-[#E7E5E4] hover:border-[#C47245]/50'
                        }`}
                      >
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

            {step === 3 && (
              <motion.div
                key="step3"
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                className="space-y-6"
              >
                <h2 className="text-2xl font-medium text-[#2A4B5C] mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Interests & Activities
                </h2>
                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">What interests you?</Label>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                    {INTERESTS.map(interest => (
                      <div
                        key={interest}
                        onClick={() => toggleArrayItem('interests', interest)}
                        className={`p-3 rounded-lg border-2 cursor-pointer transition-all ${
                          formData.interests.includes(interest)
                            ? 'border-[#C47245] bg-[#C47245]/10'
                            : 'border-[#E7E5E4] hover:border-[#C47245]/50'
                        }`}
                      >
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
                      <button
                        key={type.value}
                        onClick={() => setFormData({ ...formData, trip_type: type.value })}
                        className={`p-4 rounded-xl border-2 transition-all ${
                          formData.trip_type === type.value
                            ? 'border-[#C47245] bg-[#C47245]/10'
                            : 'border-[#E7E5E4] hover:border-[#C47245]/50'
                        }`}
                      >
                        <div className="text-sm font-medium text-[#1C1917]">{type.label}</div>
                      </button>
                    ))}
                  </div>
                </div>
              </motion.div>
            )}

            {step === 4 && (
              <motion.div
                key="step4"
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                className="space-y-6"
              >
                <h2 className="text-2xl font-medium text-[#2A4B5C] mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Additional Details
                </h2>
                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium">Dietary Preferences (Optional)</Label>
                  <Input
                    value={formData.dietary_preferences}
                    onChange={(e) => setFormData({ ...formData, dietary_preferences: e.target.value })}
                    placeholder="E.g., Vegetarian, Vegan, Halal, etc."
                    className="border-[#E7E5E4] mt-2"
                  />
                </div>
                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium">Accessibility Requirements (Optional)</Label>
                  <Input
                    value={formData.accessibility_requirements}
                    onChange={(e) => setFormData({ ...formData, accessibility_requirements: e.target.value })}
                    placeholder="Any special accessibility needs?"
                    className="border-[#E7E5E4] mt-2"
                  />
                </div>
                <div>
                  <Label className="text-[#C47245] uppercase tracking-wider text-xs font-medium mb-3 block">Travel Pace</Label>
                  <div className="grid grid-cols-3 gap-3">
                    {['Relaxed', 'Moderate', 'Fast-paced'].map(pace => (
                      <button
                        key={pace}
                        onClick={() => setFormData({ ...formData, travel_pace: pace })}
                        className={`p-3 rounded-lg border-2 transition-all ${
                          formData.travel_pace === pace
                            ? 'border-[#C47245] bg-[#C47245]/10'
                            : 'border-[#E7E5E4] hover:border-[#C47245]/50'
                        }`}
                      >
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
            <Button
              onClick={handlePrev}
              disabled={step === 1}
              variant="outline"
              className="border-[#E7E5E4]"
            >
              <ChevronLeft size={20} />
              Previous
            </Button>
            {step < totalSteps ? (
              <Button
                data-testid={TRIP_PLANNER.submitButton}
                onClick={handleNext}
                className="bg-[#C47245] hover:bg-[#A85D38]"
              >
                Next
                <ChevronRight size={20} />
              </Button>
            ) : (
              <Button
                data-testid={TRIP_PLANNER.submitButton}
                onClick={handleSubmit}
                disabled={loading}
                className="bg-[#C47245] hover:bg-[#A85D38]"
              >
                {loading ? (
                  <>Generating Plans...</>
                ) : (
                  <>
                    <Sparkles size={20} />
                    Generate Plans
                  </>
                )}
              </Button>
            )}
          </div>
        </motion.div>
      </div>
    </div>
  );
};

export default TripPlannerPage;
