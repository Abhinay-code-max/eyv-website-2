import React, { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Plane, Hotel, Search, MapPin, Calendar, Star,
  ArrowLeft, Check, X, Clock, ChevronRight, Filter,
  Zap, TrendingUp, ArrowUpDown, Wifi, Coffee, Car,
  Shield, Luggage, ExternalLink, SlidersHorizontal,
} from 'lucide-react';
import { API_URL } from '../constants';
import { BOOKINGS } from '../constants/testIds';
import EYVLogo from '../components/EYVLogo';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';

/* ── Currency helpers ──────────────────────────────────────────────────── */
const currencySymbol = (c = 'INR') => {
  const code = c.toUpperCase();
  if (code === 'INR') return '₹';
  if (code === 'EUR') return '€';
  if (code === 'GBP') return '£';
  return '$';
};
const fmt = (priceObj, field = 'total') => {
  const sym = currencySymbol(priceObj?.currency);
  const val = priceObj?.[field] ?? 0;
  return `${sym}${Number(val).toLocaleString('en-IN')}`;
};

/* ── Airline logo helper ───────────────────────────────────────────────── */
const AIRLINE_CODES = {
  'IndiGo': '6E', 'indigo': '6E',
  'SpiceJet': 'SG', 'spicejet': 'SG',
  'Air India': 'AI', 'air india': 'AI',
  'Emirates': 'EK', 'emirates': 'EK',
  'Vistara': 'UK', 'vistara': 'UK',
  'GoAir': 'G8', 'go first': 'G8',
  'AirAsia': 'I5', 'airasia': 'I5',
  'flydubai': 'FZ', 'fly dubai': 'FZ',
  'Etihad': 'EY', 'etihad': 'EY',
  'Qatar Airways': 'QR', 'qatar': 'QR',
  'British Airways': 'BA', 'british': 'BA',
  'Lufthansa': 'LH', 'lufthansa': 'LH',
  'Singapore Airlines': 'SQ', 'singapore': 'SQ',
  'United': 'UA', 'american': 'AA', 'delta': 'DL',
};

const getIataCode = (airlineName = '', carrierCode = '') => {
  if (carrierCode && carrierCode.length === 2) return carrierCode.toUpperCase();
  const lower = airlineName.toLowerCase();
  for (const [key, code] of Object.entries(AIRLINE_CODES)) {
    if (lower.includes(key.toLowerCase())) return code;
  }
  return airlineName.slice(0, 2).toUpperCase();
};

const AirlineLogo = ({ airline, carrierCode, size = 40 }) => {
  const iata = getIataCode(airline, carrierCode);
  const [imgError, setImgError] = useState(false);
  const logoUrl = `https://content.airhex.com/content/logos/airlines_${iata}_100_100_s.png`;

  if (imgError) {
    return (
      <div
        className="flex items-center justify-center rounded-xl font-bold text-white text-sm"
        style={{ width: size, height: size, background: '#C47245', minWidth: size }}
      >
        {iata}
      </div>
    );
  }

  return (
    <img
      src={logoUrl}
      alt={airline}
      width={size}
      height={size}
      onError={() => setImgError(true)}
      className="rounded-xl object-contain bg-white border border-[#E7E5E4]"
      style={{ minWidth: size }}
    />
  );
};

/* ── Booking link helper ───────────────────────────────────────────────── */
const getBookingUrl = (flight) => {
  if (flight.booking_url) return flight.booking_url;
  const origin = encodeURIComponent(flight.origin || '');
  const dest = encodeURIComponent(flight.destination || '');
  const date = (flight.departure?.date || '').replace(/-/g, '');
  return `https://www.skyscanner.net/transport/flights/${origin}/${dest}/${date}/?adults=1`;
};

