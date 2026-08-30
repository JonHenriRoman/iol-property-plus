// Stub for the `server-only` package under vitest. In a Next build `server-only`
// throws when pulled into a client bundle; under plain Node it would throw
// unconditionally, so tests alias it to this no-op.

export {};
