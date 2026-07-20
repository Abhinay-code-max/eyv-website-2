import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import axios from 'axios';
import { motion } from 'framer-motion';
import { Check, X, Loader, Crown, Award } from 'lucide-react';
import { API_URL } from '../constants';
import { PAYMENT } from '../constants/testIds';
import { formatCurrency } from '../lib/currency';
import EYVLogo from '../components/EYVLogo';
import { Button } from '../components/ui/button';

const MAX_POLLS = 10;

const PaymentSuccessPage = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [status, setStatus] = useState('checking');
  const [details, setDetails] = useState(null);
  const pollCount = useRef(0);

  // useCallback with no deps: doesn't close over anything reactive (pollCount
  // is a ref, MAX_POLLS is a module-level constant), so this reference never
  // changes. Depending on it in the effect below therefore can't cause the
  // effect to re-fire on its own - if it weren't stable, every setStatus/
  // setDetails call inside a poll would re-render, mint a new pollStatus, and
  // (with it in the deps array) kick off a second concurrent polling loop.
  const pollStatus = useCallback(async (sessionId) => {
    if (pollCount.current >= MAX_POLLS) {
      setStatus('timeout');
      return;
    }
    pollCount.current += 1;

    try {
      const response = await axios.get(
        `${API_URL}/payments/status/${sessionId}`,
        { withCredentials: true }
      );

      setDetails(response.data);

      if (response.data.payment_status === 'paid') {
        setStatus('success');
        return;
      } else if (response.data.status === 'expired') {
        setStatus('expired');
        return;
      }

      // Poll again
      setTimeout(() => pollStatus(sessionId), 2000);
    } catch (error) {
      console.error('Status check error:', error);
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const sessionId = params.get('session_id');

    if (!sessionId) {
      setStatus('error');
      return;
    }

    pollStatus(sessionId);
  }, [location, pollStatus]);

  return (
    <div data-testid={PAYMENT.successPage} className="min-h-screen bg-gradient-to-br from-[#FDFBF7] via-[#F5F2EB] to-[#FDFBF7] flex items-center justify-center px-4">
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="bg-white rounded-3xl p-12 max-w-lg w-full text-center shadow-xl"
      >
        <div className="mb-6 flex justify-center">
          <EYVLogo size="normal" />
        </div>

        {status === 'checking' && (
          <>
            <Loader size={64} className="mx-auto mb-6 text-[#C47245] animate-spin" />
            <h1 className="text-3xl font-semibold text-[#1C1917] mb-2" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
              Confirming Payment...
            </h1>
            <p className="text-[#57534E]">Please wait while we verify your payment</p>
          </>
        )}

        {status === 'success' && (
          <>
            <motion.div
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{ delay: 0.2, type: 'spring' }}
              className="bg-green-100 rounded-full p-6 w-24 h-24 mx-auto mb-6 flex items-center justify-center"
            >
              <Check size={48} className="text-green-600" />
            </motion.div>
            <div data-testid={PAYMENT.statusBadge}>
              <h1 className="text-4xl font-semibold text-[#1C1917] mb-4" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                Payment Successful!
              </h1>
              <p className="text-[#57534E] mb-6">
                Your payment of {formatCurrency(details?.amount, details?.currency)} has been processed successfully.
              </p>
            </div>
            
            {details?.metadata?.payment_type === 'subscription' && (
              <div className="bg-gradient-to-r from-[#C47245] to-[#E8B273] text-white rounded-xl p-4 mb-6">
                <Crown size={32} className="mx-auto mb-2" />
                <p className="font-medium">Welcome to EYV Premium!</p>
                <p className="text-sm text-white/90">All premium benefits are now active</p>
              </div>
            )}

            {details?.metadata?.payment_type === 'booking' && (
              <div className="bg-[#C47245]/10 rounded-xl p-4 mb-6">
                <Award size={32} className="mx-auto mb-2 text-[#C47245]" />
                <p className="font-medium text-[#1C1917]">Points Earned!</p>
                <p className="text-sm text-[#57534E]">Check your rewards page</p>
              </div>
            )}

            <div className="flex gap-3">
              <Button onClick={() => navigate('/dashboard')} variant="outline" className="flex-1">
                Dashboard
              </Button>
              <Button
                onClick={() => navigate(details?.metadata?.payment_type === 'subscription' ? '/premium' : '/bookings')}
                className="flex-1 bg-[#C47245] hover:bg-[#A85D38]"
              >
                View Details
              </Button>
            </div>
          </>
        )}

        {(status === 'error' || status === 'expired' || status === 'timeout') && (
          <>
            <div className="bg-red-100 rounded-full p-6 w-24 h-24 mx-auto mb-6 flex items-center justify-center">
              <X size={48} className="text-red-600" />
            </div>
            <h1 className="text-3xl font-semibold text-[#1C1917] mb-4" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
              {status === 'expired' ? 'Session Expired' : status === 'timeout' ? 'Still Processing' : 'Something Went Wrong'}
            </h1>
            <p className="text-[#57534E] mb-6">
              {status === 'expired'
                ? 'Your checkout session has expired. Please try again.'
                : status === 'timeout'
                ? 'Payment is still processing. Please check your account in a few minutes.'
                : 'We could not verify your payment. Please contact support if you were charged.'}
            </p>
            <Button onClick={() => navigate('/dashboard')} className="bg-[#C47245] hover:bg-[#A85D38]">
              Back to Dashboard
            </Button>
          </>
        )}
      </motion.div>
    </div>
  );
};

export default PaymentSuccessPage;
