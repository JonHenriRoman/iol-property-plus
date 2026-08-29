import Link from 'next/link';

const NotFound = () => {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-4 px-6 py-16">
      <h1 className="text-2xl font-semibold tracking-tight">Page not found</h1>
      <p className="text-base text-neutral-600 dark:text-neutral-400">
        The page you are looking for does not exist.
      </p>
      <Link className="text-sm underline underline-offset-4" href="/">
        Return home
      </Link>
    </main>
  );
};

export default NotFound;
