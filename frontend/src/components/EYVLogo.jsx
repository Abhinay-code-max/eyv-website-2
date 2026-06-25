import React from 'react';
import { Globe, Plane } from 'lucide-react';
import { motion } from 'framer-motion';

const EYVLogo = ({ size = 'normal', animated = false }) => {
  const sizes = {
    small: { globe: 20, plane: 16, container: 'w-32' },
    normal: { globe: 32, plane: 24, container: 'w-48' },
    large: { globe: 48, plane: 36, container: 'w-64' },
  };

  const { globe, plane, container } = sizes[size];

  if (animated) {
    return (
      <motion.div
        className={`flex items-center gap-3 ${container}`}
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 1.2, ease: 'easeOut' }}
      >
        <motion.div
          className="relative"
          animate={{ rotate: 360 }}
          transition={{ duration: 20, repeat: Infinity, ease: 'linear' }}
        >
          <Globe size={globe} className="text-[#2A4B5C]" strokeWidth={1.5} />
          <motion.div
            className="absolute inset-0"
            initial={{ opacity: 0, x: -20, y: -20 }}
            animate={{ opacity: [0, 1, 1, 0], x: 30, y: 30 }}
            transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
          >
            <Plane size={plane} className="text-[#C47245]" strokeWidth={2} />
          </motion.div>
        </motion.div>
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.6, duration: 0.8 }}
        >
          <h1 className="text-4xl font-semibold text-[#1C1917] tracking-tight" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
            EYV
          </h1>
        </motion.div>
      </motion.div>
    );
  }

  return (
    <div className={`flex items-center gap-2 ${container}`}>
      <div className="relative">
        <Globe size={globe} className="text-[#2A4B5C]" strokeWidth={1.5} />
        <Plane size={plane} className="absolute -top-1 -right-1 text-[#C47245]" strokeWidth={2} />
      </div>
      <h1 className="text-3xl font-semibold text-[#1C1917] tracking-tight" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
        EYV
      </h1>
    </div>
  );
};

export default EYVLogo;
