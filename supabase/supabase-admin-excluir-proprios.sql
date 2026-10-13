-- Libera o perfil Administrativo para excluir os processos que ELE MESMO cadastrou (created_by = usuário atual).
-- A Superintendente continua podendo excluir qualquer processo.
-- Rode este arquivo INTEIRO de uma vez no SQL Editor do Supabase.

begin;

drop policy if exists processes_delete on public.processes;
create policy processes_delete on public.processes for delete to authenticated
  using (
    public.current_user_role() = 'superintendente'
    or (public.current_user_role() = 'administrativo' and created_by = auth.uid())
  );

commit;
