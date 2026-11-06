// Lints the Supabase loader and its test (supabase/). The pipeline is Python and is linted by ruff.
import js from '@eslint/js';

export default [
  js.configs.recommended,
  {
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: { console: 'readonly', process: 'readonly', fetch: 'readonly', URL: 'readonly', URLSearchParams: 'readonly', Headers: 'readonly', AbortController: 'readonly', setTimeout: 'readonly', clearTimeout: 'readonly', TextDecoder: 'readonly' },
    },
    // Existing files are not edited to satisfy the linter; link_env.mjs uses an empty catch on purpose (a missing file is not an error).
    rules: { 'no-empty': ['error', { allowEmptyCatch: true }] },
  },
];
