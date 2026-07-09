import React from 'react';
import { motion } from 'framer-motion';
import EYVLogo from './EYVLogo';

const LoadingAnimation = () => {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-gradient-to-br from-[#FDFBF7] via-[#F5F2EB] to-[#FDFBF7]">
      <div className="text-center">
        <EYVLogo size="large" animated={true} />
        <motion.p
          className="mt-8 text-xl text-[#57534E]" style={{ fontFamily: 'Outfit, sans-serif' }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1, duration: 0.8 }}
        >
          Enjoy Your Vacation – We Plan Everything.
        </motion.p>
        <motion.div
          className="mt-6 flex justify-center gap-2"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1.5 }}
        >
          <motion.div
            className="h-3 w-3 rounded-full bg-[#C47245]"
            animate={{ scale: [1, 1.3, 1] }}
            transition={{ duration: 1, repeat: Infinity }}
          />
          <motion.div
            className="h-3 w-3 rounded-full bg-[#E8B273]"
            animate={{ scale: [1, 1.3, 1] }}
            transition={{ duration: 1, repeat: Infinity, delay: 0.2 }}
          />
          <motion.div
            className="h-3 w-3 rounded-full bg-[#86A8B3]"
            animate={{ scale: [1, 1.3, 1] }}
            transition={{ duration: 1, repeat: Infinity, delay: 0.4 }}
          />
        </motion.div>
      </div>
    </div>
  );
};

export default LoadingAnimation;
