'use client';

import { useEffect } from 'react';

const Error = ({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) => {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-4 px-6 py-16">
      <h1 className="text-2xl font-semibold tracking-tight">Something went wrong</h1>
      <p className="text-base text-neutral-600 dark:text-neutral-400">
        An unexpected error occurred. Try again, or contact the site owner if it persists.
      </p>
      <button
        className="w-fit rounded-md border border-neutral-300 px-3 py-1.5 text-sm dark:border-neutral-700"
        onClick={() => reset()}
        type="button"
      >
        Try again
      </button>
    </main>
  );
};

export default Error;
