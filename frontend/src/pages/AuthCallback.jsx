import React, { useEffect, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import axios from 'axios';
import { API_URL, POST_LOGIN_REDIRECT_KEY, AUTH_INTENT_KEY } from '../constants';
import { toast } from 'sonner';
import LoadingAnimation from '../components/LoadingAnimation';

const AuthCallback = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const hasProcessed = useRef(false);

  useEffect(() => {
    // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    if (hasProcessed.current) return;
    hasProcessed.current = true;

    const processSession = async () => {
      try {
        const hash = location.hash;
        const params = new URLSearchParams(hash.substring(1));
        const sessionId = params.get('session_id');

        if (!sessionId) {
          navigate('/login');
          return;
        }

        const response = await axios.post(
          `${API_URL}/auth/session`,
          { session_id: sessionId },
          { withCredentials: true }
        );

        if (response.data.user) {
          const isNewUser = Boolean(response.data.is_new_user);
          const intent = sessionStorage.getItem(AUTH_INTENT_KEY) || 'login';
          sessionStorage.removeItem(AUTH_INTENT_KEY);

          // Identify user by opaque user_id (no PII) and fire signup_completed event for new accounts
          if (window.posthog && response.data.user.user_id) {
            window.posthog.identify(response.data.user.user_id);
          }
          if (isNewUser && window.posthog) {
            window.posthog.capture('signup_completed');
          }

          // Distinct user messaging based on intent vs account state
          if (intent === 'signup' && !isNewUser) {
            toast.info("You already have an account — redirecting you to your dashboard.", { duration: 4000 });
          } else if (intent === 'login' && isNewUser) {
            toast.success("No existing account found — created your new EYV account! Welcome!", { duration: 4000 });
          } else if (intent === 'signup' && isNewUser) {
            toast.success("Welcome to EYV! Your account has been created.", { duration: 4000 });
          } else {
            toast.success("Welcome back!", { duration: 3000 });
          }

          // Restore the page the user was trying to reach before being sent
          // to log in (e.g. a Popular Destinations card pre-filling the trip
          // planner). Falls back to /dashboard when nothing was stashed.
          let targetPathname = '/dashboard';
          let targetState = {};
          const stashed = sessionStorage.getItem(POST_LOGIN_REDIRECT_KEY);
          if (stashed) {
            sessionStorage.removeItem(POST_LOGIN_REDIRECT_KEY);
            try {
              const parsed = JSON.parse(stashed);
              if (parsed?.pathname) {
                targetPathname = parsed.pathname;
                targetState = parsed.state || {};
              }
            } catch (e) {
              console.error('Failed to parse stashed post-login redirect:', e);
            }
          }
          navigate(targetPathname, { state: { ...targetState, user: response.data.user }, replace: true });
        } else {
          navigate('/login');
        }
      } catch (error) {
        console.error('Auth callback error:', error);
        navigate('/login');
      }
    };

    processSession();
  }, [location, navigate]);

  return <LoadingAnimation />;
};

export default AuthCallback;
