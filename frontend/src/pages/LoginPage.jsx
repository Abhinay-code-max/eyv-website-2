import React from 'react';
import { motion } from 'framer-motion';
import { LogIn, Globe, Plane, MapPin, Calendar, Users } from 'lucide-react';
import EYVLogo from '../components/EYVLogo';
import { AUTH } from '../constants/testIds';

const LoginPage = () => {
  const handleGoogleLogin = () => {
    // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    const redirectUrl = window.location.origin + '/dashboard';
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  };

  return (
    <div data-testid={AUTH.loginPage} className="min-h-screen bg-gradient-to-br from-[#FDFBF7] via-[#F5F2EB] to-[#FDFBF7] relative overflow-hidden">
      {/* Background decorative elements */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <motion.div
          className="absolute top-20 left-10 opacity-10"
          animate={{ y: [0, -20, 0] }}
          transition={{ duration: 6, repeat: Infinity }}
        >
          <Globe size={120} className="text-[#2A4B5C]" />
        </motion.div>
        <motion.div
          className="absolute bottom-20 right-10 opacity-10"
          animate={{ y: [0, 20, 0] }}
          transition={{ duration: 5, repeat: Infinity }}
        >
          <Plane size={100} className="text-[#C47245]" />
        </motion.div>
      </div>

      <div className="relative z-10 min-h-screen flex items-center justify-center px-4">
        <motion.div
          className="max-w-md w-full"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8 }}
        >
          {/* Logo */}
          <div className="flex justify-center mb-8">
            <EYVLogo size="large" animated={false} />
          </div>

          {/* Main card */}
          <div className="bg-white/70 backdrop-blur-xl rounded-2xl p-8 border border-[#E7E5E4] shadow-xl">
            <h2 className="text-4xl font-semibold text-[#1C1917] mb-2 text-center" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
              Welcome Back
            </h2>
            <p className="text-[#57534E] text-center mb-8">
              Start planning your dream vacation
            </p>

            <button
              data-testid={AUTH.googleLoginButton}
              onClick={handleGoogleLogin}
              className="w-full bg-white border-2 border-[#C47245] text-[#1C1917] py-4 px-6 rounded-xl font-medium text-lg flex items-center justify-center gap-3 transition-all hover:bg-[#C47245] hover:text-white hover:border-[#C47245] hover:shadow-lg"
            >
              <LogIn size={24} />
              Sign in with Google
            </button>

            <div className="mt-8 pt-8 border-t border-[#E7E5E4]">
              <div className="grid grid-cols-3 gap-4 text-center">
                <div>
                  <MapPin size={24} className="mx-auto text-[#C47245] mb-2" />
                  <p className="text-xs text-[#57534E]">Global Destinations</p>
                </div>
                <div>
                  <Calendar size={24} className="mx-auto text-[#C47245] mb-2" />
                  <p className="text-xs text-[#57534E]">Easy Planning</p>
                </div>
                <div>
                  <Users size={24} className="mx-auto text-[#C47245] mb-2" />
                  <p className="text-xs text-[#57534E]">AI Assistance</p>
                </div>
              </div>
            </div>
          </div>

          <p className="text-center mt-6 text-sm text-[#57534E]">
            Enjoy Your Vacation – We Plan Everything.
          </p>
        </motion.div>
      </div>
    </div>
  );
};

export default LoginPage;
