import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { MapPin, Calendar, Users, Search, Plane, Hotel, Utensils, Activity, Star, ChevronRight, Globe } from 'lucide-react';
import EYVLogo from '../components/EYVLogo';
import { HOME } from '../constants/testIds';
import LocationAutocomplete from '../components/LocationAutocomplete';

const HomePage = () => {
  const navigate = useNavigate();
  const [searchData, setSearchData] = useState({
    destination: '',
    startLocation: '',
    departureDate: '',
    returnDate: '',
    travelers: 1,
  });

  const handleSearch = () => {
    navigate('/login');
  };

  const destinations = [
    { name: 'Maldives', image: 'https://images.pexels.com/photos/6875499/pexels-photo-6875499.jpeg', trips: '2,340 trips' },
    { name: 'Switzerland', image: 'https://images.unsplash.com/photo-1558883493-8b86ff880fec', trips: '1,890 trips' },
    { name: 'Bali', image: 'https://images.pexels.com/photos/25706808/pexels-photo-25706808.jpeg', trips: '3,120 trips' },
  ];

  const features = [
    { icon: Plane, title: 'Flight Booking', description: 'Best flight deals aggregated from top airlines' },
    { icon: Hotel, title: 'Hotels & Resorts', description: 'Curated accommodations for every budget' },
    { icon: Utensils, title: 'Dining', description: 'Restaurant recommendations and reservations' },
    { icon: Activity, title: 'Activities', description: 'Experiences from adventure to relaxation' },
  ];

  const reviews = [
    { name: 'Sarah M.', text: 'EYV planned our entire Maldives trip perfectly. The AI suggestions were spot-on!', rating: 5 },
    { name: 'Raj K.', text: 'Saved hours of research. The Luxury plan was incredible value for money.', rating: 5 },
    { name: 'Emily L.', text: 'The AI chatbot was so helpful during our trip. Couldn\'t recommend more!', rating: 5 },
  ];

  return (
    <div data-testid={HOME.heroSection} className="min-h-screen bg-[#FDFBF7]">
      {/* Navigation */}
      <nav className="glass sticky top-0 z-50 border-b border-[#E7E5E4]">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <EYVLogo size="small" />
          <div className="hidden md:flex items-center gap-8">
            <a href="#destinations" className="text-[#57534E] hover:text-[#C47245] transition-colors">Destinations</a>
            <a href="#packages" className="text-[#57534E] hover:text-[#C47245] transition-colors">Packages</a>
            <a href="#about" className="text-[#57534E] hover:text-[#C47245] transition-colors">About</a>
          </div>
          <button
            data-testid={HOME.loginButton}
            onClick={() => navigate('/login')}
            className="bg-[#C47245] text-white px-6 py-2 rounded-full hover:bg-[#A85D38] transition-all hover:shadow-lg"
          >
            Sign In
          </button>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="relative min-h-[90vh] flex items-center overflow-hidden">
        <div className="absolute inset-0">
          <img
            src="https://images.pexels.com/photos/6875499/pexels-photo-6875499.jpeg"
            alt="Tropical paradise"
            className="w-full h-full object-cover"
          />
          <div className="absolute inset-0 bg-gradient-to-r from-black/50 to-transparent"></div>
        </div>

        <div className="relative z-10 max-w-7xl mx-auto px-6 py-20">
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 1 }}
            className="max-w-2xl"
          >
            <h1 className="text-5xl md:text-6xl font-semibold text-white mb-6 tracking-tighter leading-none" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
              Enjoy Your Vacation
            </h1>
            <p className="text-xl md:text-2xl text-white/90 mb-8">
              We Plan Everything.
            </p>
            <p className="text-lg text-white/80 mb-12">
              Complete AI-powered travel planning from flights to activities, all in one place.
            </p>

            {/* Search Box */}
            <div className="bg-white/95 backdrop-blur-xl rounded-2xl p-8 shadow-2xl border border-white/50">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                <div>
                  <label className="text-xs uppercase tracking-wider text-[#C47245] font-medium mb-2 block">Where to?</label>
                  <LocationAutocomplete
                    value={searchData.destination}
                    onChange={(val) => setSearchData({ ...searchData, destination: val })}
                    placeholder="Destination"
                  />
                </div>
                <div>
                  <label className="text-xs uppercase tracking-wider text-[#C47245] font-medium mb-2 block">From</label>
                  <LocationAutocomplete
                    value={searchData.startLocation}
                    onChange={(val) => setSearchData({ ...searchData, startLocation: val })}
                    placeholder="Starting location"
                  />
                </div>
                <div>
                  <label className="text-xs uppercase tracking-wider text-[#C47245] font-medium mb-2 block">Departure</label>
                  <div className="flex items-center gap-2 border border-[#E7E5E4] rounded-lg px-4 py-3">
                    <Calendar size={20} className="text-[#57534E]" />
                    <input
                      type="date"
                      value={searchData.departureDate}
                      onChange={(e) => setSearchData({ ...searchData, departureDate: e.target.value })}
                      className="flex-1 outline-none bg-transparent text-[#1C1917]"
                    />
                  </div>
                </div>
                <div>
                  <label className="text-xs uppercase tracking-wider text-[#C47245] font-medium mb-2 block">Return</label>
                  <div className="flex items-center gap-2 border border-[#E7E5E4] rounded-lg px-4 py-3">
                    <Calendar size={20} className="text-[#57534E]" />
                    <input
                      type="date"
                      value={searchData.returnDate}
                      onChange={(e) => setSearchData({ ...searchData, returnDate: e.target.value })}
                      className="flex-1 outline-none bg-transparent text-[#1C1917]"
                    />
                  </div>
                </div>
                <div className="md:col-span-2">
                  <label className="text-xs uppercase tracking-wider text-[#C47245] font-medium mb-2 block">Travelers</label>
                  <div className="flex items-center gap-2 border border-[#E7E5E4] rounded-lg px-4 py-3">
                    <Users size={20} className="text-[#57534E]" />
                    <input
                      type="number"
                      min="1"
                      value={searchData.travelers}
                      onChange={(e) => setSearchData({ ...searchData, travelers: e.target.value })}
                      className="flex-1 outline-none bg-transparent text-[#1C1917]"
                    />
                  </div>
                </div>
              </div>
              <button
                data-testid={HOME.getStartedButton}
                onClick={handleSearch}
                className="w-full bg-[#C47245] text-white py-4 px-6 rounded-xl font-medium text-lg flex items-center justify-center gap-2 transition-all hover:bg-[#A85D38] hover:shadow-lg"
              >
                <Search size={20} />
                Plan My Vacation
              </button>
            </div>
          </motion.div>
        </div>
      </section>

      {/* Popular Destinations */}
      <section id="destinations" className="py-24 px-6">
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-4xl md:text-5xl font-semibold text-[#1C1917] mb-4" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
              Popular Destinations
            </h2>
            <p className="text-lg text-[#57534E]">Discover the world's most beautiful places</p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {destinations.map((dest, idx) => (
              <motion.div
                key={idx}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                transition={{ delay: idx * 0.2 }}
                className="group relative overflow-hidden rounded-2xl border border-[#E7E5E4] cursor-pointer"
              >
                <div className="aspect-[4/5] overflow-hidden">
                  <img
                    src={dest.image}
                    alt={dest.name}
                    className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110"
                  />
                </div>
                <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent"></div>
                <div className="absolute bottom-0 left-0 right-0 p-6 text-white">
                  <h3 className="text-2xl font-medium mb-1" style={{ fontFamily: 'Cormorant Garamond, serif' }}>{dest.name}</h3>
                  <p className="text-white/80 text-sm">{dest.trips}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section id="packages" className="py-24 px-6 bg-[#F5F2EB]">
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-4xl md:text-5xl font-semibold text-[#1C1917] mb-4" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
              Everything You Need
            </h2>
            <p className="text-lg text-[#57534E]">One platform for your complete vacation</p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8">
            {features.map((feature, idx) => (
              <motion.div
                key={idx}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                transition={{ delay: idx * 0.1 }}
                className="bg-white p-8 rounded-xl border border-[#E7E5E4] hover:shadow-xl transition-all"
              >
                <feature.icon size={40} className="text-[#C47245] mb-4" />
                <h3 className="text-xl font-medium text-[#2A4B5C] mb-2" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  {feature.title}
                </h3>
                <p className="text-[#57534E]">{feature.description}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Adventure Activities */}
      <section className="py-24 px-6">
        <div className="max-w-7xl mx-auto">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-12 items-center">
            <motion.div
              initial={{ opacity: 0, x: -30 }}
              whileInView={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.8 }}
            >
              <span className="text-xs uppercase tracking-[0.2em] font-medium text-[#C47245]">Adventure Awaits</span>
              <h2 className="text-4xl md:text-5xl font-semibold text-[#1C1917] mt-4 mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                Thrilling Experiences
              </h2>
              <p className="text-lg text-[#57534E] mb-6">
                From skydiving over scenic landscapes to scuba diving in coral reefs, our AI curates the perfect adventures for every thrill-seeker.
              </p>
              <ul className="space-y-3">
                {['Trekking & Mountaineering', 'Water Sports & Diving', 'Wildlife Safaris', 'Theme Parks & Amusement'].map((item, idx) => (
                  <li key={idx} className="flex items-center gap-3 text-[#1C1917]">
                    <Star size={18} className="text-[#C47245]" />
                    {item}
                  </li>
                ))}
              </ul>
            </motion.div>
            <motion.div
              initial={{ opacity: 0, x: 30 }}
              whileInView={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.8 }}
              className="relative rounded-2xl overflow-hidden aspect-square"
            >
              <img
                src="https://images.unsplash.com/photo-1558883493-8b86ff880fec"
                alt="Adventure activities"
                className="w-full h-full object-cover"
              />
            </motion.div>
          </div>
        </div>
      </section>

      {/* Restaurants */}
      <section className="py-24 px-6 bg-[#F5F2EB]">
        <div className="max-w-7xl mx-auto">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-12 items-center">
            <motion.div
              initial={{ opacity: 0, x: -30 }}
              whileInView={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.8 }}
              className="relative rounded-2xl overflow-hidden aspect-square order-2 md:order-1"
            >
              <img
                src="https://images.pexels.com/photos/30924602/pexels-photo-30924602.jpeg"
                alt="Restaurants"
                className="w-full h-full object-cover"
              />
            </motion.div>
            <motion.div
              initial={{ opacity: 0, x: 30 }}
              whileInView={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.8 }}
              className="order-1 md:order-2"
            >
              <span className="text-xs uppercase tracking-[0.2em] font-medium text-[#C47245]">Culinary Journey</span>
              <h2 className="text-4xl md:text-5xl font-semibold text-[#1C1917] mt-4 mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                Local Flavors
              </h2>
              <p className="text-lg text-[#57534E] mb-6">
                Taste your way through every destination with our handpicked restaurant recommendations, from street food gems to Michelin-starred experiences.
              </p>
              <ul className="space-y-3">
                {['Authentic Local Cuisine', 'Fine Dining Experiences', 'Dietary Preferences Honored', 'Reservation Assistance'].map((item, idx) => (
                  <li key={idx} className="flex items-center gap-3 text-[#1C1917]">
                    <Utensils size={18} className="text-[#C47245]" />
                    {item}
                  </li>
                ))}
              </ul>
            </motion.div>
          </div>
        </div>
      </section>

      {/* Customer Reviews */}
      <section className="py-24 px-6">
        <div className="max-w-7xl mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-4xl md:text-5xl font-semibold text-[#1C1917] mb-4" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
              What Travelers Say
            </h2>
            <p className="text-lg text-[#57534E]">Real stories from real vacations</p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {reviews.map((review, idx) => (
              <motion.div
                key={idx}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                transition={{ delay: idx * 0.15 }}
                className="bg-white p-8 rounded-2xl border border-[#E7E5E4]"
              >
                <div className="flex gap-1 mb-4">
                  {[...Array(review.rating)].map((_, i) => (
                    <Star key={i} size={18} className="fill-[#C47245] text-[#C47245]" />
                  ))}
                </div>
                <p className="text-[#1C1917] mb-4 italic" style={{ fontFamily: 'Cormorant Garamond, serif', fontSize: '1.15rem' }}>
                  "{review.text}"
                </p>
                <p className="text-[#C47245] font-medium text-sm uppercase tracking-wider">{review.name}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section id="about" className="py-24 px-6 bg-[#2A4B5C] text-white">
        <div className="max-w-4xl mx-auto text-center">
          <Globe size={64} className="mx-auto mb-8 opacity-80" />
          <h2 className="text-4xl md:text-5xl font-semibold mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
            Ready for Your Next Adventure?
          </h2>
          <p className="text-xl text-white/80 mb-8">
            Let our AI plan the perfect vacation tailored just for you
          </p>
          <button
            onClick={() => navigate('/login')}
            className="bg-[#C47245] text-white px-8 py-4 rounded-full text-lg font-medium inline-flex items-center gap-2 hover:bg-[#A85D38] transition-all hover:shadow-2xl"
          >
            Get Started
            <ChevronRight size={20} />
          </button>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-12 px-6 border-t border-[#E7E5E4]">
        <div className="max-w-7xl mx-auto text-center">
          <EYVLogo size="small" />
          <p className="mt-4 text-[#57534E]">© 2026 EYV. Enjoy Your Vacation - We Plan Everything.</p>
        </div>
      </footer>
    </div>
  );
};

export default HomePage;
