-- SOLVI: esquema mínimo y políticas de seguridad para apuntes.
-- Ejecutar en Supabase antes de activar SUPABASE_URL/SUPABASE_KEY en Render.

create extension if not exists pgcrypto;

create table if not exists public.notes (
    id uuid primary key default gen_random_uuid(),
    title text not null check (char_length(title) between 1 and 200),
    text text not null default '' check (char_length(text) <= 20000),
    tags jsonb not null default '[]'::jsonb check (jsonb_typeof(tags) = 'array'),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists notes_created_at_idx on public.notes (created_at desc);

alter table public.notes enable row level security;
alter table public.notes force row level security;

-- El navegador nunca accede directamente a Supabase: solo la API Flask con
-- una clave service_role guardada en Render. anon/authenticated no tienen CRUD.
revoke all on table public.notes from anon, authenticated;
grant all on table public.notes to service_role;

drop policy if exists "notes_no_anon_access" on public.notes;
create policy "notes_no_anon_access"
    on public.notes
    for all
    to anon, authenticated
    using (false)
    with check (false);

create or replace function public.set_notes_updated_at()
returns trigger
language plpgsql
security invoker
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists notes_set_updated_at on public.notes;
create trigger notes_set_updated_at
before update on public.notes
for each row execute function public.set_notes_updated_at();
