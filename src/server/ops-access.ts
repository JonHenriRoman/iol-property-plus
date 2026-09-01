import 'server-only';

import { serverEnv } from '@/server/env';

/**
 * Gate for the internal `/ops` feed-operations UI.
 *
 * There is no user authentication in this app yet. Until there is, `/ops` is
 * available only in local development, or in a deployed environment that has
 * *explicitly* opted in with `OPS_UI_ENABLED` — and the intent is that such an
 * environment also sits behind network controls or a reverse-proxy auth check.
 *
 * This function is the single seam where a real auth check (session lookup,
 * role assertion) attaches later: the `/ops` layout calls it and 404s when it
 * returns false. Nothing else in the app should reference `OPS_UI_ENABLED`.
 */
const isOpsUiEnabled = (): boolean => {
  if (serverEnv.APP_ENV === 'development') return true;
  return serverEnv.OPS_UI_ENABLED != null;
};

export { isOpsUiEnabled };
