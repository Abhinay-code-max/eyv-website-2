import React, { useState, useEffect } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { LogIn, Globe, Plane, MapPin, Calendar, Users, Sparkles, Star } from 'lucide-react';
import EYVLogo from '../components/EYVLogo';
import { AUTH } from '../constants/testIds';
import { API_URL } from '../constants';

/* ── tiny floating particle ───────────────────────────────────────── */
const PARTICLES = Array.from({ length: 18 }, (_, i) => ({
  id: i,
  left: (i * 53 + 7) % 100,
  size: 2 + (i % 3),
  delay: (i % 9) * 0.4,
  dur: 7 + (i % 6),
  color: ['#C47245', '#E8B273', '#86A8B3', '#2A4B5C'][i % 4],
}));

/* ── animated flight path behind the card ────────────────────────── */
const FlightPath = () => (
  <svg className="absolute inset-0 w-full h-full pointer-events-none" viewBox="0 0 800 600"
    preserveAspectRatio="xMidYMid slice" aria-hidden="true">
    <defs>
      <linearGradient id="lp-trail" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stopColor="#C47245" stopOpacity="0" />
        <stop offset="50%" stopColor="#C47245" stopOpacity="0.25" />
        <stop offset="100%" stopColor="#2A4B5C" stopOpacity="0" />
      </linearGradient>
    </defs>
    <motion.path
      d="M -60 480 Q 200 80 860 120"
      stroke="url(#lp-trail)" strokeWidth="1.5"
      strokeDasharray="4 10" strokeLinecap="round" fill="none"
      initial={{ pathLength: 0, opacity: 0 }}
      animate={{ pathLength: 1, opacity: 1 }}
      transition={{ duration: 2.2, ease: 'easeInOut', delay: 0.4 }}
    />
    <motion.path
      d="M -40 560 Q 400 200 840 300"
      stroke="url(#lp-trail)" strokeWidth="1"
      strokeDasharray="3 12" strokeLinecap="round" fill="none"
      initial={{ pathLength: 0, opacity: 0 }}
      animate={{ pathLength: 1, opacity: 1 }}
      transition={{ duration: 2.6, ease: 'easeInOut', delay: 0.8 }}
    />
  </svg>
);

