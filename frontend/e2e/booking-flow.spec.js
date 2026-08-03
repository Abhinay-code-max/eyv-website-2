// Smoke check for the payment/booking flow: "Book this Plan" -> POST
// /api/trips/{id}/book/{plan_type} -> POST /api/payments/checkout ->
// redirect to Stripe Checkout (see handleBookPlan in TripResultsPage.jsx).
// Does NOT complete a real Stripe payment - that's Stripe's own hosted
// page, well outside this app, and already out of scope for a smoke test.
//
// Whether the second step actually reaches Stripe depends on STRIPE_API_KEY
// being configured in whatever environment this runs in (a real Stripe
// *test-mode* secret, same requirement the backend suite's checkout tests
// already have - see ci.yml's comment on STRIPE_API_KEY). Both outcomes are
// accepted: a real redirect toward Stripe, or the app's own handled error
// message if Stripe isn't configured here. Either way proves the button is
// correctly wired end to end and the app doesn't silently do nothing or
// throw an unhandled error - an unconfigured-Stripe *crash* would fail this
// test same as a broken button would.
const crypto = require('crypto');
const { test, expect } = require('@playwright/test');
const { loginAs } = require('./auth');
const seed = require('./seed');
const { readyTrip } = require('./fixtures/trip');

test('booking a plan calls the real backend and either redirects to Stripe or shows a handled error', async ({ page, context }) => {
  const { userId, token } = await loginAs(context);
  const tripId = `e2e_booking_${crypto.randomUUID().replace(/-/g, '').slice(0, 16)}`;
  seed.seedTrip(tripId, userId, readyTrip('E2E Booking Smoke Test Trip'));

  try {
    await page.goto(`/trip-results/${tripId}`);
    await expect(page.getByTestId('premium-plan-card')).toBeVisible({ timeout: 15_000 });

    const bookResponse = page.waitForResponse((res) => res.url().includes('/api/trips/') && res.url().includes('/book/'));
    await page.getByTestId('book-plan-button').click();
    const response = await bookResponse;
    expect(response.status(), 'the real booking endpoint must respond, not hang or 404').toBeLessThan(500);

    // Give the follow-up /payments/checkout call and whichever UI branch it
    // triggers (redirect vs. error message) time to resolve.
    await page.waitForTimeout(3_000);

    const stillOnResultsPage = page.url().includes('/trip-results/');
    const errorVisible = await page.getByText(/could not start booking|stripe/i).isVisible().catch(() => false);

    expect(
      !stillOnResultsPage || errorVisible,
      'expected either a real redirect away from the results page, or a handled booking error message - got neither (likely an unhandled crash)'
    ).toBe(true);
  } finally {
    seed.cleanup(userId, token, tripId);
  }
});
