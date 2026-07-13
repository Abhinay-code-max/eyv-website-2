import React, { useEffect, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import axios from 'axios';
import { API_URL, POST_LOGIN_REDIRECT_KEY } from '../constants';
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
