import type { Metadata, Viewport } from "next";
import Script from "next/script";
import "./globals.css";
import { Providers } from "./providers";
import { Analytics } from "@vercel/analytics/next";
import { SpeedInsights } from "@vercel/speed-insights/next";

// ── Analytics IDs (set in Vercel env vars for production) ──
const GA4_ID = process.env.NEXT_PUBLIC_GA4_ID || "";
const CLARITY_ID = process.env.NEXT_PUBLIC_CLARITY_ID || "";

export const metadata: Metadata = {
  title: "YieldIQ — Know if a stock is undervalued",
  description:
    "Free DCF valuation for 2,900+ NSE/BSE stocks. Instant fair value, margin of safety, and quality scores.",
  manifest: "/manifest.json",
  icons: {
    icon: "/logo-new.svg",
    apple: "/logo-new.svg",
  },
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "YieldIQ",
  },
  openGraph: {
    title: "YieldIQ — Know if a stock is undervalued",
    description: "Free DCF valuation for 2,900+ NSE/BSE stocks. Instant fair value, margin of safety, and quality scores.",
    url: "https://yieldiq.in",
    siteName: "YieldIQ",
    type: "website",
    locale: "en_IN",
  },
  twitter: {
    card: "summary_large_image",
    title: "YieldIQ — Stock Valuation for Indian Investors",
    description: "Free DCF analysis for NSE/BSE stocks. Know the fair value before you invest.",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  themeColor: "#1D4ED8",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <head>
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
      <body className="min-h-full flex flex-col bg-gray-50 text-gray-900">
        <Providers>{children}</Providers>
        <Analytics />
        <SpeedInsights />
      </body>
    </html>
  );
}
