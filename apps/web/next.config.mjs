/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Type imports from packages/contracts/ts live outside the app directory.
  experimental: { externalDir: true },
};

export default nextConfig;
