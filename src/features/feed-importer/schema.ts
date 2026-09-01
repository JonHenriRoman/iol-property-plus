import { z } from 'zod';

import { getVendor, VENDOR_SLUGS } from '@/lib/feed-vendors';

/**
 * Validation for the add/edit feed form. The static shape is checked with zod;
 * the per-vendor identity fields are checked against the registry
 * (`vendors.ts`), since which fields exist depends on the chosen vendor.
 */

const codeRule = z
  .string()
  .trim()
  .min(3, 'Give the feed a code (at least 3 characters).')
  .max(64)
  .regex(
    /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/,
    'Lowercase letters, digits and hyphens; must start and end with a letter or digit.',
  );

const baseSchema = z.object({
  vendor: z.enum(VENDOR_SLUGS as [string, ...string[]]),
  code: codeRule,
  name: z.string().trim().min(1, 'Give the feed a name.').max(200),
  isActive: z.boolean(),
});

type FeedFormFields = Record<string, string>;

type ParsedFeed = {
  code: string;
  name: string;
  vendorName: string;
  vendorSlug: string;
  format: 'XML' | 'JSON' | 'CSV' | 'API';
  baseUrl: string | null;
  authConfig: Record<string, string | string[]>;
};

type ParseResult =
  { ok: true; data: ParsedFeed } | { ok: false; fieldErrors: Record<string, string> };

const parseFeedForm = (raw: FeedFormFields): ParseResult => {
  const fieldErrors: Record<string, string> = {};

  const base = baseSchema.safeParse({
    vendor: raw.vendor,
    code: raw.code,
    name: raw.name,
    isActive: raw.isActive === 'on' || raw.isActive === 'true',
  });

  if (!base.success) {
    for (const issue of base.error.issues) {
      const key = String(issue.path[0] ?? 'form');
      fieldErrors[key] ??= issue.message;
    }
    return { ok: false, fieldErrors };
  }

  const vendor = getVendor(base.data.vendor);
  if (!vendor) {
    return { ok: false, fieldErrors: { vendor: 'Unknown vendor.' } };
  }

  if (!base.data.code.startsWith(`${vendor.slug}-`) && base.data.code !== vendor.slug) {
    fieldErrors.code = `Convention: start the code with "${vendor.slug}-".`;
  }

  let baseUrl: string | null = null;
  const authConfig: Record<string, string | string[]> = {};

  for (const field of vendor.fields) {
    const value = (raw[field.key] ?? '').trim();

    if (!value) {
      if (field.required) fieldErrors[field.key] = `${field.label} is required.`;
      continue;
    }

    if (field.type === 'url' && !/^https?:\/\/.+/i.test(value)) {
      fieldErrors[field.key] = 'Enter a full http(s) URL.';
      continue;
    }

    if (field.target === 'base_url') {
      baseUrl = value;
    } else if (field.list) {
      authConfig[field.key] = value
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
    } else {
      authConfig[field.key] = value;
    }
  }

  if (Object.keys(fieldErrors).length > 0) return { ok: false, fieldErrors };

  return {
    ok: true,
    data: {
      code: base.data.code,
      name: base.data.name,
      vendorName: vendor.label,
      vendorSlug: vendor.slug,
      format: vendor.feedFormat,
      baseUrl,
      authConfig,
    },
  };
};

export { parseFeedForm };
export type { ParsedFeed, ParseResult };
