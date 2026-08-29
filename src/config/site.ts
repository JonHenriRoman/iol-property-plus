/**
 * Typed public site configuration.
 *
 * Safe for browser exposure. Anything secret belongs in a server module, not here.
 */

export interface SiteConfig {
  name: string;
  shortName: string;
  description: string;
  url: string;
  locale: string;
  themeColor: string;
  backgroundColor: string;
}

export const siteConfig: SiteConfig = {
  name: 'IOL Property Plus',
  shortName: 'Property Plus',
  description: 'IOL Property Plus corporate website.',
  url: process.env.NEXT_PUBLIC_SITE_URL ?? 'http://localhost:3000',
  locale: 'en_ZA',
  themeColor: '#0b1f3a',
  backgroundColor: '#0b1f3a',
};
