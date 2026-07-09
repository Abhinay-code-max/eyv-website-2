/*
 * constants/motion.js — shared Framer Motion presets
 *
 * Performance rules applied here:
 *  1. Only animate transform (translate/scale/rotate) and opacity —
 *     both are GPU-composited and never trigger layout.
 *  2. Spring transitions feel snappier and don't drop frames compared
 *     to duration-based tweens on low-end devices.
 *  3. willChange is NOT set here — Framer Motion sets it automatically
 *     on the animated element and removes it when the animation ends,
 *     which is more efficient than a blanket CSS class.
 *  4. All presets are plain objects so they can be spread onto motion.*
 *     elements without creating new object references on every render.
 */

/* ── Page entrance (used on every route) ───────────────────────── */
export const fadeUp = {
  initial: { opacity: 0, y: 24 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.55, ease: [0.22, 1, 0.36, 1] },
};

/* ── Staggered list item (spread variants onto motion.div) ──────── */
export const staggerItem = {
  variants: {
    hidden: { opacity: 0, y: 20 },
    show:   { opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] } },
  },
};

/* ── Stagger container (parent of staggerItem children) ─────────── */
export const staggerContainer = {
  variants: {
    hidden: {},
    show: {
      transition: { staggerChildren: 0.08, delayChildren: 0.1 },
    },
  },
  initial: 'hidden',
  animate: 'show',
};

/* ── Button micro-interaction ────────────────────────────────────── */
export const buttonHover = {
  whileHover: { scale: 1.03 },
  whileTap:   { scale: 0.97 },
  transition: { type: 'spring', stiffness: 400, damping: 20 },
};

/* ── Card lift (hover only, no tap needed) ───────────────────────── */
export const cardHover = {
  whileHover: { y: -6, transition: { type: 'spring', stiffness: 300, damping: 20 } },
};

/* ── Slide in from right (page transitions) ──────────────────────── */
export const slideInRight = {
  initial:    { opacity: 0, x: 40 },
  animate:    { opacity: 1, x: 0 },
  exit:       { opacity: 0, x: -40 },
  transition: { duration: 0.35, ease: [0.22, 1, 0.36, 1] },
};

/* ── Modal spring entrance ───────────────────────────────────────── */
export const modalSpring = {
  initial:    { opacity: 0, scale: 0.92, y: 16 },
  animate:    { opacity: 1, scale: 1,    y: 0  },
  exit:       { opacity: 0, scale: 0.92, y: 16 },
  transition: { type: 'spring', stiffness: 300, damping: 25 },
};

/* ── Fade only (for overlays, tooltips) ──────────────────────────── */
export const fadeOnly = {
  initial:    { opacity: 0 },
  animate:    { opacity: 1 },
  exit:       { opacity: 0 },
  transition: { duration: 0.2 },
};
