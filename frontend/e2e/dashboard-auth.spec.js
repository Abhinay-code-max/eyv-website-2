// Proves the auth-bypass mechanism itself works end to end: a session
// seeded directly into Mongo (not a hardcoded token) is accepted by the
// real /api/auth/me check ProtectedRoute makes, and a protected page
// actually renders instead of bouncing to /login. Every other authenticated
// spec in this suite depends on this same mechanism, so it gets its own
// smoke check rather than being assumed to work.
const { test, expect } = require('@playwright/test');
const { loginAs } = require('./auth');
const seed = require('./seed');

test('authenticated session reaches the dashboard, not the login page', async ({ page, context }) => {
  const { userId, token } = await loginAs(context);
  try {
    await page.goto('/dashboard');
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 });
    await expect(page.getByTestId('dashboard-container')).toBeVisible({ timeout: 15_000 });
  } finally {
    seed.cleanup(userId, token);
  }
});

test('no session cookie redirects a protected route to login', async ({ page }) => {
  await page.goto('/dashboard');
  await expect(page).toHaveURL(/\/login/, { timeout: 15_000 });
});
