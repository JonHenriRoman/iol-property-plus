import 'server-only';

import StatusPill from '@/components/ui/status-pill';
import Table, { Td, Th } from '@/components/ui/table';

import { getJobErrors, getRecentJobs } from '../server/queries';

const formatWhen = (iso: string | null): string =>
  iso ? new Date(iso).toLocaleString('en-ZA', { hour12: false }) : '—';

const duration = (start: string, end: string | null): string => {
  if (!end) return '—';
  const secs = Math.max(0, Math.round((Date.parse(end) - Date.parse(start)) / 1000));
  return `${secs}s`;
};

const JobHistory = async ({ feedSourceId }: { feedSourceId: number }) => {
  const jobs = await getRecentJobs(feedSourceId, 20);

  if (jobs.length === 0) {
    return (
      <p className="rounded-md border border-line bg-surface px-4 py-6 text-center text-sm text-ink-muted">
        No import jobs yet — real runs appear here once the feed is active and the scheduler runs
        it.
      </p>
    );
  }

  const latest = jobs[0]!;
  const latestErrors = latest.recordsFailed > 0 ? await getJobErrors(latest.id) : [];
  const byType = latestErrors.reduce<Record<string, number>>((acc, e) => {
    acc[e.errorType] = (acc[e.errorType] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="flex flex-col gap-3">
      <Table
        head={
          <tr>
            <Th>Started</Th>
            <Th>Status</Th>
            <Th>Duration</Th>
            <Th>Seen</Th>
            <Th>New</Th>
            <Th>Updated</Th>
            <Th>Failed</Th>
          </tr>
        }
      >
        {jobs.map((job) => (
          <tr key={String(job.id)}>
            <Td>
              <span className="text-xs tabular-nums">{formatWhen(job.startedAt)}</span>
            </Td>
            <Td>
              <StatusPill status={job.status} />
            </Td>
            <Td>
              <span className="tabular-nums">{duration(job.startedAt, job.finishedAt)}</span>
            </Td>
            <Td>
              <span className="tabular-nums">{job.recordsSeen}</span>
            </Td>
            <Td>
              <span className="tabular-nums">{job.recordsInserted}</span>
            </Td>
            <Td>
              <span className="tabular-nums">{job.recordsUpdated}</span>
            </Td>
            <Td>
              <span className="tabular-nums">{job.recordsFailed}</span>
            </Td>
          </tr>
        ))}
      </Table>

      {Object.keys(byType).length > 0 ? (
        <div className="rounded-md border border-line bg-surface p-3 text-sm">
          <p className="mb-1 font-medium">Errors in the latest run</p>
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-ink-muted">
            {Object.entries(byType).map(([type, count]) => (
              <li key={type} className="tabular-nums">
                {type}: {count}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
};

export default JobHistory;
