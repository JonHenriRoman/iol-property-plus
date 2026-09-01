import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createTestDb, type TestDb } from '../helpers/test-db';

const hoisted = vi.hoisted(() => ({ db: null as unknown }));

vi.mock('@/server/db', async () => {
  const schema = await vi.importActual('@/server/db/schema');
  return {
    get db() {
      return hoisted.db;
    },
    schema,
  };
});

vi.mock('next/cache', () => ({ revalidatePath: vi.fn() }));
vi.mock('next/navigation', () => ({
  redirect: (url: string) => {
    throw new Error(`REDIRECT:${url}`);
  },
}));

const { createFeed, toggleFeedActive, updateFeed } =
  await import('@/features/feed-importer/server/actions');
const { getFeedByCode, getRecentJobs, listFeeds } =
  await import('@/features/feed-importer/server/queries');
const schema = await import('@/server/db/schema');

let db: TestDb;

beforeEach(async () => {
  db = await createTestDb();
  hoisted.db = db;
});

afterEach(async () => {
  await db.$client.close();
});

const form = (fields: Record<string, string>): FormData => {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.set(k, v);
  return fd;
};

describe('feed-importer server actions', () => {
  it('creates a feed and redirects to its detail page', async () => {
    await expect(
      createFeed(
        { ok: false },
        form({
          vendor: 'allsa',
          code: 'allsa-10173',
          name: 'National Real Estate',
          agency_id: '10173',
          isActive: 'on',
        }),
      ),
    ).rejects.toThrow('REDIRECT:/ops/feeds/allsa-10173');

    const row = await getFeedByCode('allsa-10173');
    expect(row).toMatchObject({
      code: 'allsa-10173',
      vendorName: 'AllSA Property',
      format: 'XML',
      isActive: true,
      authConfig: { agency_id: '10173' },
    });
  });

  it('rejects a duplicate code', async () => {
    const fields = {
      vendor: 'allsa',
      code: 'allsa-1',
      name: 'A',
      agency_id: '1',
      isActive: 'on',
    };
    await expect(createFeed({ ok: false }, form(fields))).rejects.toThrow('REDIRECT');
    const second = await createFeed({ ok: false }, form(fields));
    expect(second.ok).toBe(false);
    expect(second.fieldErrors?.code).toMatch(/already exists/i);
  });

  it('rejects an invalid payload without writing', async () => {
    const result = await createFeed(
      { ok: false },
      form({ vendor: 'allsa', code: 'allsa-2', name: 'B', agency_id: '' }),
    );
    expect(result.ok).toBe(false);
    expect(result.fieldErrors?.agency_id).toBeTruthy();
    expect(await listFeeds()).toHaveLength(0);
  });

  it('updates an existing feed', async () => {
    await expect(
      createFeed(
        { ok: false },
        form({
          vendor: 'rt3',
          code: 'rt3-rawson',
          name: 'Rawson',
          provinces: 'Gauteng',
          isActive: 'on',
        }),
      ),
    ).rejects.toThrow('REDIRECT');

    const result = await updateFeed(
      { ok: false },
      form({
        vendor: 'rt3',
        code: 'rt3-rawson',
        name: 'Rawson Properties',
        provinces: 'Gauteng, Western_Cape',
        isActive: 'on',
      }),
    );
    expect(result.ok).toBe(true);

    const row = await getFeedByCode('rt3-rawson');
    expect(row?.name).toBe('Rawson Properties');
    expect(row?.authConfig).toEqual({ provinces: ['Gauteng', 'Western_Cape'] });
  });

  it('toggles is_active', async () => {
    await expect(
      createFeed(
        { ok: false },
        form({ vendor: 'fusion', code: 'fusion-main', name: 'Fusion', isActive: 'on' }),
      ),
    ).rejects.toThrow('REDIRECT');

    await toggleFeedActive(form({ code: 'fusion-main', active: 'false' }));
    expect((await getFeedByCode('fusion-main'))?.isActive).toBe(false);

    await toggleFeedActive(form({ code: 'fusion-main', active: 'true' }));
    expect((await getFeedByCode('fusion-main'))?.isActive).toBe(true);
  });

  it('lists feeds with their most recent job', async () => {
    await expect(
      createFeed(
        { ok: false },
        form({ vendor: 'allsa', code: 'allsa-9', name: 'Nine', agency_id: '9', isActive: 'on' }),
      ),
    ).rejects.toThrow('REDIRECT');

    const feed = await getFeedByCode('allsa-9');
    await db.insert(schema.importJobs).values([
      {
        feedSourceId: feed!.id,
        status: 'Success',
        recordsInserted: 5,
        startedAt: '2026-01-01T00:00:00Z',
        finishedAt: '2026-01-01T00:01:00Z',
      },
      {
        feedSourceId: feed!.id,
        status: 'Failed',
        recordsFailed: 2,
        startedAt: '2026-02-01T00:00:00Z',
        finishedAt: '2026-02-01T00:01:00Z',
      },
    ]);

    const feeds = await listFeeds();
    expect(feeds).toHaveLength(1);
    expect(feeds[0]?.lastJob?.status).toBe('Failed');

    const jobs = await getRecentJobs(feed!.id);
    expect(jobs.map((j) => j.status)).toEqual(['Failed', 'Success']);
  });
});
