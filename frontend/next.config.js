/** @type {import('next').NextConfig} */
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
module.exports = {
  async rewrites() {
    // proxy /api/* -> backend (evita CORS y oculta el origen real al navegador)
    return [{ source: "/api/:path*", destination: `${API}/:path*` }];
  },
};
