// Smoke check for the notification bell (EYV Agent System Phase 4 Step
// 4.4): seed a notification directly into Mongo (same shortcut seed-trip
// already takes - see e2e_seed.py's cmd_seed_notification docstring),
// confirm the unread badge reflects it, confirm opening the list shows it,
// and confirm opening the list clears the badge (the "opening/viewing
// marks them read" behavior GET /api/notifications + PATCH
// /api/notifications/read implement).
const { test, expect } = require('@playwright/test');
const { loginAs } = require('./auth');
const seed = require('./seed');

test('unread badge reflects a seeded notification, and opening the list clears it', async ({ page, context }) => {
  const { userId, token } = await loginAs(context);
  try {
    seed.seedNotification(userId, {
      status: 'implemented',
      title: 'Fixed: Refund button does nothing',
      body: 'The issue you reported has been implemented and is live.',
    });

    await page.goto('/dashboard');
    await expect(page.getByTestId('dashboard-container')).toBeVisible({ timeout: 15_000 });

    await expect(page.getByTestId('notification-unread-badge')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('notification-unread-badge')).toHaveText('1');

    // App.js's opening LoadingAnimation overlay (fixed inset-0, LOADER_MS =
    // 3000) runs on every fresh page load regardless of route and sits on
    // top of the bell's own fixed position, intercepting the click below
    // until it clears - same reason booking-flow.spec.js waits out a fixed
    // 3s window elsewhere in this suite.
    await page.waitForTimeout(3_000);

    await page.getByTestId('notification-bell-button').click();
    await expect(page.getByTestId('notification-list')).toBeVisible();
    await expect(page.getByTestId('notification-item')).toHaveCount(1);
    await expect(page.getByTestId('notification-item')).toContainText('Fixed: Refund button does nothing');

    // Opening the list marks it read - the badge disappears once the
    // mark-read round trip completes (no fixed unread count left to show).
    await expect(page.getByTestId('notification-unread-badge')).not.toBeVisible({ timeout: 10_000 });
  } finally {
    seed.cleanup(userId, token);
  }
});
