import type { Metadata } from 'next';

import { siteConfig } from '@/config/site';

import './globals.css';

const htmlLang = siteConfig.locale.replace('_', '-');

export const metadata: Metadata = {
  metadataBase: new URL(siteConfig.url),
  title: {
    default: siteConfig.name,
    template: `%s | ${siteConfig.name}`,
  },
  description: siteConfig.description,
  applicationName: siteConfig.name,
  alternates: {
    canonical: '/',
  },
  openGraph: {
    type: 'website',
    locale: siteConfig.locale,
    url: siteConfig.url,
    siteName: siteConfig.name,
    title: siteConfig.name,
    description: siteConfig.description,
  },
  twitter: {
    card: 'summary_large_image',
    title: siteConfig.name,
    description: siteConfig.description,
  },
};

const RootLayout = ({ children }: { children: React.ReactNode }) => {
  return (
    <html lang={htmlLang}>
      <body>{children}</body>
    </html>
  );
};

export default RootLayout;
