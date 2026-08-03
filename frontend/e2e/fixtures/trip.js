// Shared seeded-trip fixture for the view-trip and booking specs. A fully
// "ready" trip is seeded directly into Mongo rather than generated live -
// real generation depends on Gemini (slow, quota-limited, and non-
// deterministic content) which is exactly the kind of dependency a shallow
// smoke test should avoid; trip-generation.spec.js covers the generation
// *request* path itself separately.
function dummyPlan(planType, totalCost) {
  return {
    plan_type: planType,
    status: 'ready',
    currency: 'INR',
    currency_symbol: '₹',
    itinerary: {
      day_1: {
        date: '2027-06-01',
        transportation: { mode: 'flight', details: 'Test Air TA101', cost: 6000 },
        accommodation: { name: 'E2E Test Hotel', type: 'hotel', cost: 4000, location: 'Goa' },
        meals: [{ time: 'dinner', restaurant: 'Local restaurant', cuisine: 'Local', cost: 500 }],
        activities: [{ time: '14:00', activity: 'Check-in and explore', location: 'Hotel', cost: 0, category: 'free', pricing_type: 'flat_group' }],
        daily_total: 10500, cumulative_total: 10500, fixed_costs: 10000, variable_costs: 500,
      },
    },
    cost_breakdown: { transportation: 6000, accommodation: 4000, food: 500, activities: 0, miscellaneous: 0 },
    total_cost: totalCost,
    highlights: ['Beautiful beaches', 'Great seafood', 'Relaxing vibe'],
    budget_tips: ['Book early for better rates'],
    anchor_pricing: {
      is_train: false, is_cruise: false, is_road: false, is_one_way: false,
      flight_price: 6000, flight_airline: 'Test Air', flight_number: 'TA101',
      hotel_price_per_night: 4000, hotel_name: 'E2E Test Hotel', hotel_stars: 3,
    },
  };
}

function readyTrip(tripName = 'E2E Smoke Test Trip to Goa') {
  return {
    trip_name: tripName,
    preferences: {
      destination: 'Goa', starting_location: 'Mumbai',
      departure_date: '2027-06-01', return_date: '2027-06-02',
      transportation: 'Flight', currency: 'INR',
      num_travelers: 1, adults: 1, children: 0, seniors: 0,
      budget_level: 'Premium', accommodation: ['Hotel'], interests: ['Beaches'],
      trip_type: 'Solo',
    },
    plans: [
      dummyPlan('Budget', 9500),
      dummyPlan('Premium', 10500),
      dummyPlan('Luxury', 14000),
    ],
  };
}

module.exports = { readyTrip, dummyPlan };
