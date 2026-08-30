// Fails any test that makes a real outbound HTTP call. Loopback is allowed so a
// future test can talk to an in-process server; everything else throws.

const realFetch = globalThis.fetch;

const isLoopback = (url: string): boolean => {
  try {
    const { hostname } = new URL(url);
    return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1';
  } catch {
    return false;
  }
};

globalThis.fetch = ((
  input: Parameters<typeof realFetch>[0],
  init?: Parameters<typeof realFetch>[1],
) => {
  const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
  if (!isLoopback(url)) {
    throw new Error(`Blocked network call in a deterministic test: ${url}`);
  }
  return realFetch(input, init);
}) as typeof realFetch;
