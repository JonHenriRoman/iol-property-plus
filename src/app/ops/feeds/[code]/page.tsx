import type { Metadata } from 'next';

import Link from 'next/link';
import { notFound } from 'next/navigation';

import Badge from '@/components/ui/badge';
import Button from '@/components/ui/button';
import DryRunPanel from '@/features/feed-importer/components/dry-run-panel';
import FeedForm from '@/features/feed-importer/components/feed-form';
import JobHistory from '@/features/feed-importer/components/job-history';
import {
  runFeedDryRun,
  toggleFeedActive,
  updateFeed,
} from '@/features/feed-importer/server/actions';
import { getFeedByCode } from '@/features/feed-importer/server/queries';
import { vendorByLabel, vendorForFeedCode } from '@/lib/feed-vendors';

type Params = { params: Promise<{ code: string }> };

export const dynamic = 'force-dynamic';

export const generateMetadata = async ({ params }: Params): Promise<Metadata> => {
  const { code } = await params;
  return { title: code };
};

const FeedDetailPage = async ({ params }: Params) => {
  const { code } = await params;
  const feed = await getFeedByCode(code);
  if (!feed) notFound();

  const vendor = vendorByLabel(feed.vendorName) ?? vendorForFeedCode(feed.code);
  const authConfig = (feed.authConfig ?? {}) as Record<string, unknown>;

  return (
    <div className="flex flex-col gap-8">
      <div>
        <Link className="text-sm text-accent hover:underline" href="/ops/feeds">
          ← Feeds
        </Link>
        <div className="mt-1 flex items-center gap-3">
          <h1 className="text-xl font-semibold tracking-tight">{feed.vendorName}</h1>
          {feed.isActive ? <Badge tone="ok">active</Badge> : <Badge>paused</Badge>}
        </div>
        <p className="text-sm text-ink-muted">
          <code className="text-xs">{feed.code}</code> · {feed.name}
        </p>
      </div>

      <DryRunPanel
        action={runFeedDryRun}
        code={feed.code}
        dryRunNote={vendor?.dryRunNote}
        dryRunSupported={vendor?.dryRunSupported ?? false}
      />

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold">Configuration</h2>
        <FeedForm
          action={updateFeed}
          initial={{
            code: feed.code,
            name: feed.name,
            vendorSlug: vendor?.slug ?? '',
            baseUrl: feed.baseUrl,
            authConfig,
          }}
          mode="edit"
        />
        <form action={toggleFeedActive}>
          <input name="code" type="hidden" value={feed.code} />
          <input name="active" type="hidden" value={String(!feed.isActive)} />
          <Button type="submit" variant={feed.isActive ? 'danger' : 'secondary'}>
            {feed.isActive ? 'Pause feed' : 'Activate feed'}
          </Button>
        </form>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold">Import history</h2>
        <JobHistory feedSourceId={feed.id} />
      </section>
    </div>
  );
};

export default FeedDetailPage;
