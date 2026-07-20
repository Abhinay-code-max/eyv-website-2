import * as Sentry from "@sentry/react";

// No-op when REACT_APP_SENTRY_DSN is unset, so local dev builds are
// unaffected. Sentry.ErrorBoundary in index.js still catches render errors
// either way - it just won't have anywhere to report them to.
export function initSentry() {
  const dsn = process.env.REACT_APP_SENTRY_DSN;
  if (!dsn) return;

  Sentry.init({
    dsn,
    environment: process.env.REACT_APP_ENVIRONMENT || "development",
    integrations: [Sentry.browserTracingIntegration()],
    // Same "1.0 for now, dial down once there's real traffic" reasoning as
    // the backend's SENTRY_TRACES_SAMPLE_RATE.
    tracesSampleRate: Number(process.env.REACT_APP_SENTRY_TRACES_SAMPLE_RATE || 1.0),
  });
}

export { Sentry };
