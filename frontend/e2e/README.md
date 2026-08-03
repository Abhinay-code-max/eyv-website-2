# Playwright smoke tests

Shallow smoke coverage only - catching "the app is completely broken"
before it ships, not exhaustive UI testing. Five specs:

- `home-and-login.spec.js` - home page renders; Google sign-in button
  actually kicks off a navigation.
- `dashboard-auth.spec.js` - the auth-bypass mechanism itself (see below)
  works end to end, and an unauthenticated request is correctly bounced.
- `trip-generation.spec.js` - submitting the planner wizard reaches a real
  trip-results page without a fatal error. Does not wait for real Gemini
  generation to finish.
- `view-trip.spec.js` - a `status: "ready"` trip (seeded directly, not
  generated) renders its tier cards and lets you switch between them.
- `booking-flow.spec.js` - "Book this Plan" calls the real backend and
  either redirects toward Stripe or shows a handled error - never a
  silent no-op or an unhandled crash.

## Auth bypass

Real Google OAuth can't run here (no test Google account, and Google
actively blocks automated logins). `auth.js`'s `loginAs()` instead seeds a
real session document straight into Mongo - via `seed.js`, which shells out
to `backend/tests/e2e_seed.py` (the same `conftest.seed_session` helper the
Python backend suite already uses) - and sets the resulting token as the
same `session_token` cookie the real frontend reads. No new backend HTTP
endpoint was added for this on purpose: a "seed a session" route would be a
real backdoor if it ever shipped by accident.

This only works run against the literal hostname `localhost` (not
`127.0.0.1`) - Chromium treats `localhost` as a secure context, so the
real cookie's `Secure` attribute (see `server.py`'s `response.set_cookie`
for `/auth/session`) still gets sent even without TLS.

## Running locally

Needs Mongo reachable at `MONGO_URL` (defaults to
`mongodb://localhost:27017`) and the backend's Python dependencies
installed (`backend/venv` if present, otherwise `python`/`python3` on
`PATH` - see `seed.js`). Playwright's `webServer` config starts the
frontend (`yarn start`) and backend (`uvicorn`) for you and reuses
whatever's already running locally instead of relaunching:

```
cd frontend
npx playwright test
```

`npx playwright show-report` after a run opens the HTML report (traces/
screenshots on failure only).
