import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 301 redirects: consolidate the old /hex/* surface into the new /prism/*
  // canonical. The /api/og/hex/:ticker route is intentionally NOT redirected —
  // Twitter/LinkedIn crawlers cache OG images by URL and may still fetch the
  // old path; keeping that image endpoint alive preserves existing share
  // previews while new shares go through /api/og/prism/*.
  async redirects() {
    return [
      {
        source: "/hex/compare/:slug",
        destination: "/prism/compare/:slug",
        permanent: true,
      },
      {
        source: "/hex/:ticker",
        destination: "/prism/:ticker",
        permanent: true,
      },
    ]
  },
};

export default nextConfig;
