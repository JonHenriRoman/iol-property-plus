import { test as base, expect } from '@playwright/test';

/**
 * Every e2e test runs through this fixture, which fails the test if the page
 * contacts any origin other than the local server — the deterministic /
 * offline guarantee, enforced in the browser.
 */
const test = base.extend({
  page: async ({ page, baseURL }, use) => {
    const allowed = new URL(baseURL ?? 'http://localhost:3100').host;
    const offenders: string[] = [];

    page.on('request', (req) => {
      const { protocol, host } = new URL(req.url());
      if (protocol.startsWith('http') && host !== allowed) offenders.push(req.url());
    });

    await use(page);

    expect(offenders, `page made external requests:\n${offenders.join('\n')}`).toEqual([]);
  },
});

export { expect, test };
