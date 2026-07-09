import React from 'react';
import { motion, AnimatePresence, useReducedMotion } from 'framer-motion';
import { Globe, Plane } from 'lucide-react';

/*
 * Cinematic EYV intro:
 *  - cream stage with soft drifting particles + pulsing glow
 *  - wireframe globe + flight paths draw themselves in (the Step 1 route motif)
 *  - the EYV mark assembles: globe spins in, plane flies into orbit, letters stagger up
 *  - progress bar fills over `duration`, with a Skip control
 *  - fades smoothly into the homepage (handled by AnimatePresence in App.js)
 *
 * Props:
 *  - onSkip:   called when the user taps Skip (ends the intro early)
 *  - duration: total intro length in ms (kept in sync with the timer in App.js)
 */

const LETTERS = ['E', 'Y', 'V'];

const PARTICLES = Array.from({ length: 14 }, (_, i) => ({
  id: i,
  left: (i * 67) % 100,
  size: 3 + (i % 4),
  delay: (i % 7) * 0.4,
  dur: 5 + (i % 5),
  color: ['#C47245', '#E8B273', '#86A8B3'][i % 3],
}));

const LoadingAnimation = ({ onSkip, duration = 3000 }) => {
  const reduce = useReducedMotion();
  const seconds = duration / 1000;

  return (
    <motion.div
      className="fixed inset-0 z-[60] flex items-center justify-center overflow-hidden"
      style={{ background: 'radial-gradient(ellipse at center, #FDFBF7 0%, #F5F2EB 70%, #EFEAE0 100%)' }}
      initial={{ opacity: 1 }}
      exit={{ opacity: 0, transition: { duration: 0.6, ease: 'easeInOut' } }}
    >
      {/* Soft drifting particles */}
      {!reduce && PARTICLES.map((p) => (
        <motion.span
          key={p.id}
          className="absolute rounded-full"
          style={{
            left: `${p.left}%`,
            bottom: '-5%',
            width: p.size,
            height: p.size,
            background: p.color,
            filter: 'blur(1px)',
            opacity: 0.5,
          }}
          animate={{ y: ['0vh', '-110vh'], opacity: [0, 0.6, 0] }}
          transition={{ duration: p.dur, delay: p.delay, repeat: Infinity, ease: 'easeOut' }}
        />
      ))}

      {/* Pulsing glow behind the mark */}
      {!reduce && (
        <motion.div
          className="absolute w-[420px] h-[420px] rounded-full"
          style={{ background: 'radial-gradient(circle, rgba(196,114,69,0.28) 0%, rgba(196,114,69,0) 65%)' }}
          animate={{ scale: [1, 1.18, 1], opacity: [0.5, 0.85, 0.5] }}
          transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
        />
      )}

      <div className="relative flex flex-col items-center">
        {/* Wireframe globe + flight paths */}
        <motion.svg
          viewBox="0 0 240 240"
          className="absolute -top-10 w-[260px] h-[260px]"
          initial={{ opacity: 0, scale: 0.9, rotate: -8 }}
          animate={{ opacity: 1, scale: 1, rotate: 0 }}
          transition={{ duration: 1.2, ease: 'easeOut' }}
          aria-hidden="true"
        >
          <g stroke="#2A4B5C" strokeWidth="1" fill="none" opacity="0.22">
            <circle cx="120" cy="120" r="90" />
            <ellipse cx="120" cy="120" rx="60" ry="90" />
            <ellipse cx="120" cy="120" rx="30" ry="90" />
            <line x1="120" y1="30" x2="120" y2="210" />
            <line x1="30" y1="120" x2="210" y2="120" />
            <line x1="42" y1="75" x2="198" y2="75" />
            <line x1="42" y1="165" x2="198" y2="165" />
          </g>
          {[
            { d: 'M 50 160 Q 120 50 200 110', delay: 0.8 },
            { d: 'M 60 95 Q 135 175 195 150', delay: 1.1 },
          ].map((arc, i) => (
            <motion.path
              key={i}
              d={arc.d}
              stroke="#C47245"
              strokeWidth="2"
              strokeDasharray="2 7"
              strokeLinecap="round"
              fill="none"
              initial={{ pathLength: 0, opacity: 0 }}
              animate={{ pathLength: 1, opacity: 0.9 }}
              transition={{ duration: reduce ? 0 : 1.3, delay: reduce ? 0 : arc.delay, ease: 'easeInOut' }}
            />
          ))}
        </motion.svg>

        {/* The mark assembles */}
        <div className="relative flex items-center gap-3 mt-24">
          <div className="relative">
            <motion.div
              initial={{ opacity: 0, scale: 0.4, rotate: -90 }}
              animate={{ opacity: 1, scale: 1, rotate: 0 }}
              transition={{ duration: 1, ease: 'easeOut' }}
            >
              <Globe size={56} className="text-[#2A4B5C]" strokeWidth={1.5} />
            </motion.div>
            {/* Plane flies into orbit */}
            <motion.div
              className="absolute -top-2 -right-3"
              initial={{ opacity: 0, x: -40, y: -40, rotate: -25 }}
              animate={{ opacity: 1, x: 0, y: 0, rotate: 0 }}
              transition={{ duration: 1, delay: 0.5, ease: [0.22, 1, 0.36, 1] }}
            >
              <Plane size={26} className="text-[#C47245]" strokeWidth={2} />
            </motion.div>
          </div>

          {/* Letters stagger up */}
          <div className="flex overflow-hidden">
            {LETTERS.map((ch, i) => (
              <motion.span
                key={i}
                className="text-6xl font-semibold text-[#1C1917] tracking-tight"
                style={{ fontFamily: 'Cormorant Garamond, serif' }}
                initial={{ opacity: 0, y: 50 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, delay: 0.7 + i * 0.13, ease: [0.22, 1, 0.36, 1] }}
              >
                {ch}
              </motion.span>
            ))}
          </div>
        </div>

        {/* Tagline */}
        <motion.p
          className="mt-6 text-lg text-[#57534E]"
          style={{ fontFamily: 'Outfit, sans-serif' }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1.3, duration: 0.8 }}
        >
          Enjoy Your Vacation — We Plan Everything.
        </motion.p>

        {/* Progress bar */}
        <div className="mt-10 w-56 h-[3px] rounded-full bg-[#E7E5E4] overflow-hidden">
          <motion.div
            className="h-full rounded-full"
            style={{ background: 'linear-gradient(90deg, #C47245, #E8B273)' }}
            initial={{ width: '0%' }}
            animate={{ width: '100%' }}
            transition={{ duration: seconds, ease: 'linear' }}
          />
        </div>
      </div>

      {/* Skip */}
      {onSkip && (
        <motion.button
          onClick={onSkip}
          className="absolute bottom-8 right-8 text-xs uppercase tracking-[0.2em] text-[#57534E] hover:text-[#C47245] transition-colors flex items-center gap-2"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.8 }}
        >
          Skip
          <span className="w-6 h-px bg-current" />
        </motion.button>
      )}
    </motion.div>
  );
};

export default LoadingAnimation;
