import {
  haversineDistanceKm,
  getDefaultTransportation,
  getDefaultTripType,
  getDefaultTravelPace,
  getDefaultAccommodation,
  getDefaultInterestFromDestinationType,
} from './tripDefaults';

describe('haversineDistanceKm', () => {
  test('same point => 0', () => {
    const p = { lat: 19.0760, lng: 72.8777 };
    expect(haversineDistanceKm(p, p)).toBeCloseTo(0, 3);
  });

  test('Mumbai to Pune is roughly 120-150km', () => {
    const mumbai = { lat: 19.0760, lng: 72.8777 };
    const pune = { lat: 18.5204, lng: 73.8567 };
    const d = haversineDistanceKm(mumbai, pune);
    expect(d).toBeGreaterThan(100);
    expect(d).toBeLessThan(160);
  });

  test('missing point => null', () => {
    expect(haversineDistanceKm(null, { lat: 1, lng: 1 })).toBeNull();
    expect(haversineDistanceKm({ lat: 1, lng: 1 }, null)).toBeNull();
  });
});

describe('getDefaultTransportation', () => {
  test('no signal on either side => Flight', () => {
    expect(getDefaultTransportation(null, null)).toBe('Flight');
  });

  test('only one side resolved => Flight', () => {
    const meta = { country: 'India', type: 'city', lat: 19.0760, lng: 72.8777 };
    expect(getDefaultTransportation(meta, null)).toBe('Flight');
    expect(getDefaultTransportation(null, meta)).toBe('Flight');
  });

  test('different countries => Flight', () => {
    const destination = { country: 'France', type: 'city', lat: 48.8566, lng: 2.3522 };
    const start = { country: 'India', type: 'city', lat: 19.0760, lng: 72.8777 };
    expect(getDefaultTransportation(destination, start)).toBe('Flight');
  });

  test('same country, nearby (<=300km) => Road', () => {
    const mumbai = { country: 'India', type: 'city', lat: 19.0760, lng: 72.8777 };
    const pune = { country: 'India', type: 'city', lat: 18.5204, lng: 73.8567 };
    expect(getDefaultTransportation(pune, mumbai)).toBe('Road');
  });

  test('same country, far (>300km) => Flight', () => {
    const mumbai = { country: 'India', type: 'city', lat: 19.0760, lng: 72.8777 };
    const delhi = { country: 'India', type: 'city', lat: 28.6139, lng: 77.2090 };
    expect(getDefaultTransportation(delhi, mumbai)).toBe('Flight');
  });
});

describe('getDefaultTripType', () => {
  test('1 adult => Solo', () => {
    expect(getDefaultTripType(1, 0, 0)).toBe('Solo');
  });

  test('2 adults => Couple', () => {
    expect(getDefaultTripType(2, 0, 0)).toBe('Couple');
  });

  test('1 adult + 1 child => Family, not Couple', () => {
    expect(getDefaultTripType(1, 1, 0)).toBe('Family');
  });

  test('3 adults, no children/seniors => Group', () => {
    expect(getDefaultTripType(3, 0, 0)).toBe('Group');
  });

  test('4 adults, no children/seniors => Family', () => {
    expect(getDefaultTripType(4, 0, 0)).toBe('Family');
  });

  test('5+ adults, no children/seniors => Group', () => {
    expect(getDefaultTripType(6, 0, 0)).toBe('Group');
  });

  test('any seniors present => Family regardless of count', () => {
    expect(getDefaultTripType(3, 0, 2)).toBe('Family');
  });
});

describe('getDefaultTravelPace', () => {
  test('missing dates => Moderate', () => {
    expect(getDefaultTravelPace('', '')).toBe('Moderate');
    expect(getDefaultTravelPace('2026-08-10', '')).toBe('Moderate');
  });

  test('invalid range (return before departure) => Moderate', () => {
    expect(getDefaultTravelPace('2026-08-10', '2026-08-05')).toBe('Moderate');
  });

  test('<=3 days => Fast-paced', () => {
    expect(getDefaultTravelPace('2026-08-10', '2026-08-12')).toBe('Fast-paced');
  });

  test('4-7 days => Moderate', () => {
    expect(getDefaultTravelPace('2026-08-10', '2026-08-15')).toBe('Moderate');
  });

  test('8+ days => Relaxed', () => {
    expect(getDefaultTravelPace('2026-08-10', '2026-08-20')).toBe('Relaxed');
  });
});

describe('getDefaultAccommodation', () => {
  test('Budget => Hostel', () => {
    expect(getDefaultAccommodation('Budget')).toEqual(['Hostel']);
  });

  test('Premium => Hotel', () => {
    expect(getDefaultAccommodation('Premium')).toEqual(['Hotel']);
  });

  test('Luxury => Resort', () => {
    expect(getDefaultAccommodation('Luxury')).toEqual(['Resort']);
  });
});

describe('getDefaultInterestFromDestinationType', () => {
  test('beach and island both nudge Beaches', () => {
    expect(getDefaultInterestFromDestinationType('beach')).toBe('Beaches');
    expect(getDefaultInterestFromDestinationType('island')).toBe('Beaches');
  });

  test('hill-station nudges Nature', () => {
    expect(getDefaultInterestFromDestinationType('hill-station')).toBe('Nature');
  });

  test('spiritual nudges Religious Tourism', () => {
    expect(getDefaultInterestFromDestinationType('spiritual')).toBe('Religious Tourism');
  });

  test('landmark nudges Historical Sites', () => {
    expect(getDefaultInterestFromDestinationType('landmark')).toBe('Historical Sites');
  });

  test('city/state/country/unknown => no nudge', () => {
    expect(getDefaultInterestFromDestinationType('city')).toBeNull();
    expect(getDefaultInterestFromDestinationType('state')).toBeNull();
    expect(getDefaultInterestFromDestinationType('country')).toBeNull();
    expect(getDefaultInterestFromDestinationType(undefined)).toBeNull();
  });
});
