import type { Metadata } from 'next';

import Link from 'next/link';

import Badge from '@/components/ui/badge';
import Button from '@/components/ui/button';
import StatusPill from '@/components/ui/status-pill';
import Table, { Td, Th } from '@/components/ui/table';
import { listFeeds } from '@/features/feed-importer/server/queries';

export const metadata: Metadata = { title: 'Feeds' };

export const dynamic = 'force-dynamic';

const formatWhen = (iso: string | null): string => {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-ZA', { hour12: false });
};

const FeedsPage = async () => {
  const feeds = await listFeeds();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Feeds</h1>
          <p className="text-sm text-ink-muted">
            {feeds.length} configured {feeds.length === 1 ? 'feed' : 'feeds'}.
          </p>
        </div>
        <Link href="/ops/feeds/new">
          <Button variant="primary">Add feed</Button>
        </Link>
      </div>

      {feeds.length === 0 ? (
        <p className="rounded-md border border-line bg-surface px-4 py-8 text-center text-sm text-ink-muted">
          No feeds yet. Add one to get started.
        </p>
      ) : (
        <Table
          head={
            <tr>
              <Th>Vendor</Th>
              <Th>Code</Th>
              <Th>Active</Th>
              <Th>Last run</Th>
              <Th>Result</Th>
            </tr>
          }
        >
          {feeds.map((feed) => (
            <tr key={feed.code}>
              <Td>
                <Link
                  className="font-medium text-accent hover:underline"
                  href={`/ops/feeds/${feed.code}`}
                >
                  {feed.vendorName}
                </Link>
                <div className="text-xs text-ink-muted">{feed.name}</div>
              </Td>
              <Td>
                <code className="text-xs">{feed.code}</code>
              </Td>
              <Td>{feed.isActive ? <Badge tone="ok">active</Badge> : <Badge>paused</Badge>}</Td>
              <Td>
                <span className="text-xs tabular-nums">
                  {formatWhen(feed.lastJob?.finishedAt ?? null)}
                </span>
              </Td>
              <Td>
                {feed.lastJob ? (
                  <div className="flex flex-col gap-1">
                    <StatusPill status={feed.lastJob.status} />
                    <span className="text-xs text-ink-muted tabular-nums">
                      {feed.lastJob.recordsInserted} new · {feed.lastJob.recordsUpdated} updated ·{' '}
                      {feed.lastJob.recordsFailed} failed
                    </span>
                  </div>
                ) : (
                  <span className="text-xs text-ink-muted">never run</span>
                )}
              </Td>
            </tr>
          ))}
        </Table>
      )}
    </div>
  );
};

export default FeedsPage;
