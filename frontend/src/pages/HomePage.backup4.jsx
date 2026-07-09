import React, { useState, useEffect, useRef, useId } from 'react';
import {
  motion,
  AnimatePresence,
  useScroll,
  useTransform,
  useInView,
  useReducedMotion,
} from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import {
  MapPin, Calendar, Users, Search, Plane, Hotel, Utensils, Activity,
  Star, ChevronRight, Globe, Compass, Menu, X, ArrowRight,
} from 'lucide-react';
import EYVLogo from '../components/EYVLogo';
import { HOME } from '../constants/testIds';
import LocationAutocomplete from '../components/LocationAutocomplete';
import ScrollPlane from '../components/ScrollPlane';

/* ------------------------------------------------------------------ */
/*  Small reusable helpers (count-up, route signature, reveal motion)  */
/* ------------------------------------------------------------------ */

const useCountUp = (target, inView, duration = 1600) => {
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (!inView) return;
    let raf;
    const start = performance.now();
    const tick = (now) => {
      const p = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      setValue(target * eased);
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [inView, target, duration]);
  return value;
};

const Stat = ({ value, suffix = '', label }) => {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: '-60px' });
  const n = useCountUp(value, inView);
  const display = Number.isInteger(value)
    ? Math.round(n).toLocaleString()
    : n.toFixed(1);
  return (
    <div ref={ref} className="text-center">
      <div
        className="text-4xl md:text-5xl font-semibold text-[#1C1917] tracking-tight"
        style={{ fontFamily: 'Cormorant Garamond, serif' }}
      >
        {display}{suffix}
      </div>
      <div className="mt-2 text-xs uppercase tracking-[0.18em] text-[#57534E]">{label}</div>
    </div>
  );
};

/* The signature element: a flight route that draws itself in on scroll. */
const RouteDivider = ({ className = '' }) => {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: '-80px' });
  const reduce = useReducedMotion();
  const gradId = useId().replace(/:/g, '');
  return (
    <div ref={ref} className={`max-w-7xl mx-auto px-6 ${className}`}>
      <svg viewBox="0 0 1200 80" className="w-full h-10 overflow-visible" fill="none" aria-hidden="true">
        <defs>
          <linearGradient id={`route-${gradId}`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#C47245" stopOpacity="0.15" />
            <stop offset="50%" stopColor="#C47245" />
            <stop offset="100%" stopColor="#2A4B5C" stopOpacity="0.15" />
          </linearGradient>
        </defs>
        <motion.path
          d="M 40 56 Q 600 -12 1160 40"
          stroke={`url(#route-${gradId})`}
          strokeWidth="2"
          strokeDasharray="2 9"
          strokeLinecap="round"
          initial={{ pathLength: 0, opacity: 0 }}
          animate={inView ? { pathLength: 1, opacity: 1 } : {}}
          transition={{ duration: reduce ? 0 : 1.6, ease: 'easeInOut' }}
        />
        <motion.circle
          cx="40" cy="56" r="5" fill="#C47245"
          initial={{ scale: 0 }} animate={inView ? { scale: 1 } : {}}
          transition={{ delay: reduce ? 0 : 0.1 }}
        />
        <motion.circle
          cx="1160" cy="40" r="5" fill="#2A4B5C"
          initial={{ scale: 0 }} animate={inView ? { scale: 1 } : {}}
          transition={{ delay: reduce ? 0 : 1.4 }}
        />
        <motion.g
          initial={{ opacity: 0, scale: 0.4 }}
          animate={inView ? { opacity: 1, scale: 1 } : {}}
          transition={{ delay: reduce ? 0 : 1.2, type: 'spring', stiffness: 200 }}
        >
          <Plane x="1104" y="20" width="32" height="32" className="text-[#C47245]" style={{ transform: 'rotate(20deg)', transformOrigin: 'center' }} />
        </motion.g>
      </svg>
    </div>
  );
};

const fadeUp = {
  hidden: { opacity: 0, y: 28 },
  show: (i = 0) => ({
    opacity: 1, y: 0,
    transition: { duration: 0.7, delay: i * 0.12, ease: [0.22, 1, 0.36, 1] },
  }),
};

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

