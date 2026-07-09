import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence, useReducedMotion } from 'framer-motion';
import { Globe, Plane } from 'lucide-react';

/*
 * TripLoadingScreen — cinematic AI loading experience shown while
 * the backend generates trip plans. Cycles through stages, shows
 * a travel fact, and animates a globe + orbiting plane.
 *
 * Props:
 *  - destination: string  (shown in the header)
 *  - onSkip: () => void   (optional — reveals results early)
 */

const STAGES = [
  { icon: '✈️', label: 'Finding flights',        sub: 'Scanning hundreds of routes...' },
  { icon: '🏨', label: 'Searching hotels',        sub: 'Comparing stays for every budget...' },
  { icon: '📍', label: 'Discovering attractions', sub: 'Pinpointing must-see spots...' },
  { icon: '🍽️', label: 'Finding restaurants',     sub: 'From street food to fine dining...' },
  { icon: '🎟️', label: 'Curating experiences',    sub: 'Adventures, culture, relaxation...' },
  { icon: '🧠', label: 'Optimising itinerary',    sub: 'Balancing time, cost & enjoyment...' },
  { icon: '🎉', label: 'Finalising your trip',    sub: 'Almost ready — just a moment...' },
];

const FACTS = [
  'The Maldives is the world\'s lowest-lying country — average 1.5 m above sea level.',
  'Japan has more than 6,800 islands, but most people live on just 4.',
  'Switzerland has four official languages: German, French, Italian and Romansh.',
  'Bali has over 20,000 temples, earning it the name "Island of the Gods".',
  'Dubai\'s Burj Khalifa is so tall you can watch the sunset twice from different floors.',
  'Iceland has no mosquitoes — one of the few places on Earth that\'s true.',
  'The Great Wall of China took over 2,000 years to build across multiple dynasties.',
  'Singapore Changi Airport has a waterfall inside — 40 metres tall.',
];

const STAGE_MS   = 900;   // how long each stage shows
const FACT_MS    = 4000;  // how often the travel fact rotates

