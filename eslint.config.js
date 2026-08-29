import nextVitals from 'eslint-config-next/core-web-vitals';
import nextTs from 'eslint-config-next/typescript';
import prettier from 'eslint-config-prettier/flat';
import importX from 'eslint-plugin-import-x';
import perfectionist from 'eslint-plugin-perfectionist';
import unusedImports from 'eslint-plugin-unused-imports';
import { defineConfig, globalIgnores } from 'eslint/config';

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    plugins: {
      'import-x': importX,
      perfectionist,
      'unused-imports': unusedImports,
    },
    rules: {
      'import-x/first': 'error',
      'import-x/newline-after-import': ['error', { count: 1 }],
      'perfectionist/sort-imports': [
        'error',
        {
          internalPattern: ['@/.*'],
          order: 'asc',
          type: 'natural',
        },
      ],
      'perfectionist/sort-named-imports': 'error',
      'perfectionist/sort-named-exports': 'error',
      'perfectionist/sort-variable-declarations': 'off',
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': 'off',
      'unused-imports/no-unused-imports': 'error',
      'unused-imports/no-unused-vars': [
        'warn',
        {
          args: 'after-used',
          argsIgnorePattern: '^_',
          ignoreRestSiblings: true,
          vars: 'all',
          varsIgnorePattern: '^_',
        },
      ],
      'no-debugger': 'error',
      'prefer-const': 'error',
    },
  },
  prettier,
  globalIgnores(['.next/**', 'coverage/**', 'dist/**', 'node_modules/**', 'out/**']),
]);
