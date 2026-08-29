import { publicEnv } from './env';

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
  url: publicEnv.NEXT_PUBLIC_SITE_URL,
  locale: 'en_ZA',
  themeColor: '#0b1f3a',
  backgroundColor: '#0b1f3a',
};
