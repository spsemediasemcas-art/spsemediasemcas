-- Administrativo conclui, responde e reabre QUALQUER processo (não só os que cadastrou).
-- O supabase-admin-concluir.sql de 13/10 só corrigiu a trigger; a regra de UPDATE do banco
-- (migration 20261009_permissions) ainda recusava a gravação quando o processo virava
-- "respondido"/"concluído" ou não tinha sido cadastrado pelo próprio usuário.
-- A exclusão continua como está: Superintendente exclui qualquer um; Administrativo, só os que cadastrou.
-- Rode este arquivo INTEIRO de uma vez no SQL Editor do Supabase.

begin;

-- 1) Edição: Superintendente e Administrativo alteram qualquer processo, em qualquer situação.
drop policy if exists processes_update on public.processes;
create policy processes_update on public.processes for update to authenticated
  using (public.current_user_role() = any (array['superintendente','administrativo']))
  with check (public.current_user_role() = any (array['superintendente','administrativo']));

-- 2) Cadastro: o Administrativo pode cadastrar já respondido/concluído (sempre em nome dele mesmo).
drop policy if exists processes_insert on public.processes;
create policy processes_insert on public.processes for insert to authenticated
  with check (
    public.current_user_role() = 'superintendente'
    or (public.current_user_role() = 'administrativo' and created_by = auth.uid())
  );

-- 3) Trava de conclusão: libera os dois perfis (mantida só para barrar quem não tem perfil válido).
create or replace function public.proteger_conclusao() returns trigger
language plpgsql set search_path = public as $$
begin
  if auth.uid() is null
     or coalesce(public.current_user_role(), '') = any (array['superintendente','administrativo']) then
    return new;
  end if;
  if new.status is distinct from old.status
     or (coalesce(new.marking, '') = 'concluido') <> (coalesce(old.marking, '') = 'concluido')
     or (coalesce(new.stage, 0) = 5) <> (coalesce(old.stage, 0) = 5) then
    raise exception 'Somente a Superintendente ou o Administrativo podem concluir, responder ou reabrir um processo.';
  end if;
  return new;
end $$;

drop trigger if exists proteger_conclusao on public.processes;
create trigger proteger_conclusao before update on public.processes
  for each row execute function public.proteger_conclusao();

commit;

notify pgrst, 'reload schema';

-- Conferência 1: as duas linhas devem citar 'administrativo' SEM "created_by" no UPDATE.
select policyname, cmd, qual, with_check from pg_policies
where schemaname = 'public' and tablename = 'processes' and cmd in ('UPDATE','INSERT') order by cmd;

-- Conferência 2: triggers da tabela processes (só deve haver proteger_conclusao como trava de perfil).
select tgname, pg_get_triggerdef(oid) from pg_trigger
where tgrelid = 'public.processes'::regclass and not tgisinternal;

-- Conferência 3: perfis dos usuários (todo mundo que não é Superintendente precisa estar 'administrativo' e ativo).
select display_name, email, role, active from public.user_profiles order by role, display_name;
