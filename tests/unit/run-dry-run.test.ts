import { describe, expect, it } from 'vitest';

import { parseDryRunOutput } from '@/server/importer/run-dry-run';

describe('parseDryRunOutput', () => {
  it('reads a passing dry-run with record count and diagnostics', () => {
    const stdout = JSON.stringify({
      ok: true,
      supported: true,
      records_seen: 412,
      diagnostics: { branches: { CT01: 300 }, unknown_feature_tags: {} },
      message: 'Reached the feed and parsed 412 records — nothing was written.',
    });
    const outcome = parseDryRunOutput(stdout);
    expect(outcome).toEqual({
      status: 'passed',
      recordsSeen: 412,
      diagnostics: { branches: { CT01: 300 }, unknown_feature_tags: {} },
      message: 'Reached the feed and parsed 412 records — nothing was written.',
    });
  });

  it('reads a failed dry-run and keeps the error type', () => {
    const stdout = JSON.stringify({
      ok: false,
      supported: true,
      error_type: 'WebboxConfigError',
      message: "no feed_sources row with code 'webbox-x'",
    });
    expect(parseDryRunOutput(stdout)).toEqual({
      status: 'failed',
      message: "no feed_sources row with code 'webbox-x'",
      errorType: 'WebboxConfigError',
    });
  });

  it('reads an unsupported vendor result', () => {
    const stdout = JSON.stringify({
      ok: false,
      supported: false,
      message: 'propdata has no dry-run mode yet — test it from the CLI instead.',
    });
    expect(parseDryRunOutput(stdout).status).toBe('unsupported');
  });

  it('takes only the last line of stdout', () => {
    const stdout = `warning: something\n${JSON.stringify({ ok: true, records_seen: 1, diagnostics: {} })}`;
    const outcome = parseDryRunOutput(stdout);
    expect(outcome.status).toBe('passed');
  });

  it('returns an error for unreadable output', () => {
    expect(parseDryRunOutput('Traceback (most recent call last): ...').status).toBe('error');
  });
});
