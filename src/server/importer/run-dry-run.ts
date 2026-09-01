import 'server-only';
import { execFile } from 'node:child_process';
import process from 'node:process';
import { promisify } from 'node:util';

import { getVendor } from '@/lib/feed-vendors';

/**
 * The one seam between the web app and the Python feed importers.
 *
 * Today it shells out to a co-located `importers/` checkout:
 *   uv run --project importers python -m iol_importers.dryrun <vendor> <code> --json
 *
 * A deployed environment swaps the body of `runDryRun` for an HTTP call to an
 * importer service, or an ECS RunTask — the exported signature and the
 * `DryRunOutcome` shape stay the same, so nothing upstream changes. Every input
 * is validated here and passed as an argv array (never a shell string).
 */

const exec = promisify(execFile);

const TIMEOUT_MS = 120_000;
const MAX_OUTPUT_BYTES = 512 * 1024;

type DryRunOutcome =
  | {
      status: 'passed';
      recordsSeen: number | null;
      diagnostics: Record<string, unknown>;
      message: string;
    }
  | { status: 'failed'; message: string; errorType?: string }
  | { status: 'unsupported'; message: string }
  | { status: 'error'; message: string };

/** Map the wrapper's last stdout line to an outcome. Pure; unit-tested. */
const parseDryRunOutput = (stdout: string): DryRunOutcome => {
  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(stdout.trim().split('\n').at(-1) ?? '{}') as Record<string, unknown>;
  } catch {
    return { status: 'error', message: 'The importer did not return a readable result.' };
  }

  const message = typeof parsed.message === 'string' ? parsed.message : 'Dry-run finished.';

  if (parsed.supported === false) return { status: 'unsupported', message };

  if (parsed.ok === true) {
    const seen = parsed.records_seen;
    return {
      status: 'passed',
      recordsSeen: typeof seen === 'number' ? seen : null,
      diagnostics:
        parsed.diagnostics && typeof parsed.diagnostics === 'object'
          ? (parsed.diagnostics as Record<string, unknown>)
          : {},
      message,
    };
  }

  return {
    status: 'failed',
    message,
    errorType: typeof parsed.error_type === 'string' ? parsed.error_type : undefined,
  };
};

const runDryRun = async (vendorSlug: string, feedSourceCode: string): Promise<DryRunOutcome> => {
  const vendor = getVendor(vendorSlug);
  if (!vendor) return { status: 'error', message: `Unknown vendor "${vendorSlug}".` };
  if (!vendor.dryRunSupported) {
    return { status: 'unsupported', message: vendor.dryRunNote ?? 'No dry-run for this vendor.' };
  }
  if (!/^[a-z0-9][a-z0-9-]*$/.test(feedSourceCode)) {
    return { status: 'error', message: `Invalid feed code "${feedSourceCode}".` };
  }

  try {
    const { stdout } = await exec(
      'uv',
      [
        'run',
        '--project',
        'importers',
        'python',
        '-m',
        'iol_importers.dryrun',
        vendor.slug,
        feedSourceCode,
        '--json',
      ],
      { cwd: process.cwd(), timeout: TIMEOUT_MS, maxBuffer: MAX_OUTPUT_BYTES },
    );
    return parseDryRunOutput(stdout);
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    return { status: 'error', message: `Could not run the importer: ${reason}` };
  }
};

export { parseDryRunOutput, runDryRun };
export type { DryRunOutcome };
