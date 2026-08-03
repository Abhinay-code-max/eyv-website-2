// Real-session auth bypass for the smoke suite - real Google OAuth can't
// run headless/in CI (no test Google account, and Google actively blocks
// automated logins). Instead: seed a genuine session document into Mongo
// (seed.js, same mechanism the Python backend suite's conftest.seed_session
// already uses) and set the resulting token as the same cookie the real
// frontend reads (see server.py's response.set_cookie for /auth/session -
// name "session_token", HttpOnly, Secure, SameSite=None). Chromium treats
// http://localhost as a secure context, so a Secure cookie still gets sent
// here even without TLS - this only works because everything runs on the
// literal hostname "localhost", not 127.0.0.1.
const crypto = require('crypto');
const seed = require('./seed');

async function loginAs(context, { premium = false } = {}) {
  const userId = `e2e_${crypto.randomUUID().replace(/-/g, '').slice(0, 16)}`;
  const token = `e2e_token_${crypto.randomUUID()}`;
  seed.seedSession(userId, token, { premium });
  await context.addCookies([{
    name: 'session_token',
    value: token,
    domain: 'localhost',
    path: '/',
    httpOnly: true,
    secure: true,
    sameSite: 'None',
  }]);
  return { userId, token };
}

module.exports = { loginAs };
