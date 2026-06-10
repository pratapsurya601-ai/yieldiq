import type { Metadata, Viewport } from "next";
import Script from "next/script";
import { Inter, Inter_Tight, JetBrains_Mono, Fraunces } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { Analytics } from "@vercel/analytics/next";
// NOTE: @vercel/speed-insights intentionally removed — the Speed Insights
// ingestion endpoint (/_vercel/speed-insights/vitals, served via the
// hashed /<id>/vitals path) was returning a consistent 503 on every
// page load because Speed Insights isn't enabled on the Vercel project.
// That polluted Sentry / network-error monitoring with a fixed-rate
// failure. To re-enable, enable "Speed Insights" on the Vercel dashboard,
// re-add `@vercel/speed-insights` to package.json, and mount
// `<SpeedInsights />` next to `<Analytics />` below.
import BetaBanner from "@/components/marketing/BetaBanner";
import IncidentBanner from "@/components/IncidentBanner";
import ServiceWorkerRegister from "@/components/ServiceWorkerRegister";

// ── Typography (next/font, self-hosted, no FOUT) ──
// Inter Tight serves as our "display" face (used for headings via
// the `font-display` utility). Inter is the body/sans face. JetBrains
// Mono renders numeric displays (prices, scores, percentages) — pairs
// perfectly with tabular-nums since it already has distinctive digits.
const fontSans = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const fontDisplay = Inter_Tight({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
});

const fontMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

// Editorial serif — Fraunces with the optical-size axis enabled so large
// hero headlines render with the display-optimized glyph shapes while
// smaller usages stay readable. Used via `font-editorial` utility.
// NOTE: Fraunces is a variable font; we request the `opsz` optical-size axis
// in addition to the default `wght`. next/font requires `weight` to be unset
// (or "variable") when `axes` is provided, so we omit weight here — the
// browser can still access the full 100–900 range via font-weight CSS.
const fontEditorial = Fraunces({
  subsets: ["latin"],
  variable: "--font-editorial",
  display: "swap",
  axes: ["opsz"],
  adjustFontFallback: true,
});

// ── Analytics IDs (set in Vercel env vars for production) ──
const GA4_ID = process.env.NEXT_PUBLIC_GA4_ID || "";
// TODO: re-enable once Clarity tag ID is regenerated
// const CLARITY_ID = process.env.NEXT_PUBLIC_CLARITY_ID || "";

// Inline script string: reads the user's saved theme preference from
// localStorage BEFORE React hydrates so we avoid a dark-to-light
// flash on first paint. Standard anti-FOUC pattern.
//
// Migration (2026-06): dark is now the premium-fintech default
// (Bloomberg / Koyfin / TradingView / AlphaSpread). Anything other
// than "light" — missing key, garbage, legacy "system" sentinel —
// resolves to dark, and non-canonical values are rewritten to "dark"
// so the migration only runs once per browser. An explicit "light"
// preference from a returning user is preserved as-is.
const themeInitScript = `(function(){try{var s=localStorage.getItem('yieldiq_theme');if(s!=='dark'&&s!=='light'){try{localStorage.setItem('yieldiq_theme','dark');}catch(e){}s='dark';}var e=document.documentElement;if(s==='light'){e.classList.remove('dark');}else{e.classList.add('dark');}}catch(e){}})();`;

// Motion-off init: same anti-FOUC pattern as theme. If the user has
// flipped the in-app "Reduce motion" toggle (localStorage key
// `yq:motion-off`), we add `data-yq-motion-off="1"` to <html> before
// first paint so CSS utilities (.hover-lift, .pressable, .shimmer,
// etc.) can disable themselves in lockstep with the React hook.
const motionInitScript = `(function(){try{if(localStorage.getItem('yq:motion-off')==='1'){document.documentElement.setAttribute('data-yq-motion-off','1');}}catch(e){}})();`;

