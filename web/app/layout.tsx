import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  metadataBase: new URL('http://localhost:3000'),
  title: 'Vegetable Price Intelligence | From Market Signals to Pricing Decisions',
  description:
    'An economics-informed pricing intelligence system connecting historical market signals, auditable forecasts, risk alerts, procurement costs and common-shock exposure.',
  openGraph: {
    title: 'Vegetable Price Intelligence | Market-to-Pricing Decisions',
    description: 'Historical market signals, forecast governance, price-risk alerts, risk-adjusted costs and common-shock exposure for pricing decisions.',
    type: 'website',
    images: [{ url: '/og.png', width: 3072, height: 1728, alt: 'Vegetable Price Intelligence portfolio cover' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Vegetable Price Intelligence',
    description: 'From market signals to governed pricing decisions.',
    images: ['/og.png'],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