const HomePage = () => {
  const navigate = useNavigate();
  const reduce = useReducedMotion();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

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

  // Nav frosts once the user scrolls past the hero fold.
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // Subtle hero parallax on the background image.
  const heroRef = useRef(null);
  const { scrollYProgress } = useScroll({ target: heroRef, offset: ['start start', 'end start'] });
  const heroY = useTransform(scrollYProgress, [0, 1], ['0%', '18%']);
  const heroScale = useTransform(scrollYProgress, [0, 1], [1, 1.12]);

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

  const stats = [
    { value: 50000, suffix: '+', label: 'Trips Planned' },
    { value: 120, suffix: '+', label: 'Countries' },
    { value: 4.9, suffix: '', label: 'Avg. Rating' },
    { value: 98, suffix: '%', label: 'Would Rebook' },
  ];

  const navLinks = [
    { href: '#destinations', label: 'Destinations' },
    { href: '#packages', label: 'Packages' },
    { href: '#about', label: 'About' },
  ];

  // Ambient floating icons in the hero (disabled when reduced motion is requested).
  const floaters = [
    { Icon: Plane, style: { top: '18%', right: '14%' }, dur: 9, delay: 0 },
    { Icon: Compass, style: { top: '62%', right: '8%' }, dur: 11, delay: 1.5 },
    { Icon: Globe, style: { top: '30%', right: '38%' }, dur: 13, delay: 0.8 },
  ];

  return (
    <div data-testid={HOME.heroSection} className="min-h-screen bg-[#FDFBF7] text-[#1C1917]">
      {/* Scroll-driven airplane overlay (decorative, pointer-events-none) */}
      <ScrollPlane />

      {/* Navigation */}
      <motion.nav
        initial={{ y: -80, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.6, ease: 'easeOut' }}
        className={`fixed top-0 inset-x-0 z-50 transition-all duration-500 ${
          scrolled
            ? 'bg-[#FDFBF7]/80 backdrop-blur-xl border-b border-[#E7E5E4] shadow-[0_6px_30px_-12px_rgba(28,25,23,0.25)]'
            : 'bg-transparent border-b border-transparent'
        }`}
      >
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className={scrolled ? '' : 'drop-shadow-[0_2px_8px_rgba(0,0,0,0.35)]'}>
            <EYVLogo size="small" />
          </div>

          <div className="hidden md:flex items-center gap-9">
            {navLinks.map((l) => (
              <a
                key={l.href}
                href={l.href}
                className={`relative text-sm font-medium transition-colors group ${
                  scrolled ? 'text-[#57534E] hover:text-[#C47245]' : 'text-white/90 hover:text-white'
                }`}
              >
                {l.label}
                <span className="absolute left-0 -bottom-1 h-px w-0 bg-[#C47245] transition-all duration-300 group-hover:w-full" />
              </a>
            ))}
          </div>

          <div className="flex items-center gap-3">
            <button
              data-testid={HOME.loginButton}
              onClick={() => navigate('/login')}
              className="hidden md:inline-flex bg-[#C47245] text-white px-6 py-2.5 rounded-full text-sm font-medium transition-all hover:bg-[#A85D38] hover:shadow-lg hover:shadow-[#C47245]/30 active:scale-95"
            >
              Sign In
            </button>
            <button
              aria-label="Open menu"
              onClick={() => setMobileOpen((v) => !v)}
              className={`md:hidden p-2 rounded-full transition-colors ${
                scrolled ? 'text-[#1C1917] hover:bg-[#E7E5E4]' : 'text-white hover:bg-white/10'
              }`}
            >
              {mobileOpen ? <X size={22} /> : <Menu size={22} />}
            </button>
          </div>
        </div>

        {/* Mobile menu */}
        <AnimatePresence>
          {mobileOpen && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.3 }}
              className="md:hidden overflow-hidden bg-[#FDFBF7]/95 backdrop-blur-xl border-t border-[#E7E5E4]"
            >
              <div className="px-6 py-4 flex flex-col gap-1">
                {navLinks.map((l) => (
                  <a
                    key={l.href}
                    href={l.href}
                    onClick={() => setMobileOpen(false)}
                    className="py-3 text-[#57534E] hover:text-[#C47245] border-b border-[#E7E5E4] last:border-0"
                  >
                    {l.label}
                  </a>
                ))}
                <button
                  onClick={() => { setMobileOpen(false); navigate('/login'); }}
                  className="mt-3 bg-[#C47245] text-white py-3 rounded-full font-medium hover:bg-[#A85D38] transition-all"
                >
                  Sign In
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.nav>

      {/* Hero Section */}
      <section ref={heroRef} className="relative min-h-[100vh] flex items-center overflow-hidden">
        <motion.div className="absolute inset-0" style={{ y: heroY, scale: heroScale }}>
          <img
            src="https://images.pexels.com/photos/6875499/pexels-photo-6875499.jpeg"
            alt="Tropical paradise"
            className="w-full h-full object-cover"
          />
          <div className="absolute inset-0 bg-gradient-to-r from-black/70 via-black/40 to-transparent" />
          <div className="absolute inset-0 bg-gradient-to-t from-[#1C1917]/60 via-transparent to-[#1C1917]/20" />
        </motion.div>

        {/* Ambient floating travel icons */}
        {!reduce && floaters.map(({ Icon, style, dur, delay }, i) => (
          <motion.div
            key={i}
            className="absolute hidden md:block text-white/15 z-[5]"
            style={style}
            animate={{ y: [0, -22, 0], rotate: [0, 6, 0] }}
            transition={{ duration: dur, delay, repeat: Infinity, ease: 'easeInOut' }}
          >
            <Icon size={56} strokeWidth={1} />
          </motion.div>
        ))}

        <div className="relative z-10 max-w-7xl mx-auto px-6 w-full pt-28 pb-20">
          <motion.div initial="hidden" animate="show" className="max-w-2xl">
            <motion.span
              variants={fadeUp} custom={0}
              className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.25em] text-white/80 bg-white/10 backdrop-blur-md border border-white/20 rounded-full px-4 py-2 mb-6"
            >
              <Compass size={14} /> AI-Powered Travel Planning
            </motion.span>

            <motion.h1
              variants={fadeUp} custom={1}
              className="text-6xl md:text-7xl font-semibold text-white mb-6 tracking-tight leading-[0.95]"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}
            >
              Enjoy Your Vacation
            </motion.h1>

            <motion.p variants={fadeUp} custom={2} className="text-2xl md:text-3xl text-white/90 mb-4 font-light">
              We Plan Everything.
            </motion.p>
            <motion.p variants={fadeUp} custom={3} className="text-lg text-white/75 mb-10 max-w-xl">
              Complete AI-powered travel planning from flights to activities, all in one place.
            </motion.p>

            {/* Search Box */}
            <motion.div
              variants={fadeUp} custom={4}
              className="bg-white/95 backdrop-blur-2xl rounded-3xl p-7 md:p-8 shadow-[0_30px_80px_-20px_rgba(28,25,23,0.5)] border border-white/60"
            >
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
                  <div className="flex items-center gap-2 border border-[#E7E5E4] rounded-xl px-4 py-3 transition-colors focus-within:border-[#C47245]">
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
                  <div className="flex items-center gap-2 border border-[#E7E5E4] rounded-xl px-4 py-3 transition-colors focus-within:border-[#C47245]">
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
                  <div className="flex items-center gap-2 border border-[#E7E5E4] rounded-xl px-4 py-3 transition-colors focus-within:border-[#C47245]">
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
                className="group w-full bg-[#C47245] text-white py-4 px-6 rounded-xl font-medium text-lg flex items-center justify-center gap-2 transition-all hover:bg-[#A85D38] hover:shadow-xl hover:shadow-[#C47245]/30 active:scale-[0.99]"
              >
                <Search size={20} />
                Plan My Vacation
                <ArrowRight size={20} className="transition-transform group-hover:translate-x-1" />
              </button>
            </motion.div>
          </motion.div>
        </div>

        {/* Scroll cue */}
        {!reduce && (
          <motion.div
            className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10 hidden md:flex flex-col items-center gap-2 text-white/70"
            animate={{ y: [0, 8, 0] }}
            transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
          >
            <span className="text-[10px] uppercase tracking-[0.3em]">Scroll</span>
            <div className="w-5 h-8 rounded-full border border-white/40 flex justify-center pt-1.5">
              <div className="w-1 h-1.5 rounded-full bg-white/70" />
            </div>
          </motion.div>
        )}
      </section>

      {/* Stats band */}
      <section className="py-16 px-6 border-b border-[#E7E5E4]">
        <div className="max-w-7xl mx-auto grid grid-cols-2 md:grid-cols-4 gap-10">
          {stats.map((s, idx) => (
            <Stat key={idx} value={s.value} suffix={s.suffix} label={s.label} />
          ))}
        </div>
      </section>

      <RouteDivider className="pt-16" />

      {/* Popular Destinations */}
      <section id="destinations" className="pt-8 pb-24 px-6">
        <div className="max-w-7xl mx-auto">
          <motion.div
            variants={fadeUp} initial="hidden" whileInView="show" viewport={{ once: true }}
            className="text-center mb-16"
          >
            <span className="text-xs uppercase tracking-[0.25em] font-medium text-[#C47245]">Where Next</span>
            <h2 className="text-4xl md:text-5xl font-semibold text-[#1C1917] mt-3 mb-4" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
              Popular Destinations
            </h2>
            <p className="text-lg text-[#57534E]">Discover the world's most beautiful places</p>
          </motion.div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {destinations.map((dest, idx) => (
              <motion.div
                key={idx}
                variants={fadeUp} custom={idx} initial="hidden" whileInView="show" viewport={{ once: true }}
                whileHover={{ y: -8 }}
                className="group relative overflow-hidden rounded-3xl border border-[#E7E5E4] cursor-pointer shadow-sm hover:shadow-2xl transition-shadow duration-500"
              >
                <div className="aspect-[4/5] overflow-hidden">
                  <img
                    src={dest.image}
                    alt={dest.name}
                    className="w-full h-full object-cover transition-transform duration-700 group-hover:scale-110"
                  />
                </div>
                <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/10 to-transparent" />
                <div className="absolute bottom-0 left-0 right-0 p-6 text-white">
                  <h3 className="text-2xl font-medium mb-1" style={{ fontFamily: 'Cormorant Garamond, serif' }}>{dest.name}</h3>
                  <p className="text-white/80 text-sm">{dest.trips}</p>
                  <span className="mt-3 inline-flex items-center gap-1 text-sm text-[#E9C9A0] opacity-0 -translate-y-1 transition-all duration-300 group-hover:opacity-100 group-hover:translate-y-0">
                    Explore <ChevronRight size={16} />
                  </span>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section id="packages" className="py-24 px-6 bg-[#F5F2EB]">
        <div className="max-w-7xl mx-auto">
          <motion.div
            variants={fadeUp} initial="hidden" whileInView="show" viewport={{ once: true }}
            className="text-center mb-16"
          >
            <span className="text-xs uppercase tracking-[0.25em] font-medium text-[#C47245]">All In One Place</span>
            <h2 className="text-4xl md:text-5xl font-semibold text-[#1C1917] mt-3 mb-4" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
              Everything You Need
            </h2>
            <p className="text-lg text-[#57534E]">One platform for your complete vacation</p>
          </motion.div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8">
            {features.map((feature, idx) => (
              <motion.div
                key={idx}
                variants={fadeUp} custom={idx} initial="hidden" whileInView="show" viewport={{ once: true }}
                whileHover={{ y: -6 }}
                className="group bg-white p-8 rounded-2xl border border-[#E7E5E4] hover:border-[#C47245]/40 hover:shadow-xl transition-all duration-300"
              >
                <div className="w-14 h-14 rounded-2xl bg-[#C47245]/10 flex items-center justify-center mb-5 transition-colors group-hover:bg-[#C47245]">
                  <feature.icon size={26} className="text-[#C47245] transition-colors group-hover:text-white" />
                </div>
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
              viewport={{ once: true }}
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
                  <motion.li
                    key={idx}
                    initial={{ opacity: 0, x: -10 }}
                    whileInView={{ opacity: 1, x: 0 }}
                    viewport={{ once: true }}
                    transition={{ delay: idx * 0.1 }}
                    className="flex items-center gap-3 text-[#1C1917]"
                  >
                    <span className="w-7 h-7 rounded-full bg-[#C47245]/10 flex items-center justify-center shrink-0">
                      <Star size={15} className="text-[#C47245]" />
                    </span>
                    {item}
                  </motion.li>
                ))}
              </ul>
            </motion.div>
            <motion.div
              initial={{ opacity: 0, x: 30 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.8 }}
              className="relative rounded-3xl overflow-hidden aspect-square shadow-xl"
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
              viewport={{ once: true }}
              transition={{ duration: 0.8 }}
              className="relative rounded-3xl overflow-hidden aspect-square order-2 md:order-1 shadow-xl"
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
              viewport={{ once: true }}
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
                  <motion.li
                    key={idx}
                    initial={{ opacity: 0, x: -10 }}
                    whileInView={{ opacity: 1, x: 0 }}
                    viewport={{ once: true }}
                    transition={{ delay: idx * 0.1 }}
                    className="flex items-center gap-3 text-[#1C1917]"
                  >
                    <span className="w-7 h-7 rounded-full bg-[#C47245]/10 flex items-center justify-center shrink-0">
                      <Utensils size={15} className="text-[#C47245]" />
                    </span>
                    {item}
                  </motion.li>
                ))}
              </ul>
            </motion.div>
          </div>
        </div>
      </section>

      <RouteDivider className="py-16" />

      {/* Customer Reviews */}
      <section className="pb-24 px-6">
        <div className="max-w-7xl mx-auto">
          <motion.div
            variants={fadeUp} initial="hidden" whileInView="show" viewport={{ once: true }}
            className="text-center mb-16"
          >
            <span className="text-xs uppercase tracking-[0.25em] font-medium text-[#C47245]">Loved By Travelers</span>
            <h2 className="text-4xl md:text-5xl font-semibold text-[#1C1917] mt-3 mb-4" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
              What Travelers Say
            </h2>
            <p className="text-lg text-[#57534E]">Real stories from real vacations</p>
          </motion.div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {reviews.map((review, idx) => (
              <motion.div
                key={idx}
                variants={fadeUp} custom={idx} initial="hidden" whileInView="show" viewport={{ once: true }}
                whileHover={{ y: -6 }}
                className="bg-white p-8 rounded-3xl border border-[#E7E5E4] hover:shadow-xl transition-shadow duration-300"
              >
                <div className="flex gap-1 mb-4">
                  {[...Array(review.rating)].map((_, i) => (
                    <Star key={i} size={18} className="fill-[#C47245] text-[#C47245]" />
                  ))}
                </div>
                <p className="text-[#1C1917] mb-6 italic" style={{ fontFamily: 'Cormorant Garamond, serif', fontSize: '1.15rem' }}>
                  "{review.text}"
                </p>
                <p className="text-[#C47245] font-medium text-sm uppercase tracking-wider">{review.name}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section id="about" className="relative py-28 px-6 bg-[#2A4B5C] text-white overflow-hidden">
        <div className="absolute inset-0 opacity-30">
          <div className="absolute -top-24 -left-24 w-96 h-96 rounded-full bg-[#C47245] blur-[120px]" />
          <div className="absolute -bottom-24 -right-24 w-96 h-96 rounded-full bg-[#C47245]/60 blur-[120px]" />
        </div>
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.8 }}
          className="relative z-10 max-w-4xl mx-auto text-center"
        >
          <Globe size={64} className="mx-auto mb-8 opacity-80" />
          <h2 className="text-4xl md:text-5xl font-semibold mb-6" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
            Ready for Your Next Adventure?
          </h2>
          <p className="text-xl text-white/80 mb-10">
            Let our AI plan the perfect vacation tailored just for you
          </p>
          <button
            onClick={() => navigate('/login')}
            className="group bg-[#C47245] text-white px-8 py-4 rounded-full text-lg font-medium inline-flex items-center gap-2 hover:bg-[#A85D38] transition-all hover:shadow-2xl hover:shadow-[#C47245]/40 active:scale-95"
          >
            Get Started
            <ChevronRight size={20} className="transition-transform group-hover:translate-x-1" />
          </button>
        </motion.div>
      </section>

      {/* Footer */}
      <footer className="py-16 px-6 bg-[#FDFBF7] border-t border-[#E7E5E4]">
        <div className="max-w-7xl mx-auto">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-10 mb-12">
            <div className="md:col-span-1">
              <EYVLogo size="small" />
              <p className="mt-4 text-sm text-[#57534E] leading-relaxed">
                AI-powered travel planning, from flights to activities — all in one place.
              </p>
            </div>
            <div>
              <h4 className="text-xs uppercase tracking-[0.18em] text-[#1C1917] font-semibold mb-4">Explore</h4>
              <ul className="space-y-3 text-sm text-[#57534E]">
                <li><a href="#destinations" className="hover:text-[#C47245] transition-colors">Destinations</a></li>
                <li><a href="#packages" className="hover:text-[#C47245] transition-colors">Packages</a></li>
                <li><a href="#about" className="hover:text-[#C47245] transition-colors">About</a></li>
              </ul>
            </div>
            <div>
              <h4 className="text-xs uppercase tracking-[0.18em] text-[#1C1917] font-semibold mb-4">Company</h4>
              <ul className="space-y-3 text-sm text-[#57534E]">
                <li><span className="hover:text-[#C47245] transition-colors cursor-pointer">Careers</span></li>
                <li><span className="hover:text-[#C47245] transition-colors cursor-pointer">Press</span></li>
                <li><span className="hover:text-[#C47245] transition-colors cursor-pointer">Contact</span></li>
              </ul>
            </div>
            <div>
              <h4 className="text-xs uppercase tracking-[0.18em] text-[#1C1917] font-semibold mb-4">Get Started</h4>
              <button
                onClick={() => navigate('/login')}
                className="bg-[#C47245] text-white px-6 py-2.5 rounded-full text-sm font-medium hover:bg-[#A85D38] transition-all hover:shadow-lg"
              >
                Plan a Trip
              </button>
            </div>
          </div>
          <div className="pt-8 border-t border-[#E7E5E4] text-center">
            <p className="text-sm text-[#57534E]">© 2026 EYV. Enjoy Your Vacation — We Plan Everything.</p>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default HomePage;
