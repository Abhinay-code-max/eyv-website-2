// Smoke check on the unauthenticated entry point: home page renders, and
// the Google sign-in button actually kicks off a real navigation (to the
// backend's OAuth-kickoff route) rather than silently doing nothing. Does
// NOT attempt a real Google login - see e2e/auth.js for how the other
// specs get an authenticated session instead.
const { test, expect } = require('@playwright/test');

test('home page loads without a blank/broken screen', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('body')).toBeVisible();
  await expect(page.getByTestId('get-started-button').or(page.getByTestId('login-button')).first()).toBeVisible({ timeout: 15_000 });
});

test('Google sign-in button navigates away to start the OAuth flow', async ({ page }) => {
  await page.goto('/login');
  const googleButton = page.getByTestId('google-login-button');
  await expect(googleButton).toBeVisible();

  const frontendOrigin = new URL(page.url()).origin;
  await googleButton.click();
  // window.location.href assignment is a real full-page navigation, not a
  // React Router route change - the SPA's origin must actually be left
  // behind, proving the click is wired to something real (whether that
  // lands on Google's consent screen or the backend's own "OAuth not
  // configured" error in an environment with no real Google credentials -
  // either way it left the SPA's origin, which is what this smoke check
  // cares about). Checking origin rather than pathname - a pathname
  // endsWith('/login') check produces a false negative when the backend's
  // own error response is served at a path that also ends in "/login"
  // (e.g. /api/auth/google/login, the unconfigured-OAuth case CI hits).
  await page.waitForURL((url) => url.origin !== frontendOrigin, { timeout: 10_000 });
});
