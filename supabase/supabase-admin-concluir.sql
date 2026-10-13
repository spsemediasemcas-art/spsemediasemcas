-- Libera o perfil Administrativo para concluir, responder e reabrir processos.
-- Antes, a trigger proteger_conclusao recusava essas mudanças para quem não era Superintendente.
-- A exclusão de processos continua somente com a Superintendente (regra processes_delete, não alterada aqui).
-- Rode este arquivo INTEIRO de uma vez no SQL Editor do Supabase.

begin;

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

commit;
