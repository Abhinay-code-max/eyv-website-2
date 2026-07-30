/** @type {import('next').NextConfig} */
const nextConfig = {
  // Silences Next's workspace-root inference warning - this repo has
  // another lockfile up in the user's home directory unrelated to this
  // project; pin the root explicitly to this directory instead.
  turbopack: {
    root: __dirname,
  },
};

module.exports = nextConfig;
