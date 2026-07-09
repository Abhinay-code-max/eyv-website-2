import React, { useState, useEffect, lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, useLocation, Navigate } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import '@/App.css';
import LoadingAnimation from './components/LoadingAnimation';
import AuthCallback from './pages/AuthCallback';
import ProtectedRoute from './components/ProtectedRoute';

/* ── Lazy-load every page (code splitting per route) ─────────────
   Each page becomes its own JS chunk, downloaded only when needed.
   The auth-critical pages (HomePage, LoginPage) are still small
   and load first; heavy pages (TripResults, Bookings) load on demand.
───────────────────────────────────────────────────────────────── */
const HomePage         = lazy(() => import('./pages/HomePage'));
const LoginPage        = lazy(() => import('./pages/LoginPage'));
const DashboardPage    = lazy(() => import('./pages/DashboardPage'));
const TripPlannerPage  = lazy(() => import('./pages/TripPlannerPage'));
const TripResultsPage  = lazy(() => import('./pages/TripResultsPage'));
const BookingPage      = lazy(() => import('./pages/BookingPage'));
const WalletPage       = lazy(() => import('./pages/WalletPage'));
const RewardsPage      = lazy(() => import('./pages/RewardsPage'));
const PremiumPage      = lazy(() => import('./pages/PremiumPage'));
const PaymentSuccessPage = lazy(() => import('./pages/PaymentSuccessPage'));
const PaymentCancelPage  = lazy(() => import('./pages/PaymentCancelPage'));

/* ── Minimal inline fallback shown during chunk download ─────────
   Keeps the screen from going blank between route transitions.
───────────────────────────────────────────────────────────────── */
const PageFallback = () => (
  <div className="min-h-screen bg-[#FDFBF7] flex items-center justify-center">
    <motion.div
      animate={{ rotate: 360 }}
      transition={{ duration: 0.9, repeat: Infinity, ease: 'linear' }}
      className="h-10 w-10 border-4 border-[#C47245] border-t-transparent rounded-full"
    />
  </div>
);

// Total length of the opening animation in ms.
const LOADER_MS = 3000;

function AppRouter() {
  const location = useLocation();
  const [showLoading, setShowLoading] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => setShowLoading(false), LOADER_MS);
    return () => clearTimeout(timer);
  }, []);

  // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
  if (location.hash?.includes('session_id=')) {
    return <AuthCallback />;
  }

  return (
    <>
      <AnimatePresence>
        {showLoading && (
          <LoadingAnimation
            key="loader"
            duration={LOADER_MS}
            onSkip={() => setShowLoading(false)}
          />
        )}
      </AnimatePresence>

      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/dashboard"
            element={<ProtectedRoute><DashboardPage /></ProtectedRoute>}
          />
          <Route
            path="/trip-planner"
            element={<ProtectedRoute><TripPlannerPage /></ProtectedRoute>}
          />
          <Route
            path="/trip-results/:tripId"
            element={<ProtectedRoute><TripResultsPage /></ProtectedRoute>}
          />
          <Route
            path="/bookings"
            element={<ProtectedRoute><BookingPage /></ProtectedRoute>}
          />
          <Route
            path="/wallet"
            element={<ProtectedRoute><WalletPage /></ProtectedRoute>}
          />
          <Route
            path="/rewards"
            element={<ProtectedRoute><RewardsPage /></ProtectedRoute>}
          />
          <Route
            path="/premium"
            element={<ProtectedRoute><PremiumPage /></ProtectedRoute>}
          />
          <Route
            path="/payment-success"
            element={<ProtectedRoute><PaymentSuccessPage /></ProtectedRoute>}
          />
          <Route path="/payment-cancel" element={<PaymentCancelPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </>
  );
}

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <AppRouter />
      </BrowserRouter>
    </div>
  );
}

export default App;
