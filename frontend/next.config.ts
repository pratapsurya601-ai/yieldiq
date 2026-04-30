import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

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

export default withSentryConfig(nextConfig, {
  org: "yieldiq",
  project: "yieldiq-frontend",
  silent: !process.env.CI,
  widenClientFileUpload: true,
  reactComponentAnnotation: { enabled: true },
  // hideSourceMaps was removed in @sentry/nextjs v8+ — sourcemaps are now
  // deleted after upload by default (deleteSourcemapsAfterUpload), so the
  // ".map" files never ship to the public web bundle.
  disableLogger: true,
  automaticVercelMonitors: true,
});
