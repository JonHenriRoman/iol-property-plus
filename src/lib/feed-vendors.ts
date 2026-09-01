/**
 * The feed vendor registry — the single source of truth for the two-layer
 * credential model (see the plan). Executable config, not prose.
 *
 * Layer 2 (here, `fields`): the visible identity/config an operator fills in on
 * the add/edit form — which agency / office / site / provinces this feed is for.
 * These are written to the `feed_sources` row (`base_url` or `auth_config`).
 *
 * Layer 1 (`secretsNote` only): the shared vendor account credentials
 * (Basic-auth, API keys, SigV4, security tokens). These resolve from
 * env / secrets inside the Python importer (`iol_importers.config.resolve_*`)
 * and are never shown or edited on this screen. The note is displayed read-only
 * so an operator knows what must be configured out of band.
 *
 * `slug` doubles as the dispatch key for `iol_importers.dryrun` and the prefix
 * convention for `feed_sources.code` (e.g. `allsa-10173`).
 */

type VendorFieldTarget = 'base_url' | 'auth_config';

type VendorField = {
  key: string;
  label: string;
  type: 'text' | 'url';
  required: boolean;
  target: VendorFieldTarget;
  help?: string;
  /** Comma-separated input that is stored as a JSON string array. */
  list?: boolean;
  /**
   * A per-feed value that is technically a credential but is scoped to this one
   * feed (a site key, a feed token) rather than a shared vendor account. Rendered
   * masked. Still stored on the row — the shared account secrets in `secretsNote`
   * never are. (Moving these fully behind the scenes is a tracked follow-up.)
   */
  sensitive?: boolean;
};

type Vendor = {
  slug: string;
  label: string;
  feedFormat: 'XML' | 'JSON' | 'CSV' | 'API';
  dryRunSupported: boolean;
  dryRunNote?: string;
  fields: VendorField[];
  secretsNote: string;
};

const url = (key: string, label: string, required: boolean, help: string): VendorField => ({
  key,
  label,
  type: 'url',
  required,
  target: 'base_url',
  help,
});

const authField = (
  key: string,
  label: string,
  required: boolean,
  help: string,
  extra: { list?: boolean; sensitive?: boolean } = {},
): VendorField => ({
  key,
  label,
  type: 'text',
  required,
  target: 'auth_config',
  help,
  list: extra.list ?? false,
  sensitive: extra.sensitive ?? false,
});

const NO_DRY_RUN = 'This vendor has no dry-run mode yet — run it from the CLI to test.';

