import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Without this, Turbopack walks up to the home directory looking for a lockfile.
  turbopack: { root: __dirname },
};

export default nextConfig;
