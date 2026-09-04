// ESLint flat config.
// Goal: catch real bugs (react-hooks rules, type-unsafe patterns) without
// drowning in style noise. `react-hooks/exhaustive-deps` is warn because the
// codebase has many pre-existing violations; it should be tightened to error
// once the existing warnings are addressed (ratchet).
import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';

export default tseslint.config(
  {
    ignores: [
      'node_modules/**',
      'dist/**',
      '../../web/generated/**',
      '**/*.test.ts',
      '**/*.test.tsx',
      'happydom.ts',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      globals: { ...globals.browser, ...globals.es2022 },
    },
    plugins: {
      'react-hooks': reactHooks,
    },
    rules: {
      // Correctness-focused rules
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrors: 'none',
        },
      ],
      'no-empty': ['warn', { allowEmptyCatch: true }],
      'no-constant-condition': ['warn', { checkLoops: false }],
    },
  },
  {
    // Debug tooling legitimately wraps console.
    files: ['src/utils/debugLog.ts'],
    rules: { 'no-console': 'off' },
  },
);