import path from "path";

/** @type {import('next').NextConfig} */
const nextConfig = {
  distDir: process.env.NEXT_DIST_DIR || ".next",
  reactStrictMode: true,
  poweredByHeader: false,
  eslint: {
    ignoreDuringBuilds: true
  },
  typescript: {
    ignoreBuildErrors: false
  },
  webpack(config) {
    const animalStub = path.resolve(process.cwd(), "lib/animalIslandStub.tsx");
    config.resolve.alias = {
      ...(config.resolve.alias ?? {}),
      "animal-island-ui/dist/es/components/WeddingInvitation/WeddingInvitation.js": animalStub,
      "animal-island-ui/dist/es/components/WeddingInvitation/fonts.js": animalStub,
      "./components/WeddingInvitation/WeddingInvitation.js": animalStub,
      "./components/WeddingInvitation/fonts.js": animalStub
    };
    return config;
  }
};

export default nextConfig;
