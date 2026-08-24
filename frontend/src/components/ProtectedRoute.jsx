import React, { useState, useEffect } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import axios from 'axios';
import { API_URL } from '../constants';
import LoadingAnimation from '../components/LoadingAnimation';
import SupportWidget from './SupportWidget';
import NotificationBell from './NotificationBell';

const ProtectedRoute = ({ children }) => {
  const location = useLocation();
  const [isAuthenticated, setIsAuthenticated] = useState(
    location.state?.user ? true : null
  );
  const [user, setUser] = useState(location.state?.user || null);

  useEffect(() => {
    if (location.state?.user) return;

    const checkAuth = async () => {
      try {
        const response = await axios.get(`${API_URL}/auth/me`, {
          withCredentials: true,
        });
        setUser(response.data);
        setIsAuthenticated(true);
      } catch (error) {
        setIsAuthenticated(false);
      }
    };

    checkAuth();
  }, [location.state]);

  if (isAuthenticated === null) {
    return <LoadingAnimation />;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // Rendered once here, alongside every protected page, rather than
  // duplicated into each page component - ProtectedRoute already wraps
  // every authenticated route in App.js and already resolves `user`
  // (the notification loop and the support widget's ticket-reporter
  // identity both depend on user_id - see the EYV Agent System roadmap's
  // own "authenticated users only" note), so this is the one place that
  // naturally covers all of them without touching each page file.
  return (
    <>
      {React.cloneElement(children, { user })}
      <SupportWidget />
      <NotificationBell />
    </>
  );
};

export default ProtectedRoute;
