import 'server-only';

/**
 * Deploy identity for the running instance.
 *
 * Scaffold-time affordance. §9 requires the pipeline to publish build metadata
 * (commit SHA, pipeline id, image digest) and §8 requires a one-to-one mapping
 * between commit SHA, image tag and task-definition revision. Once the pipeline
 * injects these, this module can be replaced by the §6 env schema.
 */

export interface ReleaseInfo {
  commitSha: string;
  environment: string;
}

export function getReleaseInfo(): ReleaseInfo {
  return {
    commitSha: process.env.GIT_COMMIT_SHA ?? 'dev',
    environment: process.env.APP_ENV ?? 'development',
  };
}
