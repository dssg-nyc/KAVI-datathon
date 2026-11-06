// Lints the loader's TS test (supabase/__tests__/). The pipeline is Python and is linted by ruff. Existing files are not edited to satisfy it.
import js from '@eslint/js';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.recommended,
);
