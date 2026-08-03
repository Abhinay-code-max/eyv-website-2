// Pure functions behind the trip planner's smart defaults - kept separate
// from TripPlannerPage so the decision logic (thresholds, mappings) is
// unit-testable without mounting the form. Every function here is advisory:
// callers only apply the result when the user hasn't manually touched that
// field, and the user can always override afterward.

const NEARBY_ROAD_TRIP_DISTANCE_KM = 300;

// Straight-line (haversine) distance in km between two {lat, lng} points.
export function haversineDistanceKm(a, b) {
  if (!a || !b) return null;
  const toRad = (deg) => (deg * Math.PI) / 180;
  const R = 6371;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}

// destinationMeta/startingLocationMeta are {country, type, lat, lng} pulled
// from a LocationAutocomplete suggestion the user actually clicked, or null
// if they typed freehand and never picked a suggestion (no signal available).
export function getDefaultTransportation(destinationMeta, startingLocationMeta) {
  if (!destinationMeta || !startingLocationMeta) return 'Flight';

  if (
    destinationMeta.country &&
    startingLocationMeta.country &&
    destinationMeta.country !== startingLocationMeta.country
  ) {
    return 'Flight';
  }

  const distanceKm = haversineDistanceKm(startingLocationMeta, destinationMeta);
  if (distanceKm !== null && distanceKm <= NEARBY_ROAD_TRIP_DISTANCE_KM) {
    return 'Road';
  }
  return 'Flight';
}

// Composition-first: children/seniors in the party make it a Family trip
// regardless of headcount (2 people, one a child, isn't a "Couple"). Only
// falls back to a pure count table for all-adult parties.
export function getDefaultTripType(adults, children, seniors) {
  if (children > 0 || seniors > 0) return 'Family';

  const total = adults + children + seniors;
  if (total <= 1) return 'Solo';
  if (total === 2) return 'Couple';
  if (total === 4) return 'Family';
  return 'Group';
}

export function getDefaultTravelPace(departureDate, returnDate) {
  if (!departureDate || !returnDate) return 'Moderate';
  const start = new Date(departureDate);
  const end = new Date(returnDate);
  const days = Math.round((end - start) / (1000 * 60 * 60 * 24));
  if (!Number.isFinite(days) || days <= 0) return 'Moderate';
  if (days <= 3) return 'Fast-paced';
  if (days <= 7) return 'Moderate';
  return 'Relaxed';
}

export function getDefaultAccommodation(budgetLevel) {
  if (budgetLevel === 'Premium') return ['Hotel'];
  if (budgetLevel === 'Luxury') return ['Resort'];
  return ['Hostel'];
}

const DESTINATION_TYPE_INTEREST_MAP = {
  beach: 'Beaches',
  island: 'Beaches',
  'hill-station': 'Nature',
  spiritual: 'Religious Tourism',
  landmark: 'Historical Sites',
};

// null for types too broad to guess a confident interest from (city/state/country).
export function getDefaultInterestFromDestinationType(destinationType) {
  return DESTINATION_TYPE_INTEREST_MAP[destinationType] || null;
}