export const metadata: Metadata = {
  // Root-level default title. Per-route layouts under (app)/ override
  // this so a user with five tabs open sees five distinct titles
  // instead of one generic string (audit 2026-05-26 P1).
  title: {
    default: "YieldIQ — DCF Stock Analysis for Indian Markets",
    template: "%s",
  },
  description:
    "Free DCF valuation for 2,300+ NSE & BSE stocks. Instant fair value, margin of safety, and quality scores.",
  manifest: "/manifest.json",
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/favicon-16.png", type: "image/png", sizes: "16x16" },
      { url: "/favicon-32.png", type: "image/png", sizes: "32x32" },
      { url: "/icon-192.png", type: "image/png", sizes: "192x192" },
      { url: "/icon-512.png", type: "image/png", sizes: "512x512" },
    ],
    apple: [
      { url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" },
    ],
    shortcut: "/favicon.ico",
  },
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "YieldIQ",
  },
  openGraph: {
    title: "YieldIQ — Fair-value estimates for Indian stocks",
    description: "Free DCF valuation for 2,300+ NSE & BSE stocks. Instant fair value, margin of safety, and quality scores.",
    url: "https://yieldiq.in",
    siteName: "YieldIQ",
    type: "website",
    locale: "en_IN",
    images: [
      {
        url: "https://yieldiq.in/icon-512.png",
        width: 512,
        height: 512,
        alt: "YieldIQ — Stock Valuation Tool",
      },
    ],
  },
  twitter: {
    card: "summary",
    title: "YieldIQ — Stock Valuation for Indian Investors",
    description: "Free DCF analysis for NSE/BSE stocks. Know the fair value before you invest.",
    images: ["https://yieldiq.in/icon-512.png"],
  },
};

export const viewport: Viewport = {
  // Accessibility: do NOT set maximumScale or userScalable=false — that
  // blocks pinch-to-zoom and trips a Lighthouse a11y audit violation.
  // Keep the viewport minimal: device-width + initial-scale=1.
  //
  // themeColor pairs to the resolved theme: dark default uses --color-bg
  // dark (#0B1220) so the mobile browser chrome (Android Chrome address
  // bar, iOS status-bar tint) matches the page background; the light
  // override applies for users who explicitly flip back via the toggle.
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0B1220" },
    { media: "(prefers-color-scheme: light)", color: "#0B1220" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`h-full antialiased ${fontSans.variable} ${fontDisplay.variable} ${fontMono.variable} ${fontEditorial.variable}`}
      suppressHydrationWarning
    >
      <head>
        {/* Anti-FOUC theme init — must run before body paint. */}
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
        {/* Motion-off init — same pattern, drives [data-yq-motion-off]. */}
        <script dangerouslySetInnerHTML={{ __html: motionInitScript }} />

        {/* Google Analytics 4 */}
        {GA4_ID && (
          <>
            <Script
              src={`https://www.googletagmanager.com/gtag/js?id=${GA4_ID}`}
              strategy="afterInteractive"
            />
            <Script id="ga4-init" strategy="afterInteractive">
              {`
                window.dataLayer = window.dataLayer || [];
                function gtag(){dataLayer.push(arguments);}
                gtag('js', new Date());
                gtag('config', '${GA4_ID}', {
                  page_title: document.title,
                  page_location: window.location.href,
                });
              `}
            </Script>
          </>
        )}

        {/* Microsoft Clarity — heatmaps and session recordings */}
        {/* TODO: re-enable once Clarity tag ID is regenerated */}
        {/* Disabled 2026-04-27: tag returned HTTP 400 on every page load
            (DevTools audit on yieldiq.in). Re-enable by uncommenting once
            a fresh project is provisioned and NEXT_PUBLIC_CLARITY_ID is
            updated in Vercel env vars. */}
        {/*
        {CLARITY_ID && (
          <Script id="clarity-script" strategy="afterInteractive">
            {`
              (function(c,l,a,r,i,t,y){
                c[a]=c[a]||function(){(c[a].q=c[a].q||[]).push(arguments)};
                t=l.createElement(r);t.async=1;t.src="https://www.clarity.ms/tag/"+i;
                y=l.getElementsByTagName(r)[0];y.parentNode.insertBefore(t,y);
              })(window, document, "clarity", "script", "${CLARITY_ID}");
            `}
          </Script>
        )}
        */}
      </head>
      <body className="min-h-full flex flex-col bg-bg text-body font-sans">
        {/* Recent-incident notice (dismissible, surfaces for 7 days post-incident) */}
        <IncidentBanner />
        <BetaBanner />
        <Providers>{children}</Providers>
        <ServiceWorkerRegister />
        <Analytics />
      </body>
    </html>
  );
}
