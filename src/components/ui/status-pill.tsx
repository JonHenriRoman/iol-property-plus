import Badge, { type Tone } from '@/components/ui/badge';

/** Maps an `import_job_status` value to a badge tone. */
const toneByStatus: Record<string, Tone> = {
  Pending: 'neutral',
  Running: 'accent',
  Success: 'ok',
  PartialSuccess: 'warn',
  Failed: 'danger',
};

const StatusPill = ({ status }: { status: string }) => {
  return <Badge tone={toneByStatus[status] ?? 'neutral'}>{status}</Badge>;
};

export default StatusPill;
