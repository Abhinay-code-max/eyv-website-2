// Shallow smoke tests only - "is the app completely broken" before it
// ships, not exhaustive UI coverage. See e2e/README.md for the auth-bypass
// strategy (real Google OAuth can't run in CI).
const fs = require('fs');
const path = require('path');
const { defineConfig, devices } = require('@playwright/test');

const FRONTEND_URL = 'http://localhost:3000';
const BACKEND_URL = 'http://localhost:8001';
const BACKEND_DIR = path.join(__dirname, '..', 'backend');

// Same venv-detection as e2e/seed.js - a bare `python` on PATH can resolve
// to system Python (no project dependencies installed) even when the
// backend's own venv exists right next to it, which silently breaks this
// webServer entry with "No module named uvicorn" the moment nothing else
// already has :8001 held open for reuseExistingServer to fall back on. CI
// has no venv (ci.yml installs straight into the job's Python), hence the
// fallback to a bare `python`.
function pythonBin() {
  const venvPython = process.platform === 'win32'
    ? path.join(BACKEND_DIR, 'venv', 'Scripts', 'python.exe')
    : path.join(BACKEND_DIR, 'venv', 'bin', 'python');
  if (fs.existsSync(venvPython)) return venvPython;
  return process.platform === 'win32' ? 'python' : 'python3';
}

module.exports = defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false, // smoke tests share seeded DB state - keep them serial and cheap to reason about
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: FRONTEND_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  // Starts both halves of the app locally the same way a dev would (`yarn
  // start` + a plain uvicorn run) - CI only needs Mongo up first (see
  // ci.yml's playwright-smoke job), Playwright brings up everything else
  // and tears it down after. reuseExistingServer lets a developer running
  // both already (e.g. via docker-compose) skip the relaunch locally.
  webServer: [
    {
      command: 'yarn start',
      url: FRONTEND_URL,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      cwd: __dirname,
    },
    {
      command: `"${pythonBin()}" -m uvicorn server:app --port 8001`,
      url: `${BACKEND_URL}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      cwd: '../backend',
      env: {
        ...process.env,
        MONGO_URL: process.env.MONGO_URL || 'mongodb://localhost:27017',
        DB_NAME: process.env.DB_NAME || 'test_database',
        CORS_ORIGINS: FRONTEND_URL,
        WALLET_URL_SIGNING_SECRET: process.env.WALLET_URL_SIGNING_SECRET || 'e2e-placeholder-wallet-signing-secret',
        INTERNAL_TICKET_API_TOKEN: process.env.INTERNAL_TICKET_API_TOKEN || 'e2e-placeholder-internal-ticket-api-token',
        INTERNAL_ANALYTICS_API_TOKEN: process.env.INTERNAL_ANALYTICS_API_TOKEN || 'e2e-placeholder-internal-analytics-api-token',
        JARVIS_QUEUE_API_TOKEN: process.env.JARVIS_QUEUE_API_TOKEN || 'e2e-placeholder-jarvis-queue-api-token',
        ADMIN_API_KEY: process.env.ADMIN_API_KEY || 'ci-placeholder-admin-api-key-not-a-real-secret',
        REVENUECAT_WEBHOOK_AUTH_KEY: process.env.REVENUECAT_WEBHOOK_AUTH_KEY || 'ci-placeholder-revenuecat-webhook-auth-key-not-a-real-secret',
      },
    },
  ],
});

