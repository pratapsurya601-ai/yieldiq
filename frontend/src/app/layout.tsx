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
const CLARITY_ID = process.env.NEXT_PUBLIC_CLARITY_ID || "";

// Inline script string: reads the user's saved theme preference from
// localStorage BEFORE React hydrates so we avoid a light-to-dark
// flash on first paint. Standard anti-FOUC pattern.
const themeInitScript = `(function(){try{var s=localStorage.getItem('yieldiq_theme');var m=window.matchMedia('(prefers-color-scheme: dark)').matches;var d=s==='dark'||((s==='system'||!s)&&m);var e=document.documentElement;if(d){e.classList.add('dark');}else{e.classList.remove('dark');}}catch(e){}})();`;

export const metadata: Metadata = {
  title: "YieldIQ — Fair-value estimates for Indian stocks",
  description:
    "Free DCF valuation for 2,900+ NSE/BSE stocks. Instant fair value, margin of safety, and quality scores.",
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
    description: "Free DCF valuation for 2,900+ NSE/BSE stocks. Instant fair value, margin of safety, and quality scores.",
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
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  themeColor: "#2563EB",
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
      </head>
      <body className="min-h-full flex flex-col bg-bg text-body font-sans">
        <BetaBanner />
        <Providers>{children}</Providers>
        <ServiceWorkerRegister />
        <Analytics />
      </body>
    </html>
  );
}
