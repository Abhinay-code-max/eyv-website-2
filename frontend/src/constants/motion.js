/**
 * Shared animation presets for framer-motion, used across all pages
 * to keep entrance, hover, and stagger timing consistent site-wide.
 *
 * Usage:
 *   import { fadeUp, staggerContainer, cardHover } from '../constants/motion';
 *   <motion.div {...fadeUp}>...</motion.div>
 */

// Standard easing curve - a gentle ease-out, used everywhere for consistency.
// This specific cubic-bezier reads as "quick start, soft landing" - feels
// premium without being slow.
export const EASE = [0.22, 1, 0.36, 1];

// Standard entrance: fade in + rise slightly. Use for section headers,
// page titles, and any single block of content appearing on load.
export const fadeUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.5, ease: EASE },
};

// Slightly larger rise, for hero/title content that should feel more
// deliberate (e.g. homepage hero text).
export const fadeUpLarge = {
  initial: { opacity: 0, y: 30 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.6, ease: EASE },
};

// Simple fade, no movement - for content where a slide feels unnecessary
// (e.g. modals, overlays).
export const fadeIn = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  transition: { duration: 0.4, ease: EASE },
};

// Container for staggered children (e.g. a grid of cards). Wrap a list
// in this, and give each child `fadeUp` (or `staggerItem` below) -
// children will animate in sequence rather than all at once.
export const staggerContainer = {
  initial: 'hidden',
  animate: 'visible',
  variants: {
    hidden: {},
    visible: {
      transition: {
        staggerChildren: 0.08,
        delayChildren: 0.1,
      },
    },
  },
};

// Use alongside staggerContainer on each child element.
export const staggerItem = {
  variants: {
    hidden: { opacity: 0, y: 20 },
    visible: { opacity: 1, y: 0, transition: { duration: 0.4, ease: EASE } },
  },
};

// Standard hover lift for clickable cards (plan cards, dashboard tiles, etc.)
export const cardHover = {
  whileHover: { y: -4, transition: { duration: 0.2, ease: EASE } },
  whileTap: { scale: 0.98 },
};

// Standard hover for buttons - subtle scale, not a lift (buttons shouldn't
// "float", cards can).
export const buttonHover = {
  whileHover: { scale: 1.02, transition: { duration: 0.2, ease: EASE } },
  whileTap: { scale: 0.97 },
};

// For icon-only buttons or small interactive elements - slightly more
// pronounced since the target is smaller and benefits from clearer feedback.
export const iconButtonHover = {
  whileHover: { scale: 1.08, transition: { duration: 0.15, ease: EASE } },
  whileTap: { scale: 0.92 },
};

// Page-level transition wrapper - use once per page's outermost motion.div
// so navigating between pages feels consistent.
export const pageTransition = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0 },
  transition: { duration: 0.3, ease: EASE },
};
