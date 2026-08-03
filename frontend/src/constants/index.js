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

// Road-trip question branch (transportation === 'Road')
export const ROAD_ROUTE_STYLE_OPTIONS = ['Fastest', 'Scenic', 'Eco-friendly', 'Adventure route'];
export const ROAD_ROUTE_AVOIDANCE_OPTIONS = ['Avoid highways', 'Avoid tolls'];
export const ROAD_FUEL_TYPE_OPTIONS = ['Petrol', 'Diesel', 'CNG', 'Hybrid', 'Electric'];
export const ROAD_EV_RECHARGE_OPTIONS = [
  'Fast-charging stations preferred',
  'Overnight charging at accommodation',
  'Whichever is convenient',
];
// Deliberately separate from ACCOMMODATION_OPTIONS - overnight waypoint stays
// (motels, camping) are a different question from destination lodging, and
// "Motel" has no equivalent in the main accommodation list.
export const ROAD_OVERNIGHT_ACCOMMODATION_OPTIONS = ['Motel', 'Hotel', 'Homestay', 'Camping/RV Park'];
export const ROAD_FOOD_PREFERENCE_OPTIONS = [
  'Quick bites / fast food',
  'Local & regional cuisine',
  'Sit-down restaurants',
  'Mix of everything',
];
// Route/waypoint-oriented, deliberately distinct from the destination-level
// INTERESTS field above.
export const ROAD_ROUTE_ATTRACTIONS_OPTIONS = [
  'Scenic viewpoints',
  'Local food stops',
  'Historic landmarks',
  'Small towns & villages',
  'Adventure activities',
  'Photo-worthy spots',
];
export const ROAD_AVOID_OPTIONS = [
  'Mountain roads',
  'Ferries',
  'Traffic',
  'Night driving',
  'Bad weather',
  'Dirt roads',
];

// Cruise question branch (transportation === 'Cruise')
export const CRUISE_CABIN_TYPE_OPTIONS = ['Interior', 'Ocean View', 'Balcony', 'Suite'];
export const CRUISE_DURATION_OPTIONS = [
  'Short getaway (2-5 nights)',
  'Week-long (6-9 nights)',
  'Extended voyage (10+ nights)',
];
export const CRUISE_DINING_STYLE_OPTIONS = [
  'Traditional fixed dining',
  'Flexible anytime dining',
  'Specialty dining focus',
];
export const CRUISE_ITINERARY_STYLE_OPTIONS = [
  'Island-hopping',
  'Single destination focus',
  'Relaxation-focused (fewer ports)',
  'No preference',
];
