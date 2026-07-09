import React, { useRef, useEffect, useState } from 'react';
import {
  motion,
  useScroll,
  useTransform,
  useMotionValueEvent,
  useReducedMotion,
} from 'framer-motion';

/*
 * ScrollPlane — a decorative airplane that flies down a curved path as you scroll.
 *  - follows a parametric curve on the right side of the page (clear of hero text)
 *  - leaves a glowing trail that reveals itself in sync with scroll
 *  - tilts into its turns; clouds drift; landmarks crossfade as you "fly over" them
 *  - a faint tint shifts from daylight -> dusk -> evening across the scroll
 *  - pointer-events-none everywhere, so it never intercepts clicks
 *  - renders nothing when prefers-reduced-motion is set
 *
 * Drop <ScrollPlane /> anywhere inside a page; it positions itself fixed to the viewport.
 */

const SAMPLES = 120;
const PLANE_ROTATION_OFFSET = 45; // tweak if the nose doesn't line up with the path

// Parametric flight curve in 0..100 viewport-percentage space.
const curveAt = (t, amp) => ({
  x: 72 + amp * Math.sin(t * Math.PI * 2.4),
  y: 6 + t * 88,
});

const buildPath = (amp) => {
  let d = '';
  for (let i = 0; i <= SAMPLES; i++) {
    const { x, y } = curveAt(i / SAMPLES, amp);
    d += `${i === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)} `;
  }
  return d.trim();
};

const Cloud = ({ className, style, scale = 1 }) => (
  <svg viewBox="0 0 120 60" className={className} style={style} width={120 * scale} height={60 * scale} aria-hidden="true">
    <g fill="#ffffff">
      <ellipse cx="40" cy="38" rx="30" ry="18" />
      <ellipse cx="68" cy="32" rx="26" ry="20" />
      <ellipse cx="90" cy="40" rx="22" ry="14" />
      <rect x="30" y="38" width="62" height="16" rx="8" />
    </g>
  </svg>
);

// Minimal landmark silhouettes the plane "passes over".
const LANDMARKS = [
  {
    label: 'mountains',
    range: [0.18, 0.3, 0.42, 0.52],
    svg: <path d="M0 80 L30 30 L52 60 L80 18 L110 70 L140 40 L160 80 Z" />,
  },
  {
    label: 'island',
    range: [0.45, 0.56, 0.66, 0.76],
    svg: (
      <g>
        <path d="M20 80 Q80 58 140 80 Z" />
        <path d="M78 62 L80 30 M80 34 q-16 -12 -26 -6 M80 34 q16 -12 26 -6 M80 38 q-18 -2 -28 8 M80 38 q18 -2 28 8" stroke="currentColor" strokeWidth="3" fill="none" strokeLinecap="round" />
      </g>
    ),
  },
  {
    label: 'city',
    range: [0.7, 0.8, 0.92, 1.0],
    svg: <path d="M0 80 V52 H16 V40 H30 V60 H44 V30 H60 V60 H74 V46 H90 V58 H108 V36 H124 V80 Z" />,
  },
];

// One landmark layer; opacity windowed to a scroll range so it crossfades in and out.
const Landmark = ({ progress, range, children }) => {
  const opacity = useTransform(progress, range, [0, 0.16, 0.16, 0]);
  return (
    <motion.svg
      viewBox="0 0 160 80"
      className="absolute inset-0 w-full h-full text-[#2A4B5C] fill-current"
      style={{ opacity }}
    >
      {children}
    </motion.svg>
  );
};

