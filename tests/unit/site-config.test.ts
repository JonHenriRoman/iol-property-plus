import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe('siteConfig', () => {
  it('derives url from NEXT_PUBLIC_SITE_URL', async () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'https://propertyplus.example.co.za');
    vi.resetModules();
    const { siteConfig } = await import('@/config/site');
    expect(siteConfig.url).toBe('https://propertyplus.example.co.za');
  });

  it('carries the fields the metadata routes need', async () => {
    vi.resetModules();
    const { siteConfig } = await import('@/config/site');
    expect(siteConfig.name).toBe('IOL Property Plus');
    expect(siteConfig.shortName.length).toBeGreaterThan(0);
    expect(siteConfig.locale).toMatch(/^[a-z]{2}_[A-Z]{2}$/);
    expect(siteConfig.themeColor).toMatch(/^#[0-9a-f]{6}$/i);
  });
});
