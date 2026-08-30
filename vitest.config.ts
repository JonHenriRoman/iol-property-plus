import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

const r = (p: string) => fileURLToPath(new URL(p, import.meta.url));

// `@/*` aliases mirror tsconfig.json. `server-only` resolves to an empty stub so
// server modules (which open with `import 'server-only'`) load under plain Node.
const alias = {
  'server-only': r('./tests/helpers/server-only-stub.ts'),
  '@/assets': r('./src/assets'),
  '@/components': r('./src/components'),
  '@/config': r('./src/config'),
  '@/features': r('./src/features'),
  '@/lib': r('./src/lib'),
  '@/server': r('./src/server'),
  '@/styles': r('./src/styles'),
  '@/types': r('./src/types'),
};

export default defineConfig({
  test: {
    setupFiles: ['./tests/helpers/no-network.ts'],
    projects: [
      {
        resolve: { alias },
        test: {
          name: 'unit',
          environment: 'node',
          include: ['tests/unit/**/*.test.ts'],
          setupFiles: ['./tests/helpers/no-network.ts'],
        },
      },
      {
        resolve: { alias },
        test: {
          name: 'integration',
          environment: 'node',
          include: ['tests/integration/**/*.test.ts'],
          setupFiles: ['./tests/helpers/no-network.ts'],
        },
      },
    ],
  },
});
