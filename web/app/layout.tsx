import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Vegetable Price Intelligence | From Market Signals to Pricing Decisions',
  description:
    'An economics-informed pricing intelligence system connecting historical market signals, auditable forecasts, risk alerts and risk-adjusted procurement costs.',
  openGraph: {
    title: 'Vegetable Price Intelligence | Market-to-Pricing Decisions',
    description: 'Historical market signals, forecast governance, price-risk alerts and risk-adjusted cost inputs for pricing decisions.',
    type: 'website',
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
