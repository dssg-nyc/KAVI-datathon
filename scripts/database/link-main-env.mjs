// Makes .env in this git worktree a symlink to the .env of the main checkout, so scripts such as
// import-resources.mjs can read SUPABASE_SECRET_KEY without a second copy of the secret on disk.
// A symlink (not a copy) also means a key rotated in the main checkout takes effect here too.
//
// Usage (from a worktree):
//   node scripts/database/link-main-env.mjs
// Refuses to replace an existing .env, and does nothing when run in the main checkout itself.
import { execFileSync } from 'node:child_process';
import { existsSync, lstatSync, symlinkSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';

const git = (...args) => execFileSync('git', args, { encoding: 'utf8' }).trim();

const here = resolve(git('rev-parse', '--show-toplevel'));
// --git-common-dir is the main checkout's .git directory, shared by every worktree.
const main = dirname(resolve(here, git('rev-parse', '--git-common-dir')));

if (here === main) {
  console.log(`${here} is the main checkout; nothing to link.`);
  process.exit(0);
}

const source = join(main, '.env');
const target = join(here, '.env');

if (!existsSync(source)) {
  console.error(`No .env in the main checkout (${main}). Create it there first: cp .env.example .env`);
  process.exit(1);
}
let targetExists = false;
try {
  lstatSync(target);
  targetExists = true;
} catch {}
if (targetExists) {
  console.error(`${target} already exists; remove it first if you want it linked to ${source}.`);
  process.exit(1);
}

symlinkSync(source, target);
console.log(`Linked ${target} -> ${source}`);
