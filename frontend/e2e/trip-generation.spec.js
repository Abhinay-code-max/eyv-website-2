// Smoke check for the trip-generation happy path: fill the minimum required
// fields in the planner wizard, submit, and confirm the app navigates to a
// real trip-results page that starts rendering (not a blank screen or a
// fatal error) - not that a real AI-generated itinerary comes back fully
// formed. Real generation depends on Gemini (slow, quota-limited,
// non-deterministic), which is why this deliberately doesn't wait for the
// tiers to finish - view-trip.spec.js separately proves the results page
// itself renders correctly once a plan is actually "ready".
const { test, expect } = require('@playwright/test');
const { loginAs } = require('./auth');
const seed = require('./seed');

test('submitting the trip planner reaches trip-results without a fatal error', async ({ page, context }) => {
  const { userId, token } = await loginAs(context);
  let tripId;

  try {
    await page.goto('/trip-planner');

    await page.getByTestId('destination-input').fill('Goa');
    await page.getByTestId('start-location-input').fill('Mumbai');
    await page.getByTestId('departure-date-input').fill('2027-06-01');
    await page.getByTestId('return-date-input').fill('2027-06-04');

    // Every later step (transportation, accommodation, interests, pace) has
    // a smart or hardcoded default - this deliberately exercises the
    // "accept the defaults" path through the wizard rather than filling in
    // every optional field, matching what a real first-time user who just
    // wants a quick plan would do.
    const nextButton = page.getByRole('button', { name: 'Next' });
    for (let i = 0; i < 3; i++) {
      await nextButton.click();
    }

    await page.getByTestId('submit-planner-button').click();

    await page.waitForURL(/\/trip-results\//, { timeout: 20_000 });
    // Whatever state generation is in this soon after submitting (still
    // "generating", or already failed over to a graceful-degradation
    // placeholder plan - see server.py's generate_single_plan comments on
    // Gemini errors), the page itself must render something real, not a
    // blank crash.
    await expect(page.getByTestId('planner-form')).toBeVisible({ timeout: 15_000 });

    tripId = new URL(page.url()).pathname.split('/trip-results/')[1];
  } finally {
    seed.cleanup(userId, token, tripId);
  }
});
