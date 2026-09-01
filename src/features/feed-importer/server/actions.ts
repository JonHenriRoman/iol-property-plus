'use server';

import { eq } from 'drizzle-orm';
import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';

import { parseFeedForm } from '@/features/feed-importer/schema';
import { vendorByLabel, vendorForFeedCode } from '@/lib/feed-vendors';
import { db, schema } from '@/server/db';
import { type DryRunOutcome, runDryRun } from '@/server/importer/run-dry-run';
import { isOpsUiEnabled } from '@/server/ops-access';

const { feedSources } = schema;

type FormState = { ok: boolean; message?: string; fieldErrors?: Record<string, string> };
type DryRunState = { ran: boolean; outcome?: DryRunOutcome };

const readFields = (formData: FormData): Record<string, string> => {
  const out: Record<string, string> = {};
  for (const [key, value] of formData.entries()) {
    if (typeof value === 'string') out[key] = value;
  }
  return out;
};

const guard = (): FormState | null =>
  isOpsUiEnabled() ? null : { ok: false, message: 'Feed operations are not available here.' };

const createFeed = async (_prev: FormState, formData: FormData): Promise<FormState> => {
  const blocked = guard();
  if (blocked) return blocked;

  const parsed = parseFeedForm(readFields(formData));
  if (!parsed.ok) return { ok: false, fieldErrors: parsed.fieldErrors };

  const clash = await db
    .select({ id: feedSources.id })
    .from(feedSources)
    .where(eq(feedSources.code, parsed.data.code))
    .limit(1);
  if (clash.length > 0) {
    return { ok: false, fieldErrors: { code: 'A feed with this code already exists.' } };
  }

  await db.insert(feedSources).values({
    code: parsed.data.code,
    name: parsed.data.name,
    vendorName: parsed.data.vendorName,
    format: parsed.data.format,
    baseUrl: parsed.data.baseUrl,
    authConfig: parsed.data.authConfig,
    isActive: true,
  });

  revalidatePath('/ops/feeds');
  redirect(`/ops/feeds/${parsed.data.code}`);
};

const updateFeed = async (_prev: FormState, formData: FormData): Promise<FormState> => {
  const blocked = guard();
  if (blocked) return blocked;

  const parsed = parseFeedForm(readFields(formData));
  if (!parsed.ok) return { ok: false, fieldErrors: parsed.fieldErrors };

  await db
    .update(feedSources)
    .set({
      name: parsed.data.name,
      format: parsed.data.format,
      baseUrl: parsed.data.baseUrl,
      authConfig: parsed.data.authConfig,
      updatedAt: new Date().toISOString(),
    })
    .where(eq(feedSources.code, parsed.data.code));

  revalidatePath('/ops/feeds');
  revalidatePath(`/ops/feeds/${parsed.data.code}`);
  return { ok: true, message: 'Feed saved.' };
};

const toggleFeedActive = async (formData: FormData): Promise<void> => {
  if (!isOpsUiEnabled()) return;

  const code = String(formData.get('code') ?? '');
  const nextActive = formData.get('active') === 'true';
  if (!code) return;

  await db
    .update(feedSources)
    .set({ isActive: nextActive, updatedAt: new Date().toISOString() })
    .where(eq(feedSources.code, code));

  revalidatePath('/ops/feeds');
  revalidatePath(`/ops/feeds/${code}`);
};

const runFeedDryRun = async (_prev: DryRunState, formData: FormData): Promise<DryRunState> => {
  if (!isOpsUiEnabled()) {
    return { ran: true, outcome: { status: 'error', message: 'Not available here.' } };
  }

  const code = String(formData.get('code') ?? '');
  const [feed] = await db
    .select({ vendorName: feedSources.vendorName })
    .from(feedSources)
    .where(eq(feedSources.code, code))
    .limit(1);

  if (!feed) return { ran: true, outcome: { status: 'error', message: 'Feed not found.' } };

  const vendor = vendorByLabel(feed.vendorName) ?? vendorForFeedCode(code);
  if (!vendor) {
    return { ran: true, outcome: { status: 'error', message: 'Could not resolve the vendor.' } };
  }

  const outcome = await runDryRun(vendor.slug, code);
  return { ran: true, outcome };
};

export { createFeed, runFeedDryRun, toggleFeedActive, updateFeed };
export type { DryRunState, FormState };
