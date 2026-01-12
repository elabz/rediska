/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  experimental: {
    serverActions: {
      allowedOrigins: ['rediska.local', 'localhost:3000'],
    },
  },
  async rewrites() {
    return [
      {
        // API routes in src/app/api/core take precedence for auth endpoints
        source: '/api/core/:path*',
        destination: `${process.env.CORE_API_URL || 'http://localhost:8000'}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
