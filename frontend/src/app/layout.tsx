import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "YieldIQ — Know if a stock is undervalued",
  description:
    "Free DCF valuation for NSE & BSE stocks. YieldIQ Score, margin of safety, Piotroski F-Score, and AI insights for Indian investors.",
  manifest: "/manifest.json",
  icons: {
    icon: "/logo_icon.jpeg",
    apple: "/logo.jpeg",
  },
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "YieldIQ",
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
      <body className="min-h-full flex flex-col bg-gray-50 text-gray-900">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