/* ── Skeletons ─────────────────────────────────────────────────────────── */
const SkeletonFlight = () => (
  <div className="bg-white rounded-2xl p-6 border border-[#E7E5E4] animate-pulse">
    <div className="flex gap-4 items-center">
      <div className="h-12 w-12 bg-[#E7E5E4] rounded-xl" />
      <div className="flex-1 grid grid-cols-4 gap-4">
        <div className="space-y-2"><div className="h-4 bg-[#E7E5E4] rounded w-3/4" /><div className="h-3 bg-[#E7E5E4] rounded w-1/2" /></div>
        <div className="space-y-2"><div className="h-6 bg-[#E7E5E4] rounded w-full" /><div className="h-3 bg-[#E7E5E4] rounded w-2/3 mx-auto" /></div>
        <div className="space-y-2"><div className="h-4 bg-[#E7E5E4] rounded w-1/2" /><div className="h-3 bg-[#E7E5E4] rounded w-3/4" /></div>
        <div className="flex justify-end"><div className="h-10 w-24 bg-[#E7E5E4] rounded-xl" /></div>
      </div>
    </div>
  </div>
);

const HotelSkeleton = () => (
  <div className="bg-white rounded-2xl overflow-hidden border border-[#E7E5E4] animate-pulse">
    <div className="h-48 bg-[#E7E5E4]" />
    <div className="p-5 space-y-3">
      <div className="h-5 bg-[#E7E5E4] rounded w-2/3" />
      <div className="h-3 bg-[#E7E5E4] rounded w-full" />
      <div className="h-8 bg-[#E7E5E4] rounded w-1/3 mt-4" />
    </div>
  </div>
);

/* ── Sort/Filter bar ───────────────────────────────────────────────────── */
const SortBar = ({ sort, setSort, filter, setFilter, options }) => (
  <div className="flex flex-wrap items-center gap-3 mb-5">
    <div className="flex items-center gap-1 text-xs text-[#57534E] font-medium">
      <SlidersHorizontal size={14} className="text-[#C47245]" /> Sort:
    </div>
    {options.map(({ key, label, icon: Icon }) => (
      <button key={key} onClick={() => setSort(key)}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all ${
          sort === key
            ? 'bg-[#C47245] text-white shadow-sm'
            : 'bg-white border border-[#E7E5E4] text-[#57534E] hover:border-[#C47245]/40'
        }`}>
        {Icon && <Icon size={12} />}{label}
      </button>
    ))}
    {filter !== undefined && (
      <>
        <div className="w-px h-4 bg-[#E7E5E4]" />
        <button onClick={() => setFilter(f => !f)}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all ${
            filter
              ? 'bg-[#1C1917] text-white'
              : 'bg-white border border-[#E7E5E4] text-[#57534E] hover:border-[#C47245]/40'
          }`}>
          <Zap size={12} /> Non-stop only
        </button>
      </>
    )}
  </div>
);

