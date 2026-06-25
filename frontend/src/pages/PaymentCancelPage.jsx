import React from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { XCircle } from 'lucide-react';
import { PAYMENT } from '../constants/testIds';
import EYVLogo from '../components/EYVLogo';
import { Button } from '../components/ui/button';

const PaymentCancelPage = () => {
  const navigate = useNavigate();

  return (
    <div data-testid={PAYMENT.cancelPage} className="min-h-screen bg-gradient-to-br from-[#FDFBF7] via-[#F5F2EB] to-[#FDFBF7] flex items-center justify-center px-4">
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="bg-white rounded-3xl p-12 max-w-lg w-full text-center shadow-xl"
      >
        <div className="mb-6 flex justify-center">
          <EYVLogo size="normal" />
        </div>

        <div className="bg-orange-100 rounded-full p-6 w-24 h-24 mx-auto mb-6 flex items-center justify-center">
          <XCircle size={48} className="text-orange-600" />
        </div>

        <h1 className="text-3xl font-semibold text-[#1C1917] mb-4" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
          Payment Cancelled
        </h1>
        <p className="text-[#57534E] mb-6">
          No worries! Your payment was cancelled and you weren't charged. You can try again anytime.
        </p>

        <div className="flex gap-3">
          <Button onClick={() => navigate('/dashboard')} variant="outline" className="flex-1">
            Dashboard
          </Button>
          <Button
            onClick={() => navigate('/premium')}
            className="flex-1 bg-[#C47245] hover:bg-[#A85D38]"
          >
            Try Again
          </Button>
        </div>
      </motion.div>
    </div>
  );
};

export default PaymentCancelPage;
