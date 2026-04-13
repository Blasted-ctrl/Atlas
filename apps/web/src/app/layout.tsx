import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, Manrope } from "next/font/google";
import type { ReactNode } from "react";

import "./globals.css";

const manrope = Manrope({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: {
    default: "Atlas - Cloud Cost Optimization",
    template: "%s | Atlas",
  },
  description:
    "Atlas helps engineering and finance teams understand, allocate, and reduce cloud infrastructure costs across AWS, GCP, and Azure.",
  keywords: ["cloud cost", "FinOps", "cost optimization", "AWS", "GCP", "Azure"],
  openGraph: {
    type: "website",
    locale: "en_US",
    siteName: "Atlas",
    title: "Atlas - Cloud Cost Optimization",
    description: "Understand and reduce your cloud infrastructure costs.",
  },
};

export const viewport: Viewport = {
  themeColor: "#4c6ef5",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${manrope.variable} ${plexMono.variable}`}>
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
