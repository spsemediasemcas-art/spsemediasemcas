-- Avisos de novidades do SEI: o monitor registra cada documento/andamento novo e o site mostra no botão "Avisos".
-- Rode este arquivo INTEIRO de uma vez no SQL Editor do Supabase.

begin;

-- 1) Novidades encontradas pelo monitor (só o que apareceu depois do cadastro do processo no monitor)
create table if not exists public.monitor_novidades (
  id uuid primary key default gen_random_uuid(),
  process_id text not null references public.processes(id) on delete cascade,
  sei_number text not null default '',
  categoria text not null default 'andamento' check (categoria in ('documento','andamento')),
  descricao text not null default '',
  unidade text not null default '',
  data_sei text not null default '',
  link text not null default '',
  chave text not null default '',
  criado_em timestamptz not null default now(),
  unique (process_id, categoria, chave)
);

create index if not exists monitor_novidades_criado_idx on public.monitor_novidades (criado_em desc);

alter table public.monitor_novidades enable row level security;

drop policy if exists monitor_novidades_read on public.monitor_novidades;
create policy monitor_novidades_read on public.monitor_novidades for select to authenticated
  using (public.current_user_role() = any (array['superintendente','administrativo','tecnica']));

drop policy if exists monitor_novidades_insert on public.monitor_novidades;
create policy monitor_novidades_insert on public.monitor_novidades for insert to authenticated
  with check (public.current_user_role() = any (array['superintendente','administrativo','tecnica']));

-- 2) Até quando cada pessoa já viu os avisos (vale em qualquer computador)
create table if not exists public.monitor_novidades_vistas (
  user_id uuid primary key default auth.uid(),
  visto_em timestamptz not null default now()
);

alter table public.monitor_novidades_vistas enable row level security;

drop policy if exists novidades_vistas_read on public.monitor_novidades_vistas;
create policy novidades_vistas_read on public.monitor_novidades_vistas for select to authenticated
  using (user_id = auth.uid());

drop policy if exists novidades_vistas_insert on public.monitor_novidades_vistas;
create policy novidades_vistas_insert on public.monitor_novidades_vistas for insert to authenticated
  with check (user_id = auth.uid());

drop policy if exists novidades_vistas_update on public.monitor_novidades_vistas;
create policy novidades_vistas_update on public.monitor_novidades_vistas for update to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

commit;

-- Conferência: deve listar as duas tabelas novas com as regras.
select tablename, policyname, cmd from pg_policies
where schemaname = 'public' and tablename in ('monitor_novidades','monitor_novidades_vistas') order by tablename, cmd;
