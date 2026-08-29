import 'server-only';

import { serverEnv } from './env';

/**
 * Deploy identity for the running instance.
 *
 * Scaffold-time affordance. §9 requires the pipeline to publish build metadata
 * (commit SHA, pipeline id, image digest) and §8 requires a one-to-one mapping
 * between commit SHA, image tag and task-definition revision.
 */

export interface ReleaseInfo {
  commitSha: string;
  environment: string;
}

export function getReleaseInfo(): ReleaseInfo {
  return {
    commitSha: serverEnv.GIT_COMMIT_SHA,
    environment: serverEnv.APP_ENV,
  };
}
