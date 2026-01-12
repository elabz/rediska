/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  experimental: {
    serverActions: {
      allowedOrigins: ['rediska.local', 'localhost:3000'],
    },
  },
};

module.exports = nextConfig;
