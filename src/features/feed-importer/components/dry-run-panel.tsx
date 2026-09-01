'use client';

import { useActionState } from 'react';

import Badge from '@/components/ui/badge';
import Button from '@/components/ui/button';

import type { DryRunState } from '../server/actions';

type Action = (prev: DryRunState, formData: FormData) => Promise<DryRunState>;

const EMPTY: DryRunState = { ran: false };

const DryRunPanel = ({
  code,
  action,
  dryRunSupported,
  dryRunNote,
}: {
  code: string;
  action: Action;
  dryRunSupported: boolean;
  dryRunNote?: string;
}) => {
  const [state, formAction, pending] = useActionState(action, EMPTY);
  const outcome = state.outcome;

  return (
    <section className="flex flex-col gap-3 rounded-md border border-line bg-surface p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Test import</h2>
          <p className="text-xs text-ink-muted">
            Fetches and parses the feed. Writes nothing to the database.
          </p>
        </div>
        <form action={formAction}>
          <input name="code" type="hidden" value={code} />
          <Button disabled={!dryRunSupported || pending} type="submit" variant="secondary">
            {pending ? 'Running…' : 'Run test import'}
          </Button>
        </form>
      </div>

      {!dryRunSupported ? (
        <p className="text-xs text-ink-muted">{dryRunNote ?? 'No dry-run for this vendor yet.'}</p>
      ) : null}

      {outcome ? (
        <div className="flex flex-col gap-2 rounded border border-line bg-raised p-3 text-sm">
          <div className="flex items-center gap-2">
            {outcome.status === 'passed' ? (
              <Badge tone="ok">passed</Badge>
            ) : outcome.status === 'unsupported' ? (
              <Badge tone="neutral">not available</Badge>
            ) : (
              <Badge tone="danger">failed</Badge>
            )}
            <span className="text-ink-muted">{outcome.message}</span>
          </div>

          {outcome.status === 'passed' ? (
            <>
              <p className="tabular-nums">
                Records seen: <span className="font-medium">{outcome.recordsSeen ?? '—'}</span>
              </p>
              {Object.keys(outcome.diagnostics).length > 0 ? (
                <details className="text-xs text-ink-muted">
                  <summary className="cursor-pointer">Feed diagnostics</summary>
                  <pre className="mt-1 overflow-x-auto rounded bg-surface p-2">
                    {JSON.stringify(outcome.diagnostics, null, 2)}
                  </pre>
                </details>
              ) : null}
            </>
          ) : null}

          {outcome.status === 'failed' && outcome.errorType ? (
            <p className="text-xs text-ink-muted">Error type: {outcome.errorType}</p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
};

export default DryRunPanel;