export default function TripLoadingScreen({ destination = 'your destination', onSkip }) {
  const reduce = useReducedMotion();
  const [stageIdx, setStageIdx]   = useState(0);
  const [factIdx, setFactIdx]     = useState(() => Math.floor(Math.random() * FACTS.length));
  const [progress, setProgress]   = useState(0);

  /* cycle through stages */
  useEffect(() => {
    const interval = setInterval(() => {
      setStageIdx(prev => {
        const next = prev + 1;
        if (next >= STAGES.length) { clearInterval(interval); return prev; }
        return next;
      });
    }, STAGE_MS);
    return () => clearInterval(interval);
  }, []);

  /* smooth progress bar — fills over all stages */
  useEffect(() => {
    const total = STAGES.length * STAGE_MS;
    const start = performance.now();
    let raf;
    const tick = (now) => {
      const p = Math.min((now - start) / total * 100, 96); // hold at 96% until real data arrives
      setProgress(p);
      if (p < 96) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  /* rotate travel facts */
  useEffect(() => {
    const t = setInterval(() => {
      setFactIdx(prev => (prev + 1) % FACTS.length);
    }, FACT_MS);
    return () => clearInterval(t);
  }, []);

  const stage = STAGES[stageIdx];

  return (
    <motion.div
      className="fixed inset-0 z-50 flex flex-col items-center justify-center overflow-hidden"
      style={{ background: 'radial-gradient(ellipse at center, #FDFBF7 0%, #F0EDE6 60%, #E8E2D8 100%)' }}
      initial={{ opacity: 1 }}
      exit={{ opacity: 0, transition: { duration: 0.5 } }}
    >
      {/* Soft ambient blobs */}
      {!reduce && (
        <>
          <div className="absolute w-[500px] h-[500px] rounded-full pointer-events-none"
            style={{ top: '10%', left: '-10%', background: 'radial-gradient(circle, rgba(196,114,69,0.12) 0%, transparent 65%)' }} />
          <div className="absolute w-[400px] h-[400px] rounded-full pointer-events-none"
            style={{ bottom: '5%', right: '-8%', background: 'radial-gradient(circle, rgba(42,75,92,0.1) 0%, transparent 65%)' }} />
        </>
      )}

      <div className="relative flex flex-col items-center max-w-lg w-full px-8">

        {/* Animated globe + orbiting plane */}
        <div className="relative w-40 h-40 mb-10 flex items-center justify-center">
          {/* Globe */}
          <motion.div
            animate={reduce ? {} : { rotate: 360 }}
            transition={{ duration: 20, repeat: Infinity, ease: 'linear' }}
          >
            <Globe size={100} className="text-[#2A4B5C]" strokeWidth={1} />
          </motion.div>

          {/* Orbiting plane */}
          {!reduce && (
            <motion.div
              className="absolute"
              animate={{ rotate: 360 }}
              transition={{ duration: 4, repeat: Infinity, ease: 'linear' }}
              style={{ width: 140, height: 140, top: 0, left: 0 }}
            >
              <div style={{ position: 'absolute', top: -4, left: '50%', transform: 'translateX(-50%) rotate(90deg)' }}>
                <Plane size={22} className="text-[#C47245]" strokeWidth={2}
                  style={{ filter: 'drop-shadow(0 2px 6px rgba(196,114,69,0.6))' }} />
              </div>
            </motion.div>
          )}

          {/* Orbit ring */}
          {!reduce && (
            <svg className="absolute inset-0 w-full h-full pointer-events-none" viewBox="0 0 140 140" aria-hidden="true">
              <ellipse cx="70" cy="70" rx="68" ry="68"
                stroke="#C47245" strokeWidth="1.5" strokeDasharray="4 8"
                fill="none" opacity="0.3" />
            </svg>
          )}
        </div>

        {/* Destination heading */}
        <motion.p
          className="text-xs uppercase tracking-[0.25em] text-[#C47245] font-medium mb-2"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.2 }}
        >
          Planning your trip to
        </motion.p>
        <motion.h2
          className="text-3xl md:text-4xl font-semibold text-[#1C1917] mb-8 text-center"
          style={{ fontFamily: 'Cormorant Garamond, serif' }}
          initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}
        >
          {destination}
        </motion.h2>

        {/* Stage indicator */}
        <div className="w-full mb-6">
          <AnimatePresence mode="wait">
            <motion.div
              key={stageIdx}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -12 }}
              transition={{ duration: 0.35 }}
              className="flex flex-col items-center gap-1"
            >
              <span className="text-4xl mb-1">{stage.icon}</span>
              <p className="text-lg font-semibold text-[#1C1917]"
                style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                {stage.label}
              </p>
              <p className="text-sm text-[#57534E]">{stage.sub}</p>
            </motion.div>
          </AnimatePresence>
        </div>

        {/* Stage dots */}
        <div className="flex gap-2 mb-6">
          {STAGES.map((_, i) => (
            <motion.div
              key={i}
              className="h-1.5 rounded-full transition-all duration-500"
              style={{
                width: i === stageIdx ? 24 : 8,
                background: i <= stageIdx ? '#C47245' : '#E7E5E4',
              }}
            />
          ))}
        </div>

        {/* Progress bar */}
        <div className="w-full h-1 rounded-full bg-[#E7E5E4] overflow-hidden mb-8">
          <motion.div
            className="h-full rounded-full"
            style={{
              width: `${progress}%`,
              background: 'linear-gradient(90deg, #C47245, #E8B273)',
            }}
            transition={{ duration: 0.3 }}
          />
        </div>

        {/* Travel fact */}
        <div className="w-full rounded-2xl border border-[#E7E5E4] bg-white/60 backdrop-blur-sm px-6 py-4 min-h-[72px] flex items-center">
          <AnimatePresence mode="wait">
            <motion.p
              key={factIdx}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.5 }}
              className="text-sm text-[#57534E] text-center w-full"
            >
              <span className="font-medium text-[#C47245]">Did you know? </span>
              {FACTS[factIdx]}
            </motion.p>
          </AnimatePresence>
        </div>

        {/* Skip */}
        {onSkip && (
          <motion.button
            onClick={onSkip}
            className="mt-6 text-xs uppercase tracking-[0.2em] text-[#57534E] hover:text-[#C47245] transition-colors flex items-center gap-2"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 1.5 }}
          >
            Skip
            <span className="w-6 h-px bg-current" />
          </motion.button>
        )}
      </div>
    </motion.div>
  );
}
