// Supabase connection for the browser (index.html). Committed on purpose:
// the publishable key can only read public.resources (RLS) and every visitor's browser receives it anyway.
// Never put the secret key (sb_secret_...) here. It belongs in .env, which git ignores.
// RESOURCES_FILE is the data file the finder reads, written by the pipeline (npm run build:data).
// pipeline/5_load/load_supabase.mjs also reads SUPABASE_URL from this file, so keep the object valid JSON.
window.APP_CONFIG = {
  "SUPABASE_URL": "https://xwpuphhocwstfgbjreeg.supabase.co",
  "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_mwAVRHD_00cNdhNA9BKFSQ_QhrEtVDK",
  "RESOURCES_FILE": "data/public/resources.public.json"
};
