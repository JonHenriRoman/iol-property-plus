import 'server-only';
import { desc, eq } from 'drizzle-orm';

import { db, schema } from '@/server/db';

/**
 * Read models for the feed-operations UI.
 *
 * TODO(migrations 002/003 + `pnpm db:pull`): once applied, `feed_sources` gains
 * `ttl_days` (replacing `ttl_minutes`) and `import_jobs` gains `records_skipped`
 * / `error_message`. Surface them here then.
 */

const { feedSources, importJobs, importErrors } = schema;

type FeedRow = typeof feedSources.$inferSelect;
type JobRow = typeof importJobs.$inferSelect;
type ErrorRow = typeof importErrors.$inferSelect;

type FeedWithLastJob = FeedRow & { lastJob: JobRow | null };

const listFeeds = async (): Promise<FeedWithLastJob[]> => {
  const feeds = await db
    .select()
    .from(feedSources)
    .orderBy(feedSources.vendorName, feedSources.code);
  if (feeds.length === 0) return [];

  const jobs = await db.select().from(importJobs).orderBy(desc(importJobs.startedAt));
  const lastByFeed = new Map<number, JobRow>();
  for (const job of jobs) {
    if (!lastByFeed.has(job.feedSourceId)) lastByFeed.set(job.feedSourceId, job);
  }

  return feeds.map((feed) => ({ ...feed, lastJob: lastByFeed.get(feed.id) ?? null }));
};

const getFeedByCode = async (code: string): Promise<FeedRow | null> => {
  const [feed] = await db.select().from(feedSources).where(eq(feedSources.code, code)).limit(1);
  return feed ?? null;
};

const getRecentJobs = async (feedSourceId: number, limit = 20): Promise<JobRow[]> => {
  return db
    .select()
    .from(importJobs)
    .where(eq(importJobs.feedSourceId, feedSourceId))
    .orderBy(desc(importJobs.startedAt))
    .limit(limit);
};

const getJobErrors = async (jobId: bigint, limit = 200): Promise<ErrorRow[]> => {
  return db
    .select()
    .from(importErrors)
    .where(eq(importErrors.importJobId, Number(jobId)))
    .orderBy(desc(importErrors.occurredAt))
    .limit(limit);
};

export { getFeedByCode, getJobErrors, getRecentJobs, listFeeds };
export type { ErrorRow, FeedRow, FeedWithLastJob, JobRow };
