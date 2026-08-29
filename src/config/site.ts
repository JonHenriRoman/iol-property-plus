/**
 * Typed public site configuration.
 *
 * Safe for browser exposure. Anything secret belongs in a server module, not here.
 */

export interface SiteConfig {
  name: string;
  description: string;
  url: string;
}

export const siteConfig: SiteConfig = {
  name: 'IOL Property Plus',
  description: 'IOL Property Plus corporate website.',
  url: process.env.NEXT_PUBLIC_SITE_URL ?? 'http://localhost:3000',
};
