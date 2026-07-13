export const API_URL = process.env.REACT_APP_BACKEND_URL + '/api';

// sessionStorage key used to carry the intended post-login destination
// (pathname + state) across the Google OAuth hard-redirect, which drops
// React Router state since the SPA fully unloads during that trip.
export const POST_LOGIN_REDIRECT_KEY = 'eyv_post_login_redirect';

export const BUDGET_LEVELS = [
  { value: 'Budget', label: 'Budget', description: 'Most economical options' },
  { value: 'Premium', label: 'Premium', description: 'Best value for comfort' },
  { value: 'Luxury', label: 'Luxury', description: 'Premium experience' },
];

export const TRANSPORTATION_OPTIONS = [
  { value: 'Flight', label: 'Flight', icon: '✈️' },
  { value: 'Train', label: 'Train', icon: '🚆' },
  { value: 'Road', label: 'Road', icon: '🚗' },
  { value: 'Cruise', label: 'Cruise', icon: '🚢' },
];

export const ACCOMMODATION_OPTIONS = [
  'Hotel',
  'Resort',
  'Villa',
  'Hostel',
  'Homestay',
];

export const INTERESTS = [
  'Adventure',
  'Nature',
  'Wildlife',
  'Beaches',
  'Trekking',
  'Shopping',
  'Food',
  'Nightlife',
  'Cultural Tourism',
  'Historical Sites',
  'Religious Tourism',
];

export const TRIP_TYPES = [
  { value: 'Family', label: 'Family Trip' },
  { value: 'Couple', label: 'Couple Trip' },
  { value: 'Solo', label: 'Solo Trip' },
  { value: 'Group', label: 'Group Trip' },
];
