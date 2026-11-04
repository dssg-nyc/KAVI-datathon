// Lints new TS tooling (pipeline/6_build, the loader's tests) plus the OSM script. Existing files are not edited to satisfy it.
import js from '@eslint/js';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.recommended,
);