const LoginPage = () => {
  const reduce = useReducedMotion();
  const [glowPulse, setGlowPulse] = useState(false);

  // subtle glow throb after initial entrance
  useEffect(() => {
    const t = setTimeout(() => setGlowPulse(true), 1200);
    return () => clearTimeout(t);
  }, []);

  const handleGoogleLogin = () => {
    window.location.href = `${API_URL}/auth/google/login`;
  };

  const perks = [
    { Icon: MapPin,   label: 'Global Destinations' },
    { Icon: Calendar, label: 'Easy Planning' },
    { Icon: Users,    label: 'AI Assistance' },
  ];

  const floatRight = [
    { top: '12%', right: '8%',  Icon: Globe,     size: 80,  dur: 9,  delay: 0   },
    { top: '58%', right: '4%',  Icon: Plane,     size: 56,  dur: 11, delay: 1.2 },
    { top: '80%', right: '14%', Icon: Sparkles,  size: 36,  dur: 8,  delay: 0.6 },
  ];

  const floatLeft = [
    { top: '20%', left: '6%',  Icon: Plane,    size: 52,  dur: 10, delay: 0.3 },
    { top: '65%', left: '4%',  Icon: Star,     size: 34,  dur: 7,  delay: 1   },
  ];

  return (
    <div
      data-testid={AUTH.loginPage}
      className="min-h-screen relative overflow-hidden flex items-center justify-center px-4"
      style={{
        background: 'radial-gradient(ellipse at 30% 40%, #EDE9DF 0%, #FDFBF7 45%, #F0EDE6 100%)',
      }}
    >
      {/* Drifting particles */}
      {!reduce && PARTICLES.map((p) => (
        <motion.span key={p.id}
          className="absolute rounded-full pointer-events-none"
          style={{ left: `${p.left}%`, bottom: '-4%', width: p.size, height: p.size,
            background: p.color, opacity: 0.45, filter: 'blur(0.5px)' }}
          animate={{ y: ['0vh', '-105vh'], opacity: [0, 0.55, 0] }}
          transition={{ duration: p.dur, delay: p.delay, repeat: Infinity, ease: 'easeOut' }}
        />
      ))}

      {/* Flight paths */}
      {!reduce && <FlightPath />}

      {/* Ambient glow blob */}
      {!reduce && (
        <motion.div
          className="absolute w-[500px] h-[500px] rounded-full pointer-events-none"
          style={{
            top: '50%', left: '50%',
            transform: 'translate(-50%, -50%)',
            background: 'radial-gradient(circle, rgba(196,114,69,0.14) 0%, transparent 65%)',
          }}
          animate={glowPulse ? { scale: [1, 1.15, 1], opacity: [0.6, 1, 0.6] } : {}}
          transition={{ duration: 4, repeat: Infinity, ease: 'easeInOut' }}
        />
      )}

      {/* Floating icons — right */}
      {!reduce && floatRight.map(({ top, right, Icon, size, dur, delay }, i) => (
        <motion.div key={`r${i}`}
          className="absolute hidden lg:block text-[#2A4B5C]/10 pointer-events-none"
          style={{ top, right }}
          animate={{ y: [0, -18, 0], rotate: [0, 5, 0] }}
          transition={{ duration: dur, delay, repeat: Infinity, ease: 'easeInOut' }}>
          <Icon size={size} strokeWidth={1} />
        </motion.div>
      ))}

      {/* Floating icons — left */}
      {!reduce && floatLeft.map(({ top, left, Icon, size, dur, delay }, i) => (
        <motion.div key={`l${i}`}
          className="absolute hidden lg:block text-[#C47245]/10 pointer-events-none"
          style={{ top, left }}
          animate={{ y: [0, -14, 0], rotate: [0, -5, 0] }}
          transition={{ duration: dur, delay, repeat: Infinity, ease: 'easeInOut' }}>
          <Icon size={size} strokeWidth={1} />
        </motion.div>
      ))}

      {/* Main card */}
      <motion.div
        className="relative z-10 w-full max-w-md"
        initial={{ opacity: 0, y: 32, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
      >
        {/* Logo */}
        <div className="flex justify-center mb-8">
          <motion.div
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.2, duration: 0.7, ease: 'easeOut' }}
          >
            <EYVLogo size="large" animated={false} />
          </motion.div>
        </div>

        {/* Glass card */}
        <motion.div
          className="relative rounded-3xl overflow-hidden"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3, duration: 0.7 }}
        >
          {/* Glass layers */}
          <div className="absolute inset-0 bg-white/60 backdrop-blur-2xl rounded-3xl" />
          <div className="absolute inset-0 rounded-3xl border border-white/80 shadow-[0_32px_80px_-16px_rgba(28,25,23,0.18),inset_0_1px_0_rgba(255,255,255,0.9)]" />

          {/* Inner glow top edge */}
          <div className="absolute top-0 left-1/2 -translate-x-1/2 w-3/4 h-px bg-gradient-to-r from-transparent via-white to-transparent" />

          <div className="relative z-10 p-8 md:p-10">
            {/* Badge */}
            <motion.div
              className="flex justify-center mb-6"
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.45, duration: 0.6 }}
            >
              <span className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-[#C47245] bg-[#C47245]/8 border border-[#C47245]/20 rounded-full px-4 py-1.5">
                <Sparkles size={12} />
                AI-Powered Planning
              </span>
            </motion.div>

            {/* Heading */}
            <motion.div
              className="text-center mb-8"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.5, duration: 0.7 }}
            >
              <h2 className="text-4xl md:text-5xl font-semibold text-[#1C1917] mb-3 leading-tight"
                style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                Welcome Back
              </h2>
              <p className="text-[#57534E] text-base">
                Sign in to start planning your dream vacation
              </p>
            </motion.div>

            {/* Google sign-in button */}
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.6, duration: 0.6 }}
            >
              <button
                data-testid={AUTH.googleLoginButton}
                onClick={handleGoogleLogin}
                className="group w-full relative bg-white border border-[#E7E5E4] text-[#1C1917] py-4 px-6 rounded-2xl font-medium text-base flex items-center justify-center gap-3 transition-all duration-300 hover:border-[#C47245] hover:shadow-[0_8px_30px_-8px_rgba(196,114,69,0.35)] hover:-translate-y-0.5 active:scale-[0.98] active:translate-y-0 overflow-hidden"
              >
                {/* Hover fill */}
                <span className="absolute inset-0 bg-gradient-to-r from-[#C47245] to-[#A85D38] opacity-0 group-hover:opacity-100 transition-opacity duration-300 rounded-2xl" />
                {/* Google G logo */}
                <span className="relative z-10 flex-shrink-0">
                  <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
                    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/>
                    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                  </svg>
                </span>
                <span className="relative z-10 group-hover:text-white transition-colors duration-300">
                  Continue with Google
                </span>
                <LogIn size={18} className="relative z-10 ml-auto text-[#57534E] group-hover:text-white transition-colors duration-300" />
              </button>
            </motion.div>

            {/* Divider */}
            <motion.div
              className="flex items-center gap-4 my-7"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.7 }}
            >
              <div className="flex-1 h-px bg-[#E7E5E4]" />
              <span className="text-xs uppercase tracking-[0.2em] text-[#57534E]">Secure Sign-In</span>
              <div className="flex-1 h-px bg-[#E7E5E4]" />
            </motion.div>

            {/* Perks row */}
            <motion.div
              className="grid grid-cols-3 gap-3"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.75, duration: 0.6 }}
            >
              {perks.map(({ Icon, label }, i) => (
                <motion.div key={i}
                  className="flex flex-col items-center gap-2 py-4 px-2 rounded-2xl bg-[#F5F2EB]/70 border border-[#E7E5E4]/60 hover:border-[#C47245]/40 hover:bg-[#FEF3EC]/60 transition-all duration-300 cursor-default"
                  whileHover={{ y: -3 }}
                >
                  <Icon size={22} className="text-[#C47245]" />
                  <p className="text-[10px] text-center text-[#57534E] leading-tight">{label}</p>
                </motion.div>
              ))}
            </motion.div>
          </div>
        </motion.div>

        {/* Tagline */}
        <motion.p
          className="text-center mt-6 text-sm text-[#57534E]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.9 }}
        >
          Enjoy Your Vacation — We Plan Everything.
        </motion.p>
      </motion.div>
    </div>
  );
};

export default LoginPage;
