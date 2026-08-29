import { siteConfig } from '@/config/site';
import { getReleaseInfo } from '@/server/release-info';

const Hero = () => {
  const release = getReleaseInfo();

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-4 px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">{siteConfig.name}</h1>
      <p className="text-base text-neutral-600 dark:text-neutral-400">
        Project skeleton scaffolded per the Corporate Web Architecture Standard.
      </p>
      <p className="text-xs text-neutral-400 dark:text-neutral-600">
        {release.environment} · {release.commitSha}
      </p>
    </main>
  );
};

export default Hero;
