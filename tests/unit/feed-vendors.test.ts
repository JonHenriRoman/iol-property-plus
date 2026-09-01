import { describe, expect, it } from 'vitest';

import {
  getVendor,
  VENDOR_SLUGS,
  vendorByLabel,
  vendorForFeedCode,
  VENDORS,
} from '@/lib/feed-vendors';

describe('feed vendor registry', () => {
  it('has the 11 known adapters, with unique slugs and labels', () => {
    expect(VENDORS).toHaveLength(11);
    expect(new Set(VENDOR_SLUGS).size).toBe(11);
    expect(new Set(VENDORS.map((v) => v.label)).size).toBe(11);
  });

  it('marks exactly the three adapters without a dry-run mode', () => {
    const noDryRun = VENDORS.filter((v) => !v.dryRunSupported)
      .map((v) => v.slug)
      .sort();
    expect(noDryRun).toEqual(['propctrl', 'propdata', 'remax']);
    for (const v of VENDORS) {
      if (!v.dryRunSupported) expect(v.dryRunNote).toBeTruthy();
    }
  });

  it('every field targets base_url or auth_config and has help text', () => {
    for (const vendor of VENDORS) {
      for (const field of vendor.fields) {
        expect(['base_url', 'auth_config']).toContain(field.target);
        expect(field.help && field.help.length).toBeGreaterThan(0);
      }
    }
  });

  it('resolves a vendor from a feed_sources code prefix', () => {
    expect(vendorForFeedCode('allsa-10173')?.slug).toBe('allsa');
    expect(vendorForFeedCode('webbox')?.slug).toBe('webbox');
    expect(vendorForFeedCode('rt3-rawson')?.slug).toBe('rt3');
    expect(vendorForFeedCode('nonsense-x')).toBeUndefined();
  });

  it('resolves a vendor from its stored label', () => {
    expect(vendorByLabel('AllSA Property')?.slug).toBe('allsa');
    expect(vendorByLabel('RE/MAX')?.slug).toBe('remax');
    expect(vendorByLabel('Unknown')).toBeUndefined();
  });

  it('getVendor is a direct slug lookup', () => {
    expect(getVendor('fusion')?.label).toBe('Fusion');
    expect(getVendor('missing')).toBeUndefined();
  });
});
