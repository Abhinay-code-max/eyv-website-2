import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { motion, AnimatePresence } from 'framer-motion';
import { Plane, Hotel, Search, MapPin, Calendar, Users, Star, Wifi, Car, Coffee, ArrowLeft, Check, X } from 'lucide-react';
import { API_URL } from '../constants';
import { BOOKINGS, DASHBOARD } from '../constants/testIds';
import EYVLogo from '../components/EYVLogo';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';

// Helper: pick the right currency symbol from a price object
const currencySymbol = (priceObj) => {
  const c = (priceObj?.currency || 'INR').toUpperCase();
  if (c === 'INR') return '₹';
  if (c === 'EUR') return '€';
  if (c === 'GBP') return '£';
  return '$';
};

const fmt = (priceObj, field = 'total') => {
  const sym = currencySymbol(priceObj);
  const val = priceObj?.[field] ?? 0;
  return `${sym}${Number(val).toLocaleString('en-IN')}`;
};

const BookingPage = ({ user }) => {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState('flights');
  const [loading, setLoading] = useState(false);
  const [flights, setFlights] = useState([]);
  const [hotels, setHotels] = useState([]);
  const [bookings, setBookings] = useState([]);
  const [showBookingModal, setShowBookingModal] = useState(false);
  const [selectedItem, setSelectedItem] = useState(null);
  const [bookingSuccess, setBookingSuccess] = useState(null);

  const [flightForm, setFlightForm] = useState({
    origin: '',
    destination: '',
    departure_date: '',
    return_date: '',
    travelers: 1,
  });

  const [hotelForm, setHotelForm] = useState({
    destination: '',
    check_in: '',
    check_out: '',
    travelers: 1,
  });

  useEffect(() => {
    fetchBookings();
  }, []);

  const fetchBookings = async () => {
    try {
      const response = await axios.get(`${API_URL}/bookings`, { withCredentials: true });
      setBookings(response.data.bookings);
    } catch (error) {
      console.error('Error fetching bookings:', error);
    }
  };

  const handleFlightSearch = async () => {
    if (!flightForm.origin || !flightForm.destination || !flightForm.departure_date) {
      alert('Please fill all required fields');
      return;
    }
    setLoading(true);
    try {
      const response = await axios.post(
        `${API_URL}/search/flights`,
        flightForm,
        { withCredentials: true }
      );
      setFlights(response.data.flights);
    } catch (error) {
      console.error('Flight search error:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleHotelSearch = async () => {
    if (!hotelForm.destination || !hotelForm.check_in || !hotelForm.check_out) {
      alert('Please fill all required fields');
      return;
    }
    setLoading(true);
    try {
      const response = await axios.post(
        `${API_URL}/search/hotels`,
        hotelForm,
        { withCredentials: true }
      );
      setHotels(response.data.hotels);
    } catch (error) {
      console.error('Hotel search error:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleBookItem = (item, type) => {
    setSelectedItem({ item, type });
    setShowBookingModal(true);
  };

  const confirmBooking = async () => {
    try {
      const bookingResponse = await axios.post(
        `${API_URL}/bookings`,
        {
          booking_type: selectedItem.type,
          item_id: selectedItem.item.id,
          item_data: selectedItem.item,
        },
        { withCredentials: true }
      );
      
      const checkoutResponse = await axios.post(
        `${API_URL}/payments/checkout`,
        {
          booking_id: bookingResponse.data.booking_id,
          origin_url: window.location.origin,
        },
        { withCredentials: true }
      );
      
      if (checkoutResponse.data.url) {
        window.location.href = checkoutResponse.data.url;
      } else {
        setBookingSuccess(bookingResponse.data);
        setShowBookingModal(false);
        fetchBookings();
      }
    } catch (error) {
      console.error('Booking error:', error);
      alert('Booking failed. Please try again.');
    }
  };

  return (
    <div className="min-h-screen bg-[#FDFBF7]">
      {/* Header */}
      <div className="glass sticky top-0 z-50 border-b border-[#E7E5E4]">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button
              onClick={() => navigate('/dashboard')}
              variant="ghost"
              className="text-[#57534E]"
            >
              <ArrowLeft size={20} />
            </Button>
            <EYVLogo size="small" />
          </div>
          <h2 className="text-2xl font-medium text-[#2A4B5C]" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
            Book Your Travel
          </h2>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-8">
        {/* Tabs */}
        <div className="flex gap-2 mb-8 border-b border-[#E7E5E4]">
          <button
            data-testid={BOOKINGS.searchFlightsTab}
            onClick={() => setActiveTab('flights')}
            className={`px-6 py-3 font-medium flex items-center gap-2 transition-colors ${
              activeTab === 'flights' ? 'text-[#C47245] border-b-2 border-[#C47245]' : 'text-[#57534E]'
            }`}
          >
            <Plane size={18} />
            Flights
          </button>
          <button
            data-testid={BOOKINGS.searchHotelsTab}
            onClick={() => setActiveTab('hotels')}
            className={`px-6 py-3 font-medium flex items-center gap-2 transition-colors ${
              activeTab === 'hotels' ? 'text-[#C47245] border-b-2 border-[#C47245]' : 'text-[#57534E]'
            }`}
          >
            <Hotel size={18} />
            Hotels
          </button>
          <button
            data-testid={BOOKINGS.myBookingsList}
            onClick={() => setActiveTab('bookings')}
            className={`px-6 py-3 font-medium flex items-center gap-2 transition-colors ${
              activeTab === 'bookings' ? 'text-[#C47245] border-b-2 border-[#C47245]' : 'text-[#57534E]'
            }`}
          >
            <Check size={18} />
            My Bookings ({bookings.length})
          </button>
        </div>

        {/* Flights Tab */}
        {activeTab === 'flights' && (
          <div>
            <div className="bg-white rounded-2xl p-6 border border-[#E7E5E4] mb-6">
              <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
                <div>
                  <Label className="text-xs uppercase tracking-wider text-[#C47245] font-medium">From</Label>
                  <Input
                    data-testid={BOOKINGS.flightOriginInput}
                    value={flightForm.origin}
                    onChange={(e) => setFlightForm({ ...flightForm, origin: e.target.value })}
                    placeholder="Origin city"
                    className="mt-1 border-[#E7E5E4]"
                  />
                </div>
                <div>
                  <Label className="text-xs uppercase tracking-wider text-[#C47245] font-medium">To</Label>
                  <Input
                    data-testid={BOOKINGS.flightDestinationInput}
                    value={flightForm.destination}
                    onChange={(e) => setFlightForm({ ...flightForm, destination: e.target.value })}
                    placeholder="Destination"
                    className="mt-1 border-[#E7E5E4]"
                  />
                </div>
                <div>
                  <Label className="text-xs uppercase tracking-wider text-[#C47245] font-medium">Departure</Label>
                  <Input
                    data-testid={BOOKINGS.flightDepartureInput}
                    type="date"
                    value={flightForm.departure_date}
                    onChange={(e) => setFlightForm({ ...flightForm, departure_date: e.target.value })}
                    className="mt-1 border-[#E7E5E4]"
                  />
                </div>
                <div>
                  <Label className="text-xs uppercase tracking-wider text-[#C47245] font-medium">Return</Label>
                  <Input
                    type="date"
                    value={flightForm.return_date}
                    onChange={(e) => setFlightForm({ ...flightForm, return_date: e.target.value })}
                    className="mt-1 border-[#E7E5E4]"
                  />
                </div>
                <div className="flex items-end">
                  <Button
                    data-testid={BOOKINGS.flightSearchButton}
                    onClick={handleFlightSearch}
                    disabled={loading}
                    className="w-full bg-[#C47245] hover:bg-[#A85D38]"
                  >
                    <Search size={18} />
                    {loading ? 'Searching...' : 'Search'}
                  </Button>
                </div>
              </div>
            </div>

            {flights.length > 0 && (
              <div className="space-y-4">
                {flights.map((flight) => (
                  <motion.div
                    key={flight.id}
                    data-testid={BOOKINGS.flightCard}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="bg-white rounded-2xl p-6 border border-[#E7E5E4] hover:shadow-lg transition-all"
                  >
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-center">
                      <div>
                        <div className="font-medium text-[#1C1917]">{flight.airline}</div>
                        <div className="text-sm text-[#57534E]">{flight.flight_number}</div>
                        <div className="text-xs text-[#86A8B3] mt-1">{flight.cabin_class}</div>
                      </div>
                      <div className="flex items-center gap-4">
                        <div>
                          <div className="text-2xl font-medium text-[#1C1917]" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                            {flight.departure.time}
                          </div>
                          <div className="text-sm text-[#57534E]">{flight.departure.airport}</div>
                        </div>
                        <div className="flex-1 text-center">
                          <div className="text-xs text-[#86A8B3]">{flight.duration}</div>
                          <div className="border-t border-[#E7E5E4] my-1 relative">
                            <Plane size={12} className="absolute -top-2 left-1/2 -translate-x-1/2 text-[#C47245]" />
                          </div>
                          <div className="text-xs text-[#57534E]">
                            {flight.stops === 0 ? 'Non-stop' : `${flight.stops} stop${flight.stops > 1 ? 's' : ''}`}
                          </div>
                        </div>
                        <div>
                          <div className="text-2xl font-medium text-[#1C1917]" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                            {flight.arrival.time}
                          </div>
                          <div className="text-sm text-[#57534E]">{flight.arrival.airport}</div>
                        </div>
                      </div>
                      <div className="text-right md:text-left">
                        <div className="text-sm text-[#57534E]">{flight.baggage}</div>
                        <div className="text-xs text-[#86A8B3] mt-1">{flight.available_seats} seats left</div>
                      </div>
                      <div className="text-right">
                        <div className="text-3xl font-semibold text-[#C47245]">
                          {fmt(flight.price, 'total')}
                        </div>
                        <div className="text-xs text-[#57534E] mb-2">total</div>
                        <Button
                          data-testid={BOOKINGS.bookButton}
                          onClick={() => handleBookItem(flight, 'flight')}
                          className="bg-[#C47245] hover:bg-[#A85D38]"
                        >
                          Book Now
                        </Button>
                      </div>
                    </div>
                  </motion.div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Hotels Tab */}
        {activeTab === 'hotels' && (
          <div>
            <div className="bg-white rounded-2xl p-6 border border-[#E7E5E4] mb-6">
              <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
                <div>
                  <Label className="text-xs uppercase tracking-wider text-[#C47245] font-medium">Destination</Label>
                  <Input
                    data-testid={BOOKINGS.hotelDestinationInput}
                    value={hotelForm.destination}
                    onChange={(e) => setHotelForm({ ...hotelForm, destination: e.target.value })}
                    placeholder="Where?"
                    className="mt-1 border-[#E7E5E4]"
                  />
                </div>
                <div>
                  <Label className="text-xs uppercase tracking-wider text-[#C47245] font-medium">Check-in</Label>
                  <Input
                    data-testid={BOOKINGS.hotelCheckinInput}
                    type="date"
                    value={hotelForm.check_in}
                    onChange={(e) => setHotelForm({ ...hotelForm, check_in: e.target.value })}
                    className="mt-1 border-[#E7E5E4]"
                  />
                </div>
                <div>
                  <Label className="text-xs uppercase tracking-wider text-[#C47245] font-medium">Check-out</Label>
                  <Input
                    data-testid={BOOKINGS.hotelCheckoutInput}
                    type="date"
                    value={hotelForm.check_out}
                    onChange={(e) => setHotelForm({ ...hotelForm, check_out: e.target.value })}
                    className="mt-1 border-[#E7E5E4]"
                  />
                </div>
                <div>
                  <Label className="text-xs uppercase tracking-wider text-[#C47245] font-medium">Guests</Label>
                  <Input
                    type="number"
                    min="1"
                    value={hotelForm.travelers}
                    onChange={(e) => setHotelForm({ ...hotelForm, travelers: parseInt(e.target.value) || 1 })}
                    className="mt-1 border-[#E7E5E4]"
                  />
                </div>
                <div className="flex items-end">
                  <Button
                    data-testid={BOOKINGS.hotelSearchButton}
                    onClick={handleHotelSearch}
                    disabled={loading}
                    className="w-full bg-[#C47245] hover:bg-[#A85D38]"
                  >
                    <Search size={18} />
                    {loading ? 'Searching...' : 'Search'}
                  </Button>
                </div>
              </div>
            </div>

            {hotels.length > 0 && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {hotels.map((hotel) => (
                  <motion.div
                    key={hotel.id}
                    data-testid={BOOKINGS.hotelCard}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="bg-white rounded-2xl overflow-hidden border border-[#E7E5E4] hover:shadow-lg transition-all"
                  >
                    <div className="aspect-video overflow-hidden">
                      <img src={hotel.image_url} alt={hotel.name} className="w-full h-full object-cover" />
                    </div>
                    <div className="p-6">
                      <div className="flex items-start justify-between mb-2">
                        <div>
                          <h3 className="text-xl font-medium text-[#1C1917]" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                            {hotel.name}
                          </h3>
                          <div className="flex items-center gap-1 mt-1">
                            {[...Array(hotel.stars)].map((_, i) => (
                              <Star key={i} size={14} className="fill-[#C47245] text-[#C47245]" />
                            ))}
                          </div>
                        </div>
                        <div className="text-right">
                          <div className="bg-[#C47245] text-white px-3 py-1 rounded-lg text-sm font-medium">
                            {hotel.rating}
                          </div>
                          <div className="text-xs text-[#57534E] mt-1">{hotel.review_count} reviews</div>
                        </div>
                      </div>
                      <div className="flex items-center gap-1 text-sm text-[#57534E] mb-3">
                        <MapPin size={14} />
                        <span className="truncate">{hotel.address}</span>
                      </div>
                      <div className="flex flex-wrap gap-2 mb-4">
                        {hotel.amenities.slice(0, 4).map((amenity, i) => (
                          <span key={i} className="text-xs bg-[#F5F2EB] text-[#57534E] px-2 py-1 rounded-md">
                            {amenity}
                          </span>
                        ))}
                      </div>
                      <div className="flex items-end justify-between pt-4 border-t border-[#E7E5E4]">
                        <div>
                          <div className="text-3xl font-semibold text-[#C47245]">
                            {fmt(hotel.price, 'per_night')}
                          </div>
                          <div className="text-xs text-[#57534E]">per night</div>
                          <div className="text-xs text-[#86A8B3] mt-1">
                            Total: {fmt(hotel.price, 'total')} ({hotel.nights} nights)
                          </div>
                        </div>
                        <Button
                          data-testid={BOOKINGS.bookButton}
                          onClick={() => handleBookItem(hotel, 'hotel')}
                          className="bg-[#C47245] hover:bg-[#A85D38]"
                        >
                          Book Now
                        </Button>
                      </div>
                    </div>
                  </motion.div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* My Bookings Tab */}
        {activeTab === 'bookings' && (
          <div>
            {bookings.length === 0 ? (
              <div className="text-center py-16 bg-white rounded-2xl border border-[#E7E5E4]">
                <Check size={48} className="mx-auto text-[#E7E5E4] mb-4" />
                <p className="text-[#57534E] text-lg">No bookings yet. Search and book your travel!</p>
              </div>
            ) : (
              <div className="space-y-4">
                {bookings.map((booking) => (
                  <div
                    key={booking.booking_id}
                    data-testid={BOOKINGS.bookingCard}
                    className="bg-white rounded-2xl p-6 border border-[#E7E5E4]"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex items-start gap-4">
                        <div className="bg-[#C47245]/10 p-3 rounded-lg">
                          {booking.booking_type === 'flight' ? (
                            <Plane size={24} className="text-[#C47245]" />
                          ) : (
                            <Hotel size={24} className="text-[#C47245]" />
                          )}
                        </div>
                        <div>
                          <h3 className="text-xl font-medium text-[#1C1917]" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                            {booking.item_data.name || `${booking.item_data.airline} ${booking.item_data.flight_number}`}
                          </h3>
                          <p className="text-sm text-[#57534E] mt-1">Confirmation: <span className="font-mono font-medium">{booking.confirmation_code}</span></p>
                          <div className="flex gap-3 mt-2">
                            <span className={`text-xs px-2 py-1 rounded-full ${booking.status === 'confirmed' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                              {booking.status}
                            </span>
                            <span className="text-xs px-2 py-1 rounded-full bg-blue-100 text-blue-700">
                              {booking.payment_status}
                            </span>
                          </div>
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-2xl font-semibold text-[#C47245]">
                          {booking.currency === 'INR' ? '₹' : '$'}{Number(booking.total_amount).toLocaleString('en-IN')}
                        </div>
                        <div className="text-xs text-[#57534E]">{new Date(booking.created_at).toLocaleDateString()}</div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Booking Confirmation Modal */}
      <AnimatePresence>
        {showBookingModal && selectedItem && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
            onClick={() => setShowBookingModal(false)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-white rounded-2xl p-8 max-w-md w-full"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-2xl font-medium text-[#1C1917]" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Confirm Booking
                </h3>
                <button onClick={() => setShowBookingModal(false)}>
                  <X size={24} className="text-[#57534E]" />
                </button>
              </div>
              <div className="space-y-4 mb-6">
                <div className="bg-[#F5F2EB] p-4 rounded-lg">
                  <div className="text-sm text-[#57534E] mb-1">
                    {selectedItem.type === 'flight' ? 'Flight' : 'Hotel'}
                  </div>
                  <div className="font-medium text-[#1C1917]">
                    {selectedItem.item.name || `${selectedItem.item.airline} ${selectedItem.item.flight_number}`}
                  </div>
                </div>
                <div className="flex justify-between border-b border-[#E7E5E4] pb-3">
                  <span className="text-[#57534E]">Total</span>
                  <span className="text-2xl font-semibold text-[#C47245]">
                    {fmt(selectedItem.item.price, 'total')}
                  </span>
                </div>
                <p className="text-sm text-[#57534E] bg-blue-50 p-3 rounded-lg">
                  💳 You'll be redirected to Stripe to complete a secure payment for {fmt(selectedItem.item.price, 'total')}.
                </p>
              </div>
              <div className="flex gap-3">
                <Button
                  onClick={() => setShowBookingModal(false)}
                  variant="outline"
                  className="flex-1"
                >
                  Cancel
                </Button>
                <Button
                  onClick={confirmBooking}
                  className="flex-1 bg-[#C47245] hover:bg-[#A85D38]"
                >
                  Proceed to Payment
                </Button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Success Modal */}
      <AnimatePresence>
        {bookingSuccess && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              className="bg-white rounded-2xl p-8 max-w-md w-full text-center"
            >
              <div className="bg-green-100 rounded-full p-4 w-20 h-20 mx-auto mb-4 flex items-center justify-center">
                <Check size={36} className="text-green-600" />
              </div>
              <h3 className="text-3xl font-semibold text-[#1C1917] mb-2" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                Booking Confirmed!
              </h3>
              <p className="text-[#57534E] mb-4">
                Your confirmation code is
              </p>
              <div className="bg-[#F5F2EB] py-3 px-4 rounded-lg font-mono text-xl text-[#C47245] mb-6">
                {bookingSuccess.confirmation_code}
              </div>
              <Button
                onClick={() => {
                  setBookingSuccess(null);
                  setActiveTab('bookings');
                }}
                className="w-full bg-[#C47245] hover:bg-[#A85D38]"
              >
                View My Bookings
              </Button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default BookingPage;
