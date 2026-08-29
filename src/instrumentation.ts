/**
 * Next.js instrumentation hook.
 *
 * Runs once when the server process starts. Importing the server env schema here
 * forces validation at boot: a misconfigured container exits non-zero before it
 * can pass an ALB health check, so the deployment rolls back.
 */

const register = async (): Promise<void> => {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    await import('@/server/env');
  }
};

export { register };
