// Smoke check for "viewing a generated trip" - seeds a fully "ready" trip
// straight into Mongo (see fixtures/trip.js for why: decoupled from real
// Gemini generation latency/flakiness) and confirms the results page
// actually renders it: trip name, destination, all three tier cards, and
// that selecting a different tier updates the shown cost.
const crypto = require('crypto');
const { test, expect } = require('@playwright/test');
const { loginAs } = require('./auth');
const seed = require('./seed');
const { readyTrip } = require('./fixtures/trip');

test('a ready trip renders its plan tiers and lets the user switch between them', async ({ page, context }) => {
  const { userId, token } = await loginAs(context);
  const tripId = `e2e_trip_${crypto.randomUUID().replace(/-/g, '').slice(0, 16)}`;
  const trip = readyTrip();
  seed.seedTrip(tripId, userId, trip);

  try {
    await page.goto(`/trip-results/${tripId}`);

    await expect(page.getByRole('heading', { name: trip.trip_name })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText('Goa').first()).toBeVisible();

    const budgetCard = page.getByTestId('budget-plan-card');
    const premiumCard = page.getByTestId('premium-plan-card');
    const luxuryCard = page.getByTestId('luxury-plan-card');
    await expect(budgetCard).toBeVisible();
    await expect(premiumCard).toBeVisible();
    await expect(luxuryCard).toBeVisible();

    // Premium (10,500) is the default-selected tier server-side ordering
    // aside, the page loads whichever the backend returns first - assert
    // the cost figure changes when a different tier is clicked, proving
    // selection actually drives the displayed plan rather than being
    // decorative.
    await luxuryCard.click();
    await expect(page.getByText('14,000').first()).toBeVisible({ timeout: 10_000 });

    await budgetCard.click();
    await expect(page.getByText('9,500').first()).toBeVisible({ timeout: 10_000 });
  } finally {
    seed.cleanup(userId, token, tripId);
  }
});
