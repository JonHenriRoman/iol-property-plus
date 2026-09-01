import type { Metadata } from 'next';

import Link from 'next/link';

import FeedForm from '@/features/feed-importer/components/feed-form';
import { createFeed } from '@/features/feed-importer/server/actions';

export const metadata: Metadata = { title: 'Add feed' };

const NewFeedPage = () => {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link className="text-sm text-accent hover:underline" href="/ops/feeds">
          ← Feeds
        </Link>
        <h1 className="mt-1 text-xl font-semibold tracking-tight">Add feed</h1>
        <p className="text-sm text-ink-muted">
          Pick a vendor, give the feed a code and the identity details it needs. Then test it.
        </p>
      </div>
      <FeedForm action={createFeed} mode="create" />
    </div>
  );
};

export default NewFeedPage;
