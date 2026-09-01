import { describe, expect, it } from 'vitest';

import { parseFeedForm } from '@/features/feed-importer/schema';

const base = { name: 'Acme Realty', isActive: 'on' };

describe('parseFeedForm', () => {
  it('accepts a valid AllSA feed and routes fields to base_url / auth_config', () => {
    const result = parseFeedForm({
      ...base,
      vendor: 'allsa',
      code: 'allsa-10173',
      base_url: 'https://feeds.allsaproperty.co.za/iol.ashx',
      agency_id: '10173',
    });

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.data.vendorName).toBe('AllSA Property');
    expect(result.data.format).toBe('XML');
    expect(result.data.baseUrl).toBe('https://feeds.allsaproperty.co.za/iol.ashx');
    expect(result.data.authConfig).toEqual({ agency_id: '10173' });
  });

  it('rejects a missing required field', () => {
    const result = parseFeedForm({ ...base, vendor: 'allsa', code: 'allsa-x', agency_id: '' });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.fieldErrors.agency_id).toMatch(/required/i);
  });

  it('enforces the code naming convention and character set', () => {
    expect(
      parseFeedForm({ ...base, vendor: 'allsa', code: 'AllSA_10173', agency_id: '1' }).ok,
    ).toBe(false);
    const wrongPrefix = parseFeedForm({
      ...base,
      vendor: 'allsa',
      code: 'webbox-10173',
      agency_id: '1',
    });
    expect(wrongPrefix.ok).toBe(false);
    if (wrongPrefix.ok) return;
    expect(wrongPrefix.fieldErrors.code).toMatch(/allsa-/);
  });

  it('splits a comma-separated list field into an array', () => {
    const result = parseFeedForm({
      ...base,
      vendor: 'rt3',
      code: 'rt3-rawson',
      provinces: 'Western_Cape, Gauteng ,KwaZulu-Natal',
    });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.data.authConfig.provinces).toEqual(['Western_Cape', 'Gauteng', 'KwaZulu-Natal']);
  });

  it('rejects a non-URL in a url field', () => {
    const result = parseFeedForm({
      ...base,
      vendor: 'propertypost',
      code: 'propertypost-acme',
      base_url: 'not-a-url',
    });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.fieldErrors.base_url).toMatch(/url/i);
  });

  it('rejects an unknown vendor', () => {
    expect(parseFeedForm({ ...base, vendor: 'nope', code: 'nope-1' }).ok).toBe(false);
  });
});
