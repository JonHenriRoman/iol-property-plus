import AxeBuilder from '@axe-core/playwright';

import { expect, test } from './fixtures';

for (const { name, path } of [
  { name: 'home', path: '/' },
  { name: '404', path: '/no-such-page' },
]) {
  test(`${name} has no serious or critical accessibility violations`, async ({ page }) => {
    await page.goto(path);
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
    const serious = results.violations.filter(
      (v) => v.impact === 'serious' || v.impact === 'critical',
    );
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
  });
}