/* ── Page ──────────────────────────────────────────────────────────────── */
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

  // Sort & filter state
  const [flightSort, setFlightSort] = useState('cheapest');
  const [nonStopOnly, setNonStopOnly] = useState(false);
  const [hotelSort, setHotelSort] = useState('price');

  const [flightForm, setFlightForm] = useState({
    origin: '', destination: '', departure_date: '', return_date: '', travelers: 1,
  });
  const [hotelForm, setHotelForm] = useState({
    destination: '', check_in: '', check_out: '', travelers: 1,
  });

  useEffect(() => { fetchBookings(); }, []);

  const fetchBookings = async () => {
    try {
      const r = await axios.get(`${API_URL}/bookings`, { withCredentials: true });
      setBookings(r.data.bookings);
    } catch (e) { console.error(e); }
  };

  const handleFlightSearch = async () => {
    if (!flightForm.origin || !flightForm.destination || !flightForm.departure_date) {
      alert('Please fill From, To and Departure date'); return;
    }
    setLoading(true); setFlights([]);
    try {
      const r = await axios.post(`${API_URL}/search/flights`, flightForm, { withCredentials: true });
      setFlights(r.data.flights || []);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  const handleHotelSearch = async () => {
    if (!hotelForm.destination || !hotelForm.check_in || !hotelForm.check_out) {
      alert('Please fill all hotel fields'); return;
    }
    setLoading(true); setHotels([]);
    try {
      const r = await axios.post(`${API_URL}/search/hotels`, hotelForm, { withCredentials: true });
      setHotels(r.data.hotels || []);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  const handleBookItem = (item, type) => { setSelectedItem({ item, type }); setShowBookingModal(true); };

  const confirmBooking = async () => {
    try {
      // eslint-disable-next-line no-unused-vars
      const { price, ...itemDataWithoutPrice } = selectedItem.item;
      const br = await axios.post(`${API_URL}/bookings`,
        { booking_type: selectedItem.type, item_id: selectedItem.item.item_id, item_data: itemDataWithoutPrice },
        { withCredentials: true }
      );
      const cr = await axios.post(`${API_URL}/payments/checkout`,
        { booking_id: br.data.booking_id, origin_url: window.location.origin },
        { withCredentials: true }
      );
      if (cr.data.url) { window.location.href = cr.data.url; }
      else { setBookingSuccess(br.data); setShowBookingModal(false); fetchBookings(); }
    } catch (e) { console.error(e); alert('Booking failed. Please try again.'); }
  };

  /* ── Sorted/filtered flight list ── */
  const sortedFlights = useMemo(() => {
    let list = nonStopOnly ? flights.filter(f => f.stops === 0) : [...flights];
    if (flightSort === 'cheapest') list.sort((a, b) => a.price.total - b.price.total);
    else if (flightSort === 'fastest') list.sort((a, b) => (a.duration_mins || 999) - (b.duration_mins || 999));
    else if (flightSort === 'best') {
      list.sort((a, b) => {
        const scoreA = a.price.total * 0.6 + (a.duration_mins || 300) * 10 * 0.4;
        const scoreB = b.price.total * 0.6 + (b.duration_mins || 300) * 10 * 0.4;
        return scoreA - scoreB;
      });
    }
    return list;
  }, [flights, flightSort, nonStopOnly]);

  /* ── Sorted hotel list ── */
  const sortedHotels = useMemo(() => {
    const list = [...hotels];
    if (hotelSort === 'price') list.sort((a, b) => a.price.per_night - b.price.per_night);
    else if (hotelSort === 'rating') list.sort((a, b) => (b.rating ?? -1) - (a.rating ?? -1));
    else if (hotelSort === 'stars') list.sort((a, b) => b.stars - a.stars);
    return list;
  }, [hotels, hotelSort]);

  const tabs = [
    { id: 'flights', label: 'Flights', Icon: Plane, testId: BOOKINGS.searchFlightsTab },
    { id: 'hotels', label: 'Hotels', Icon: Hotel, testId: BOOKINGS.searchHotelsTab },
    { id: 'bookings', label: `My Bookings (${bookings.length})`, Icon: Check, testId: BOOKINGS.myBookingsList },
  ];

  return (
    <motion.div className="min-h-screen bg-[#FDFBF7]"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.4 }}>

      {/* Header */}
      <div className="sticky top-0 z-50 bg-[#FDFBF7]/80 backdrop-blur-xl border-b border-[#E7E5E4] shadow-sm">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button onClick={() => navigate('/dashboard')} variant="ghost"
              className="text-[#57534E] hover:text-[#C47245]">
              <ArrowLeft size={20} />
            </Button>
            <EYVLogo size="small" />
          </div>
          <h2 className="text-2xl font-medium text-[#2A4B5C]"
            style={{ fontFamily: 'Cormorant Garamond, serif' }}>Book Your Travel</h2>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-8">
        {/* Tabs */}
        <div className="relative flex gap-1 mb-8 border-b border-[#E7E5E4]">
          {tabs.map(({ id, label, Icon, testId }) => (
            <button key={id} data-testid={testId} onClick={() => setActiveTab(id)}
              className={`relative px-6 py-3 font-medium flex items-center gap-2 transition-colors ${
                activeTab === id ? 'text-[#C47245]' : 'text-[#57534E] hover:text-[#1C1917]'
              }`}>
              <Icon size={17} />{label}
              {activeTab === id && (
                <motion.div layoutId="tab-ul"
                  className="absolute bottom-0 left-0 right-0 h-0.5 bg-[#C47245] rounded-full"
                  transition={{ type: 'spring', stiffness: 400, damping: 30 }} />
              )}
            </button>
          ))}
        </div>

        <AnimatePresence mode="wait">

          {/* ── Flights Tab ── */}
          {activeTab === 'flights' && (
            <motion.div key="flights"
              initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -16 }} transition={{ duration: 0.3 }}>

              {/* Search form */}
              <div className="bg-white rounded-2xl p-6 border border-[#E7E5E4] mb-6 shadow-sm">
                <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
                  {[
                    { label: 'FROM', field: 'origin', testId: BOOKINGS.flightOriginInput, placeholder: 'City or airport', type: 'text' },
                    { label: 'TO', field: 'destination', testId: BOOKINGS.flightDestinationInput, placeholder: 'City or airport', type: 'text' },
                    { label: 'DEPARTURE', field: 'departure_date', testId: BOOKINGS.flightDepartureInput, type: 'date' },
                    { label: 'RETURN', field: 'return_date', type: 'date' },
                  ].map(({ label, field, testId, placeholder, type }) => (
                    <div key={field}>
                      <Label className="text-xs tracking-widest text-[#C47245] font-semibold">{label}</Label>
                      <Input data-testid={testId} type={type}
                        value={flightForm[field]}
                        onChange={e => setFlightForm({ ...flightForm, [field]: e.target.value })}
                        placeholder={placeholder}
                        className="mt-1 border-[#E7E5E4] focus:border-[#C47245]" />
                    </div>
                  ))}
                  <div className="flex items-end">
                    <Button data-testid={BOOKINGS.flightSearchButton} onClick={handleFlightSearch}
                      disabled={loading}
                      className="w-full bg-[#C47245] hover:bg-[#A85D38] gap-2 transition-all active:scale-95">
                      <Search size={16} />{loading ? 'Searching...' : 'Search'}
                    </Button>
                  </div>
                </div>
              </div>

              {/* Sort bar */}
              {(flights.length > 0 || loading) && (
                <SortBar
                  sort={flightSort} setSort={setFlightSort}
                  filter={nonStopOnly} setFilter={setNonStopOnly}
                  options={[
                    { key: 'cheapest', label: 'Cheapest', icon: TrendingUp },
                    { key: 'fastest', label: 'Fastest', icon: Zap },
                    { key: 'best', label: 'Best Value', icon: ArrowUpDown },
                  ]}
                />
              )}

              {loading && <div className="space-y-4">{[1,2,3].map(i => <SkeletonFlight key={i} />)}</div>}

              {!loading && sortedFlights.length > 0 && (
                <div className="space-y-3">
                  {sortedFlights.map((flight, idx) => (
                    <motion.div key={flight.id} data-testid={BOOKINGS.flightCard}
                      initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: idx * 0.06 }}
                      whileHover={{ y: -2, boxShadow: '0 12px 40px -12px rgba(28,25,23,0.12)' }}
                      className="bg-white rounded-2xl p-5 border border-[#E7E5E4] transition-all group">
                      <div className="flex items-center gap-4">

                        {/* Airline logo + name */}
                        <div className="flex flex-col items-center gap-1.5 w-20 shrink-0">
                          <AirlineLogo airline={flight.airline} carrierCode={flight.carrier_code} size={44} />
                          <span className="text-[10px] text-[#57534E] font-medium text-center leading-tight">{flight.airline}</span>
                          <span className="text-[10px] text-[#86A8B3]">{flight.flight_number}</span>
                        </div>

                        {/* Flight route */}
                        <div className="flex-1 flex items-center gap-3">
                          <div className="text-center">
                            <div className="text-2xl font-semibold text-[#1C1917]"
                              style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                              {flight.departure.time}
                            </div>
                            <div className="text-xs font-medium text-[#57534E] mt-0.5">{flight.departure.airport}</div>
                          </div>

                          <div className="flex-1 flex flex-col items-center gap-1">
                            <span className="text-xs text-[#86A8B3]">{flight.duration}</span>
                            <div className="w-full flex items-center gap-1">
                              <div className="flex-1 h-px bg-[#E7E5E4]" />
                              <Plane size={14} className="text-[#C47245]" />
                              <div className="flex-1 h-px bg-[#E7E5E4]" />
                            </div>
                            <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                              flight.stops === 0
                                ? 'bg-green-50 text-green-600'
                                : 'bg-amber-50 text-amber-600'
                            }`}>
                              {flight.stops === 0 ? 'Non-stop' : `${flight.stops} stop`}
                            </span>
                          </div>

                          <div className="text-center">
                            <div className="text-2xl font-semibold text-[#1C1917]"
                              style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                              {flight.arrival.time}
                            </div>
                            <div className="text-xs font-medium text-[#57534E] mt-0.5">{flight.arrival.airport}</div>
                          </div>
                        </div>

                        {/* Details */}
                        <div className="hidden md:flex flex-col gap-1.5 w-36 shrink-0">
                          <div className="flex items-center gap-1.5 text-xs text-[#57534E]">
                            <Luggage size={12} className="text-[#86A8B3]" />
                            {flight.baggage || '1 carry-on'}
                          </div>
                          <div className="flex items-center gap-1.5 text-xs text-[#57534E]">
                            <Shield size={12} className="text-[#86A8B3]" />
                            {flight.cabin_class || 'Economy'}
                          </div>
                          {flight.aircraft && (
                            <div className="flex items-center gap-1.5 text-xs text-[#86A8B3]">
                              <Plane size={12} />
                              {flight.aircraft}
                            </div>
                          )}
                        </div>

                        {/* Price + actions */}
                        <div className="text-right shrink-0">
                          <div className="text-3xl font-semibold text-[#C47245]">
                            {fmt(flight.price, 'total')}
                          </div>
                          <div className="text-xs text-[#57534E] mb-3">per person</div>
                          <div className="flex gap-2 justify-end">
                            <a href={getBookingUrl(flight)} target="_blank" rel="noopener noreferrer"
                              className="flex items-center gap-1 px-3 py-2 rounded-xl text-xs font-medium border border-[#E7E5E4] text-[#57534E] hover:border-[#C47245]/40 hover:text-[#C47245] transition-all">
                              <ExternalLink size={12} /> View
                            </a>
                            <Button data-testid={BOOKINGS.bookButton}
                              onClick={() => handleBookItem(flight, 'flight')}
                              className="bg-[#C47245] hover:bg-[#A85D38] transition-all active:scale-95 gap-1 text-sm px-4">
                              Book <ChevronRight size={14} />
                            </Button>
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  ))}
                </div>
              )}

              {!loading && flights.length === 0 && (
                <div className="text-center py-20 bg-white rounded-3xl border border-dashed border-[#E7E5E4]">
                  <Plane size={40} className="text-[#C47245]/40 mx-auto mb-4" />
                  <p className="text-[#57534E]">Search for flights to see results</p>
                </div>
              )}
            </motion.div>
          )}

          {/* ── Hotels Tab ── */}
          {activeTab === 'hotels' && (
            <motion.div key="hotels"
              initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -16 }} transition={{ duration: 0.3 }}>

              <div className="bg-white rounded-2xl p-6 border border-[#E7E5E4] mb-6 shadow-sm">
                <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
                  {[
                    { label: 'DESTINATION', field: 'destination', testId: BOOKINGS.hotelDestinationInput, placeholder: 'City or area', type: 'text' },
                    { label: 'CHECK-IN', field: 'check_in', testId: BOOKINGS.hotelCheckinInput, type: 'date' },
                    { label: 'CHECK-OUT', field: 'check_out', testId: BOOKINGS.hotelCheckoutInput, type: 'date' },
                  ].map(({ label, field, testId, placeholder, type }) => (
                    <div key={field}>
                      <Label className="text-xs tracking-widest text-[#C47245] font-semibold">{label}</Label>
                      <Input data-testid={testId} type={type}
                        value={hotelForm[field]}
                        onChange={e => setHotelForm({ ...hotelForm, [field]: e.target.value })}
                        placeholder={placeholder}
                        className="mt-1 border-[#E7E5E4] focus:border-[#C47245]" />
                    </div>
                  ))}
                  <div>
                    <Label className="text-xs tracking-widest text-[#C47245] font-semibold">GUESTS</Label>
                    <Input type="number" min="1" value={hotelForm.travelers}
                      onChange={e => setHotelForm({ ...hotelForm, travelers: parseInt(e.target.value) || 1 })}
                      className="mt-1 border-[#E7E5E4] focus:border-[#C47245]" />
                  </div>
                  <div className="flex items-end">
                    <Button data-testid={BOOKINGS.hotelSearchButton} onClick={handleHotelSearch}
                      disabled={loading}
                      className="w-full bg-[#C47245] hover:bg-[#A85D38] gap-2 transition-all active:scale-95">
                      <Search size={16} />{loading ? 'Searching...' : 'Search'}
                    </Button>
                  </div>
                </div>
              </div>

              {/* Hotel sort bar */}
              {(hotels.length > 0 || loading) && (
                <SortBar
                  sort={hotelSort} setSort={setHotelSort}
                  options={[
                    { key: 'price', label: 'Lowest Price', icon: TrendingUp },
                    { key: 'rating', label: 'Highest Rated', icon: Star },
                    { key: 'stars', label: 'Star Rating', icon: Filter },
                  ]}
                />
              )}

              {loading && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {[1,2,3,4].map(i => <HotelSkeleton key={i} />)}
                </div>
              )}

              {!loading && sortedHotels.length > 0 && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {sortedHotels.map((hotel, idx) => (
                    <motion.div key={hotel.id} data-testid={BOOKINGS.hotelCard}
                      initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: idx * 0.07 }}
                      whileHover={{ y: -5, boxShadow: '0 20px 50px -16px rgba(28,25,23,0.15)' }}
                      className="bg-white rounded-2xl overflow-hidden border border-[#E7E5E4] transition-all group">

                      {/* Hotel image */}
                      <div className="relative h-48 overflow-hidden">
                        <img src={hotel.image_url || 'https://images.unsplash.com/photo-1566073771259-6a8506099945?w=600'}
                          alt={hotel.name}
                          className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
                          onError={e => { e.target.src = 'https://images.unsplash.com/photo-1566073771259-6a8506099945?w=600'; }}
                        />
                        <div className="absolute inset-0 bg-gradient-to-t from-black/40 to-transparent" />
                        {/* Star badges */}
                        <div className="absolute bottom-3 left-3 flex gap-0.5">
                          {[...Array(Math.min(hotel.stars || 3, 5))].map((_, i) => (
                            <Star key={i} size={12} className="fill-yellow-400 text-yellow-400" />
                          ))}
                        </div>
                        {/* Rating badge - hidden when no real rating data is available */}
                        {(hotel.rating ?? null) !== null && (
                          <div className="absolute top-3 right-3 bg-[#C47245] text-white text-sm font-bold px-2.5 py-1 rounded-lg">
                            {hotel.rating?.toFixed ? hotel.rating.toFixed(1) : hotel.rating}
                          </div>
                        )}
                      </div>

                      <div className="p-5">
                        <div className="flex items-start justify-between mb-2">
                          <div>
                            <h3 className="text-xl font-medium text-[#1C1917] leading-tight"
                              style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                              {hotel.name}
                            </h3>
                            {hotel.review_count > 0 && (
                              <p className="text-xs text-[#86A8B3] mt-0.5">{hotel.review_count.toLocaleString()} reviews</p>
                            )}
                          </div>
                        </div>

                        {hotel.address && (
                          <div className="flex items-center gap-1.5 text-xs text-[#57534E] mb-3">
                            <MapPin size={12} className="text-[#C47245] shrink-0" />
                            <span className="truncate">{hotel.address}</span>
                          </div>
                        )}

                        {/* Amenities */}
                        <div className="flex flex-wrap gap-1.5 mb-4">
                          {(hotel.amenities || []).slice(0, 5).map((amenity, i) => (
                            <span key={i} className="text-xs bg-[#F5F2EB] text-[#57534E] px-2 py-0.5 rounded-md">
                              {amenity}
                            </span>
                          ))}
                        </div>

                        {/* Cancellation */}
                        {hotel.cancellation && (
                          <div className="flex items-center gap-1.5 text-xs mb-3">
                            <Shield size={11} className={hotel.cancellation.includes('Free') ? 'text-green-500' : 'text-[#86A8B3]'} />
                            <span className={hotel.cancellation.includes('Free') ? 'text-green-600 font-medium' : 'text-[#57534E]'}>
                              {hotel.cancellation}
                            </span>
                          </div>
                        )}

                        <div className="flex items-end justify-between pt-4 border-t border-[#E7E5E4]">
                          <div>
                            <div className="text-3xl font-semibold text-[#C47245]">
                              {fmt(hotel.price, 'per_night')}
                            </div>
                            <div className="text-xs text-[#57534E]">per night</div>
                            <div className="text-xs text-[#86A8B3] mt-0.5">
                              Total: {fmt(hotel.price, 'total')} · {hotel.nights} nights
                            </div>
                          </div>
                          <div className="flex gap-2">
                            {hotel.booking_url && (
                              <a href={hotel.booking_url} target="_blank" rel="noopener noreferrer"
                                className="flex items-center gap-1 px-3 py-2 rounded-xl text-xs font-medium border border-[#E7E5E4] text-[#57534E] hover:border-[#C47245]/40 hover:text-[#C47245] transition-all">
                                <ExternalLink size={12} /> View
                              </a>
                            )}
                            <Button data-testid={BOOKINGS.bookButton}
                              onClick={() => handleBookItem(hotel, 'hotel')}
                              className="bg-[#C47245] hover:bg-[#A85D38] transition-all active:scale-95 gap-1 text-sm">
                              Book <ChevronRight size={14} />
                            </Button>
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  ))}
                </div>
              )}

              {!loading && hotels.length === 0 && (
                <div className="text-center py-20 bg-white rounded-3xl border border-dashed border-[#E7E5E4]">
                  <Hotel size={40} className="text-[#C47245]/40 mx-auto mb-4" />
                  <p className="text-[#57534E]">Search for hotels to see results</p>
                </div>
              )}
            </motion.div>
          )}

          {/* ── My Bookings Tab ── */}
          {activeTab === 'bookings' && (
            <motion.div key="bookings"
              initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -16 }} transition={{ duration: 0.3 }}>
              {bookings.length === 0 ? (
                <div className="text-center py-20 bg-white rounded-3xl border border-dashed border-[#E7E5E4]">
                  <div className="w-20 h-20 rounded-full bg-[#C47245]/10 flex items-center justify-center mx-auto mb-4">
                    <Check size={36} className="text-[#C47245]" />
                  </div>
                  <p className="text-[#57534E] text-lg mb-2">No bookings yet</p>
                  <p className="text-sm text-[#86A8B3] mb-6">Search and book your travel to get started</p>
                  <Button onClick={() => setActiveTab('flights')}
                    className="bg-[#C47245] hover:bg-[#A85D38] gap-2">
                    <Plane size={16} /> Search Flights
                  </Button>
                </div>
              ) : (
                <div className="space-y-4">
                  {bookings.map((booking, idx) => (
                    <motion.div key={booking.booking_id} data-testid={BOOKINGS.bookingCard}
                      initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: idx * 0.06 }}
                      whileHover={{ y: -2 }}
                      className="bg-white rounded-2xl p-6 border border-[#E7E5E4] hover:shadow-md transition-all">
                      <div className="flex items-start justify-between">
                        <div className="flex items-start gap-4">
                          <div className="bg-[#C47245]/10 p-3 rounded-xl">
                            {booking.booking_type === 'flight'
                              ? <Plane size={22} className="text-[#C47245]" />
                              : <Hotel size={22} className="text-[#C47245]" />}
                          </div>
                          <div>
                            <h3 className="text-xl font-medium text-[#1C1917]"
                              style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                              {booking.item_data.name || `${booking.item_data.airline} ${booking.item_data.flight_number}`}
                            </h3>
                            <p className="text-sm text-[#57534E] mt-1">
                              Confirmation: <span className="font-mono font-medium text-[#1C1917]">{booking.confirmation_code}</span>
                            </p>
                            <div className="flex gap-2 mt-2">
                              <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${
                                booking.status === 'confirmed' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                              }`}>{booking.status}</span>
                              <span className="text-xs px-2.5 py-1 rounded-full bg-blue-100 text-blue-700 font-medium">
                                {booking.payment_status}
                              </span>
                            </div>
                          </div>
                        </div>
                        <div className="text-right">
                          <div className="text-2xl font-semibold text-[#C47245]">
                            {currencySymbol(booking.currency)}{Number(booking.total_amount).toLocaleString('en-IN')}
                          </div>
                          <div className="flex items-center gap-1 text-xs text-[#57534E] mt-1 justify-end">
                            <Clock size={11} />{new Date(booking.created_at).toLocaleDateString()}
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  ))}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Booking Confirmation Modal */}
      <AnimatePresence>
        {showBookingModal && selectedItem && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4"
            onClick={() => setShowBookingModal(false)}>
            <motion.div
              initial={{ scale: 0.92, opacity: 0, y: 20 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.92, opacity: 0, y: 20 }}
              transition={{ type: 'spring', stiffness: 300, damping: 25 }}
              className="bg-white rounded-3xl p-8 max-w-md w-full shadow-2xl"
              onClick={e => e.stopPropagation()}>
              <div className="flex items-center justify-between mb-6">
                <h3 className="text-2xl font-medium text-[#1C1917]"
                  style={{ fontFamily: 'Cormorant Garamond, serif' }}>Confirm Booking</h3>
                <button onClick={() => setShowBookingModal(false)}
                  className="text-[#57534E] hover:text-[#1C1917] hover:bg-[#F5F2EB] p-1.5 rounded-full transition-all">
                  <X size={22} />
                </button>
              </div>
              <div className="space-y-4 mb-6">
                <div className="bg-[#F5F2EB] p-4 rounded-2xl flex items-center gap-3">
                  {selectedItem.type === 'flight' && (
                    <AirlineLogo airline={selectedItem.item.airline} carrierCode={selectedItem.item.carrier_code} size={40} />
                  )}
                  <div>
                    <div className="text-xs uppercase tracking-wider text-[#C47245] mb-0.5">
                      {selectedItem.type === 'flight' ? 'Flight' : 'Hotel'}
                    </div>
                    <div className="font-semibold text-[#1C1917]">
                      {selectedItem.item.name || `${selectedItem.item.airline} ${selectedItem.item.flight_number}`}
                    </div>
                  </div>
                </div>
                <div className="flex justify-between items-center border-b border-[#E7E5E4] pb-4">
                  <span className="text-[#57534E]">Total</span>
                  <span className="text-3xl font-semibold text-[#C47245]">{fmt(selectedItem.item.price, 'total')}</span>
                </div>
                <p className="text-sm text-[#57534E] bg-blue-50 p-3 rounded-xl">
                  💳 You'll be redirected to Stripe to complete secure payment.
                </p>
              </div>
              <div className="flex gap-3">
                <Button onClick={() => setShowBookingModal(false)} variant="outline" className="flex-1 rounded-xl">Cancel</Button>
                <Button onClick={confirmBooking}
                  className="flex-1 bg-[#C47245] hover:bg-[#A85D38] rounded-xl transition-all active:scale-95">
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
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4">
            <motion.div
              initial={{ scale: 0.85, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
              transition={{ type: 'spring', stiffness: 260, damping: 20 }}
              className="bg-white rounded-3xl p-8 max-w-md w-full text-center shadow-2xl">
              <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }}
                transition={{ delay: 0.2, type: 'spring', stiffness: 300 }}
                className="bg-green-100 rounded-full p-4 w-20 h-20 mx-auto mb-5 flex items-center justify-center">
                <Check size={36} className="text-green-600" />
              </motion.div>
              <h3 className="text-3xl font-semibold text-[#1C1917] mb-2"
                style={{ fontFamily: 'Cormorant Garamond, serif' }}>Booking Confirmed!</h3>
              <p className="text-[#57534E] mb-4">Your confirmation code is</p>
              <div className="bg-[#F5F2EB] py-3 px-4 rounded-xl font-mono text-xl text-[#C47245] mb-6 tracking-widest">
                {bookingSuccess.confirmation_code}
              </div>
              {typeof bookingSuccess.total_amount === 'number' && (
                <p className="text-[#57534E] mb-6">
                  Total: <span className="font-semibold text-[#1C1917]">
                    {fmt({ total: bookingSuccess.total_amount, currency: bookingSuccess.currency }, 'total')}
                  </span>
                </p>
              )}
              <Button onClick={() => { setBookingSuccess(null); setActiveTab('bookings'); }}
                className="w-full bg-[#C47245] hover:bg-[#A85D38] rounded-xl transition-all active:scale-95">
                View My Bookings
              </Button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
};

export default BookingPage;