const VENDORS: Vendor[] = [
  {
    slug: 'allsa',
    label: 'AllSA Property',
    feedFormat: 'XML',
    dryRunSupported: true,
    fields: [
      url('base_url', 'Endpoint URL', false, 'Leave blank to use the default AllSA endpoint.'),
      authField('agency_id', 'Agency ID', true, 'The agencyid AllSA issued for this account.'),
    ],
    secretsNote: 'None — the AllSA endpoint is public.',
  },
  {
    slug: 'propertypost',
    label: 'PropertyPost',
    feedFormat: 'CSV',
    dryRunSupported: true,
    fields: [
      url('base_url', 'Feed URL', true, 'The full per-agency file URL, e.g. …/BstProperties.txt.'),
    ],
    secretsNote: 'None — a plain public GET.',
  },
  {
    slug: 'rt3',
    label: 'RT3 (Rawson)',
    feedFormat: 'CSV',
    dryRunSupported: true,
    fields: [
      url('base_url', 'Host URL', false, 'Leave blank to use the default Rawson host.'),
      authField(
        'provinces',
        'Provinces',
        true,
        'Comma-separated province tokens as they appear in the URL, e.g. Western_Cape, Gauteng. One file is pulled per province.',
        { list: true },
      ),
    ],
    secretsNote: 'None — the province files are public.',
  },
  {
    slug: 'myroof',
    label: 'MyRoof',
    feedFormat: 'CSV',
    dryRunSupported: true,
    fields: [
      url('base_url', 'Host URL', false, 'Leave blank to use the default MyRoof host.'),
      authField('token', 'Feed token', true, 'The opaque per-franchise feed token.', {
        sensitive: true,
      }),
    ],
    secretsNote: 'None beyond the per-franchise feed token above.',
  },
  {
    slug: 'webbox',
    label: 'Webbox',
    feedFormat: 'XML',
    dryRunSupported: true,
    fields: [
      url(
        'base_url',
        'Site domain',
        true,
        'The site’s domain, e.g. https://www.valuablesproperties.co.za.',
      ),
      authField('siteid', 'Site ID', true, 'The Webbox site id for this feed.'),
      authField('securitykey', 'Security key', true, 'The Webbox security key for this site.', {
        sensitive: true,
      }),
    ],
    secretsNote: 'None beyond the per-site security key above.',
  },
  {
    slug: 'entegral',
    label: 'Entegral',
    feedFormat: 'XML',
    dryRunSupported: true,
    fields: [],
    secretsNote: 'ENTEGRAL_USERNAME / ENTEGRAL_PASSWORD (environment).',
  },
  {
    slug: 'fusion',
    label: 'Fusion',
    feedFormat: 'XML',
    dryRunSupported: true,
    fields: [],
    secretsNote: 'FUSION_CLIENT_ID / FUSION_PASSWORD (environment).',
  },
  {
    slug: 'propertyengine',
    label: 'PropertyEngine',
    feedFormat: 'XML',
    dryRunSupported: true,
    fields: [
      url(
        'base_url',
        'Feed URL',
        false,
        'Leave blank to use PROPERTYENGINE_FEED_URL from the environment.',
      ),
    ],
    secretsNote: 'PROPERTYENGINE_FEED_URL (+ optional token) (environment).',
  },
  {
    slug: 'remax',
    label: 'RE/MAX',
    feedFormat: 'API',
    dryRunSupported: false,
    dryRunNote: NO_DRY_RUN,
    fields: [
      authField(
        'office_id',
        'Office ID',
        false,
        'RE/MAX office id — leave blank to import the whole account.',
      ),
      authField(
        'agency_name',
        'Agency name',
        false,
        'Display label only (not yet used by the importer).',
      ),
    ],
    secretsNote: 'REMAX_ACCESS_KEY / REMAX_SECRET_KEY / REMAX_API_KEY (environment).',
  },
  {
    slug: 'propdata',
    label: 'Propdata',
    feedFormat: 'JSON',
    dryRunSupported: false,
    dryRunNote: NO_DRY_RUN,
    fields: [authField('site_id', 'Site ID', false, 'Optional — not yet used by the importer.')],
    secretsNote: 'PROP_DATA_API_USERNAME / PROP_DATA_API_PASSWORD (environment).',
  },
  {
    slug: 'propctrl',
    label: 'PropCtrl',
    feedFormat: 'API',
    dryRunSupported: false,
    dryRunNote: NO_DRY_RUN,
    fields: [
      authField('agency_id', 'Agency ID', false, 'Optional — not yet used by the importer.'),
      authField('branch_id', 'Branch ID', false, 'Optional — not yet used by the importer.'),
    ],
    secretsNote: 'PROPCTRL_API_USERNAME / PROPCTRL_API_PASSWORD (environment).',
  },
];

const VENDORS_BY_SLUG: Record<string, Vendor> = Object.fromEntries(VENDORS.map((v) => [v.slug, v]));

const VENDOR_SLUGS = VENDORS.map((v) => v.slug);

const getVendor = (slug: string): Vendor | undefined => VENDORS_BY_SLUG[slug];

/** The vendor whose slug prefixes this `feed_sources.code` (by convention `<slug>-…`). */
const vendorForFeedCode = (code: string): Vendor | undefined =>
  VENDORS.find((v) => code === v.slug || code.startsWith(`${v.slug}-`));

/** The vendor matching a stored `feed_sources.vendor_name` label. */
const vendorByLabel = (label: string): Vendor | undefined => VENDORS.find((v) => v.label === label);

export { getVendor, VENDOR_SLUGS, vendorByLabel, vendorForFeedCode, VENDORS };
export type { Vendor, VendorField };