const ScrollPlane = () => {
  const reduce = useReducedMotion();
  const { scrollYProgress } = useScroll();

  const [amp, setAmp] = useState(16);
  const [isMobile, setIsMobile] = useState(false);
  const [pathLen, setPathLen] = useState(0);

  const pathRef = useRef(null);
  const trailRef = useRef(null);
  const planeRef = useRef(null);

  // Responsive amplitude: tighter curve on small screens.
  useEffect(() => {
    const apply = () => {
      const mobile = window.innerWidth < 768;
      setIsMobile(mobile);
      setAmp(mobile ? 8 : 16);
    };
    apply();
    window.addEventListener('resize', apply);
    return () => window.removeEventListener('resize', apply);
  }, []);

  const d = buildPath(amp);

  // Measure the trail length whenever the path changes.
  useEffect(() => {
    if (pathRef.current) setPathLen(pathRef.current.getTotalLength());
  }, [d]);

  // Position the plane + reveal the trail in response to scroll (imperative = no re-render).
  const update = (p) => {
    const plane = planeRef.current;
    if (plane) {
      const a = curveAt(p, amp);
      const b = curveAt(Math.min(1, p + 0.004), amp);
      const angle = (Math.atan2(b.y - a.y, b.x - a.x) * 180) / Math.PI;
      plane.style.left = `${a.x}%`;
      plane.style.top = `${a.y}%`;
      plane.style.transform = `translate(-50%, -50%) rotate(${angle + PLANE_ROTATION_OFFSET}deg)`;
    }
    if (trailRef.current && pathLen) {
      trailRef.current.style.strokeDashoffset = String(pathLen * (1 - p));
    }
  };

  useMotionValueEvent(scrollYProgress, 'change', update);
  // Set initial position once we have a measured length.
  useEffect(() => { update(scrollYProgress.get()); /* eslint-disable-next-line */ }, [pathLen, amp]);

  const tint = useTransform(
    scrollYProgress,
    [0, 0.5, 1],
    ['rgba(255,196,140,0)', 'rgba(120,140,180,0.05)', 'rgba(40,30,60,0.09)']
  );

  if (reduce) return null;

  return (
    <div className="pointer-events-none fixed inset-0 z-30 overflow-hidden" aria-hidden="true">
      {/* Time-of-day tint */}
      <motion.div className="absolute inset-0" style={{ background: tint }} />

      {/* Drifting clouds (hidden on mobile to keep things clean) */}
      {!isMobile && (
        <>
          <motion.div
            className="absolute opacity-50"
            style={{ top: '14%' }}
            initial={{ x: '-20vw' }}
            animate={{ x: '120vw' }}
            transition={{ duration: 60, repeat: Infinity, ease: 'linear' }}
          >
            <Cloud scale={1.1} style={{ filter: 'blur(1px)' }} />
          </motion.div>
          <motion.div
            className="absolute opacity-40"
            style={{ top: '48%' }}
            initial={{ x: '110vw' }}
            animate={{ x: '-30vw' }}
            transition={{ duration: 85, repeat: Infinity, ease: 'linear' }}
          >
            <Cloud scale={0.8} style={{ filter: 'blur(1.5px)' }} />
          </motion.div>
          <motion.div
            className="absolute opacity-30"
            style={{ top: '78%' }}
            initial={{ x: '-25vw' }}
            animate={{ x: '120vw' }}
            transition={{ duration: 100, repeat: Infinity, ease: 'linear', delay: 4 }}
          >
            <Cloud scale={1.4} style={{ filter: 'blur(2px)' }} />
          </motion.div>
        </>
      )}

      {/* Landmark silhouettes that crossfade as the plane flies past */}
      <div className="absolute bottom-6 right-6 w-40 h-24">
        {LANDMARKS.map((lm) => (
          <Landmark key={lm.label} progress={scrollYProgress} range={lm.range}>
            {lm.svg}
          </Landmark>
        ))}
      </div>

      {/* Flight path + glowing trail */}
      <svg
        className="absolute inset-0 w-full h-full"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
      >
        <defs>
          <linearGradient id="planeTrail" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#C47245" stopOpacity="0.1" />
            <stop offset="60%" stopColor="#C47245" />
            <stop offset="100%" stopColor="#E8B273" />
          </linearGradient>
        </defs>
        {/* faint full guide line */}
        <path
          ref={pathRef}
          d={d}
          fill="none"
          stroke="#C47245"
          strokeOpacity="0.08"
          strokeWidth="2"
          vectorEffect="non-scaling-stroke"
        />
        {/* revealed glowing trail */}
        <path
          ref={trailRef}
          d={d}
          fill="none"
          stroke="url(#planeTrail)"
          strokeWidth="2.5"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
          style={{
            strokeDasharray: pathLen,
            strokeDashoffset: pathLen,
            filter: 'drop-shadow(0 0 5px rgba(196,114,69,0.6))',
          }}
        />
      </svg>

      {/* The plane */}
      <div
        ref={planeRef}
        className="absolute"
        style={{ left: '72%', top: '6%', transform: 'translate(-50%, -50%)', willChange: 'transform, left, top' }}
      >
        <svg width="34" height="34" viewBox="0 0 24 24" fill="none"
          stroke="#C47245" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
          style={{ filter: 'drop-shadow(0 2px 6px rgba(196,114,69,0.5))' }}>
          <path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z" />
        </svg>
      </div>
    </div>
  );
};

export default ScrollPlane;
