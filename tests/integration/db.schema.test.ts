import { eq } from 'drizzle-orm';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { cities, propertyTypes, provinces } from '@/server/db/schema';

import { createTestDb, seedReferenceData, type TestDb } from '../helpers/test-db';

let db: TestDb;

beforeEach(async () => {
  db = await createTestDb();
});

afterEach(async () => {
  await db.$client.close();
});

describe('generated Drizzle schema against a real Postgres engine', () => {
  it('round-trips seeded reference rows', async () => {
    await seedReferenceData(db);
    const rows = await db.select().from(provinces).orderBy(provinces.name);
    expect(rows.map((r) => r.code)).toEqual(['GP', 'WC']);
    expect(rows[0]?.countryCode).toBe('ZA'); // char(2) DEFAULT 'ZA'
  });

  it('enforces the cities → provinces foreign key', async () => {
    await seedReferenceData(db);
    const [wc] = await db.select().from(provinces).where(eq(provinces.code, 'WC'));

    await db.insert(cities).values({ provinceId: wc!.id, name: 'Cape Town', slug: 'cape-town' });
    const found = await db.select().from(cities);
    expect(found).toHaveLength(1);

    await expect(
      db.insert(cities).values({ provinceId: 999_999, name: 'Nowhere', slug: 'nowhere' }),
    ).rejects.toThrow();
  });

  it('enforces the property_types category check constraint', async () => {
    await expect(
      db.insert(propertyTypes).values({ name: 'Bad', slug: 'bad', category: 'Spaceship' }),
    ).rejects.toThrow();
  });
});
