create extension if not exists pgcrypto;

create table if not exists public.licenses (
  id uuid primary key default gen_random_uuid(),
  key_hash text not null unique,
  key_last4 text not null,
  status text not null default 'active' check (status in ('active','revoked','expired')),
  max_devices integer not null default 1 check (max_devices between 1 and 25),
  expires_at timestamptz,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  revoked_at timestamptz
);

create table if not exists public.license_activations (
  id uuid primary key default gen_random_uuid(),
  license_id uuid not null references public.licenses(id) on delete cascade,
  device_hash text not null,
  device_label text,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  active boolean not null default true,
  unique (license_id, device_hash)
);

create index if not exists idx_license_activations_license on public.license_activations(license_id);
create index if not exists idx_license_activations_device on public.license_activations(device_hash);

alter table public.licenses enable row level security;
alter table public.license_activations enable row level security;
revoke all on public.licenses from anon, authenticated;
revoke all on public.license_activations from anon, authenticated;

create or replace function public.touch_license_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;

drop trigger if exists licenses_updated_at on public.licenses;
create trigger licenses_updated_at before update on public.licenses
for each row execute function public.touch_license_updated_at();
