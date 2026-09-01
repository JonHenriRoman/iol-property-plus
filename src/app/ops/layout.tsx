import type { Metadata } from 'next';

import Link from 'next/link';
import { notFound } from 'next/navigation';

import { isOpsUiEnabled } from '@/server/ops-access';

export const metadata: Metadata = {
  title: {
    default: 'Operations',
    template: '%s | Operations',
  },
  robots: { index: false, follow: false },
};

// Never prerender /ops: the access gate below must run on every request so a
// production build can ship with the section dark.
export const dynamic = 'force-dynamic';

const OpsLayout = ({ children }: { children: React.ReactNode }) => {
  // The auth seam: today this is an env gate; a session/role check slots in here
  // without touching any page. When it fails, /ops does not exist.
  if (!isOpsUiEnabled()) notFound();

  return (
    <div className="min-h-screen bg-canvas text-ink">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-5xl items-center gap-4 px-6 py-3">
          <Link className="text-sm font-semibold tracking-tight" href="/ops/feeds">
            Property Plus · Operations
          </Link>
          <nav className="flex gap-3 text-sm text-ink-muted">
            <Link className="hover:text-ink" href="/ops/feeds">
              Feeds
            </Link>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-6 py-8">{children}</main>
    </div>
  );
};

export default OpsLayout;
