import { describe, expect, it } from 'vitest';

import { siteConfig } from '@/config/site';

import manifest from '../../src/app/manifest';
import robots from '../../src/app/robots';
import sitemap from '../../src/app/sitemap';

describe('sitemap()', () => {
  it('lists an absolute URL from siteConfig with a priority', () => {
    const entries = sitemap();
    expect(entries).toHaveLength(1);
    expect(entries[0]?.url).toBe(siteConfig.url);
    expect(new URL(entries[0]!.url).protocol).toMatch(/^https?:$/);
    expect(entries[0]?.priority).toBe(1);
  });
});

describe('robots()', () => {
  it('allows /, disallows /api/, and names the sitemap', () => {
    const r = robots();
    const rules = Array.isArray(r.rules) ? r.rules[0] : r.rules;
    expect(rules?.allow).toBe('/');
    expect(rules?.disallow).toBe('/api/');
    expect(r.sitemap).toBe(`${siteConfig.url}/sitemap.xml`);
  });
});

describe('manifest()', () => {
  it('is a standalone PWA manifest with icons and brand colours', () => {
    const m = manifest();
    expect(m.name).toBe(siteConfig.name);
    expect(m.short_name).toBe(siteConfig.shortName);
    expect(m.display).toBe('standalone');
    expect(m.background_color).toBe(siteConfig.backgroundColor);
    expect(m.icons?.map((i) => i.src)).toEqual(['/icon', '/apple-icon']);
  });
});
