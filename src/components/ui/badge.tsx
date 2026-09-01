import type { ReactNode } from 'react';

type Tone = 'neutral' | 'ok' | 'warn' | 'danger' | 'accent';

const tones: Record<Tone, string> = {
  neutral: 'border-line bg-surface text-ink-muted',
  ok: 'border-ok/40 bg-ok/10 text-ok',
  warn: 'border-warn/40 bg-warn/10 text-warn',
  danger: 'border-danger/40 bg-danger/10 text-danger',
  accent: 'border-accent/40 bg-accent/10 text-accent',
};

const Badge = ({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) => {
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-xs font-medium ${tones[tone]}`}
    >
      {children}
    </span>
  );
};

export default Badge;
export type { Tone };
