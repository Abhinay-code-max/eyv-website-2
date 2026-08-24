// Smoke check for the support chat widget (EYV Agent System Phase 4 Step
// 4.4): open the corner launcher, send a message, confirm the round trip
// completes and something real renders back - not that a live model
// correctly classifies the message. Real classification depends on Gemini
// (see trip-generation.spec.js's own comment on this - "slow, quota-limited,
// non-deterministic"), and CI specifically runs with a placeholder
// GEMINI_API_KEY (see ci.yml's playwright-smoke job), under which
// classify_message's own bounded retries are guaranteed to exhaust and
// POST /api/support/message returns a 500 - SupportWidget.jsx's own catch
// block turns that into a graceful in-panel error bubble + toast.error
// rather than a crash, and that's a legitimate "the app didn't break"
// outcome for a smoke test, same tolerance trip-generation.spec.js already
// applies to AI-dependent behavior.
//
// The ack-toast assertion ("if it was a bug/feature, confirm the ack toast
// appears") is therefore conditional, not a hard requirement - it only
// fires when a real classification actually came back and said bug/feature,
// which happens locally with a real GEMINI_API_KEY but not in CI.
const { test, expect } = require('@playwright/test');
const { loginAs } = require('./auth');
const seed = require('./seed');

test('sending a message through the support widget gets a response', async ({ page, context }) => {
  const { userId, token } = await loginAs(context);
  try {
    await page.goto('/dashboard');
    await expect(page.getByTestId('dashboard-container')).toBeVisible({ timeout: 15_000 });

    await page.getByTestId('support-launcher-button').click();
    await expect(page.getByTestId('support-panel')).toBeVisible();

    await page.getByTestId('support-message-input').fill(
      'The refund button on my booking does nothing when I click it - no confirmation, no error.'
    );
    await page.getByTestId('support-send-button').click();

    // The user's own message bubble renders immediately (no backend
    // round-trip needed for that half).
    await expect(page.getByTestId('support-message-bubble').filter({ hasText: 'refund button' })).toBeVisible();

    // Either a real assistant reply, or the graceful error-fallback bubble
    // SupportWidget.jsx shows on a failed request - both prove the round
    // trip completed without the widget hanging or crashing. Two bubbles
    // total: the user's own message plus this one.
    await expect(page.getByTestId('support-message-bubble')).toHaveCount(2, { timeout: 20_000 });

    // Conditional, not required - see file header. Give the toast a short
    // window to appear (sonner toasts render near-instantly once fired)
    // rather than waiting the full default timeout for something that may
    // legitimately never show up in this environment.
    const ackToast = page.locator('[data-sonner-toast]', { hasText: 'logged as a' });
    if (await ackToast.isVisible({ timeout: 2_000 }).catch(() => false)) {
      await expect(ackToast).toContainText(/logged as a (bug|feature)/i);
    }
  } finally {
    seed.cleanup(userId, token);
  }
});
