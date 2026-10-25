-- Resources from the Connections Guide (README section 8, "Suggested normalized fields").
-- Apply with: supabase db push   (or paste into the dashboard SQL Editor).

create table public.resources (
  id bigint generated always as identity primary key,
  organization_name text not null,
  service_categories text[] not null default '{}',
  description text,
  street_address text,
  borough text,
  neighborhood text,
  latitude double precision,
  longitude double precision,
  phone text,
  website text,
  hours text,
  eligibility text,
  referral_process text,
  languages text,
  accessibility_notes text,
  -- Hotlines and other resources with no physical location (README section 7.7).
  is_hotline boolean not null default false,
  last_verified date,
  source text
);

create index resources_borough_idx on public.resources (borough);
create index resources_service_categories_idx on public.resources using gin (service_categories);

-- The publishable key ships in the browser, so RLS decides what it can do.
-- Anyone can read; nobody can insert, update or delete through the Data API.
-- Edit rows in the dashboard Table Editor, which uses an admin role.
alter table public.resources enable row level security;

create policy "Resources are publicly readable"
  on public.resources
  for select
  to anon, authenticated
  using (true);

grant select on public.resources to anon, authenticated;
