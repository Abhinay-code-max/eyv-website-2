// Shells out to backend/tests/e2e_seed.py to write auth/trip state directly
// into Mongo before a test runs. See that script's docstring for why: real
// Google OAuth can't run here, and adding a Mongo client + duplicate
// session-seeding logic on the JS side would just be a second, divergent
// copy of what conftest.py's Python suite already does correctly.
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const BACKEND_DIR = path.join(__dirname, '..', '..', 'backend');
const SEED_SCRIPT = path.join(BACKEND_DIR, 'tests', 'e2e_seed.py');

function pythonBin() {
  const venvPython = process.platform === 'win32'
    ? path.join(BACKEND_DIR, 'venv', 'Scripts', 'python.exe')
    : path.join(BACKEND_DIR, 'venv', 'bin', 'python');
  if (fs.existsSync(venvPython)) return venvPython;
  // CI installs dependencies straight into the job's system Python (see
  // ci.yml's backend-tests job) rather than a venv.
  return process.platform === 'win32' ? 'python' : 'python3';
}

function run(args) {
  execFileSync(pythonBin(), [SEED_SCRIPT, ...args], {
    cwd: BACKEND_DIR,
    stdio: 'inherit',
    env: {
      ...process.env,
      MONGO_URL: process.env.MONGO_URL || 'mongodb://localhost:27017',
      DB_NAME: process.env.DB_NAME || 'test_database',
    },
  });
}

function seedSession(userId, token, { premium = false } = {}) {
  const args = ['seed-session', '--user-id', userId, '--token', token];
  if (premium) args.push('--premium');
  run(args);
}

function seedTrip(tripId, userId, tripJson) {
  run(['seed-trip', '--trip-id', tripId, '--user-id', userId, '--json', JSON.stringify(tripJson)]);
}

function cleanup(userId, token, tripId) {
  const args = ['cleanup', '--user-id', userId, '--token', token];
  if (tripId) args.push('--trip-id', tripId);
  run(args);
}

module.exports = { seedSession, seedTrip, cleanup };
