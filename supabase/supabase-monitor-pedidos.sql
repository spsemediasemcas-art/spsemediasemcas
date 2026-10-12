-- Fila de "Verificar agora": o site grava o pedido, o monitor SEI (PC 1) executa e grava o resultado.
-- Rode este arquivo INTEIRO de uma vez no SQL Editor do Supabase.

begin;

-- 1) Pedidos de verificação
create table if not exists public.monitor_pedidos (
  id uuid primary key default gen_random_uuid(),
  process_id text not null references public.processes(id) on delete cascade,
  sei_number text not null default '',
  status text not null default 'pendente'
    check (status in ('pendente','rodando','concluido','erro','nao_monitorado')),
  requested_by uuid default auth.uid(),
  requested_by_name text not null default '',
  mensagem text not null default '',
  novidades integer not null default 0,
  criado_em timestamptz not null default now(),
  iniciado_em timestamptz,
  finalizado_em timestamptz
);

create index if not exists monitor_pedidos_status_idx on public.monitor_pedidos (status, criado_em);
create index if not exists monitor_pedidos_processo_idx on public.monitor_pedidos (process_id, criado_em desc);

alter table public.monitor_pedidos enable row level security;

drop policy if exists monitor_pedidos_read on public.monitor_pedidos;
create policy monitor_pedidos_read on public.monitor_pedidos for select to authenticated
  using (public.current_user_role() = any (array['superintendente','administrativo','tecnica']));

drop policy if exists monitor_pedidos_insert on public.monitor_pedidos;
create policy monitor_pedidos_insert on public.monitor_pedidos for insert to authenticated
  with check (public.current_user_role() = any (array['superintendente','administrativo','tecnica'])
              and requested_by = auth.uid());

-- O monitor entra com uma conta do sistema e atualiza o andamento do pedido.
drop policy if exists monitor_pedidos_update on public.monitor_pedidos;
create policy monitor_pedidos_update on public.monitor_pedidos for update to authenticated
  using (public.current_user_role() = any (array['superintendente','administrativo','tecnica']))
  with check (public.current_user_role() = any (array['superintendente','administrativo','tecnica']));

-- 2) Sinal de vida do monitor (o site mostra se o PC 1 está ligado)
create table if not exists public.monitor_status (
  id text primary key,
  ultimo_sinal timestamptz not null default now(),
  processos_monitorados integer not null default 0,
  ultima_rodada text not null default ''
);

alter table public.monitor_status enable row level security;

drop policy if exists monitor_status_read on public.monitor_status;
create policy monitor_status_read on public.monitor_status for select to authenticated
  using (public.current_user_role() = any (array['superintendente','administrativo','tecnica']));

drop policy if exists monitor_status_write on public.monitor_status;
create policy monitor_status_write on public.monitor_status for insert to authenticated
  with check (public.current_user_role() = any (array['superintendente','administrativo','tecnica']));

drop policy if exists monitor_status_update on public.monitor_status;
create policy monitor_status_update on public.monitor_status for update to authenticated
  using (public.current_user_role() = any (array['superintendente','administrativo','tecnica']))
  with check (public.current_user_role() = any (array['superintendente','administrativo','tecnica']));

commit;

-- Conferência: deve listar as duas tabelas novas com as regras.
select tablename, policyname, cmd from pg_policies
where schemaname = 'public' and tablename in ('monitor_pedidos','monitor_status') order by tablename, cmd;
