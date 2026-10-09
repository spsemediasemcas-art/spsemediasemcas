alter table public.user_profiles drop constraint if exists user_profiles_role_check;
alter table public.user_profiles
  add constraint user_profiles_role_check
  check (role in ('superintendente', 'administrativo'));

update public.user_profiles
set role = 'administrativo', updated_at = now()
where role = 'tecnica';

alter table public.processes
  add column if not exists created_by uuid references auth.users(id) on delete set null;
alter table public.processes
  add column if not exists updated_by uuid references auth.users(id) on delete set null;

create index if not exists processes_created_by_idx on public.processes(created_by);
create index if not exists process_comments_author_user_idx on public.process_comments(author_user_id);

grant select on table public.user_profiles to authenticated;
grant select on table public.services to authenticated;
grant select, insert, update, delete on table public.processes to authenticated;
grant select, insert, update, delete on table public.process_comments to authenticated;
grant select, insert on table public.process_audit_log to authenticated;

drop policy if exists processes_insert on public.processes;
create policy processes_insert on public.processes
for insert to authenticated
with check (
  public.current_user_role() = 'superintendente'
  or (
    public.current_user_role() = 'administrativo'
    and created_by = auth.uid()
    and status = 'pendente'
    and coalesce(marking, '') <> 'concluido'
  )
);

drop policy if exists processes_update on public.processes;
create policy processes_update on public.processes
for update to authenticated
using (
  public.current_user_role() = 'superintendente'
  or (public.current_user_role() = 'administrativo' and created_by = auth.uid())
)
with check (
  public.current_user_role() = 'superintendente'
  or (
    public.current_user_role() = 'administrativo'
    and created_by = auth.uid()
    and status = 'pendente'
    and coalesce(marking, '') <> 'concluido'
  )
);

drop policy if exists processes_delete on public.processes;
create policy processes_delete on public.processes
for delete to authenticated
using (
  public.current_user_role() = 'superintendente'
  or (public.current_user_role() = 'administrativo' and created_by = auth.uid())
);

drop policy if exists comments_insert on public.process_comments;
create policy comments_insert on public.process_comments
for insert to authenticated
with check (
  public.current_user_role() in ('superintendente', 'administrativo')
  and author_user_id = auth.uid()
);

drop policy if exists comments_update on public.process_comments;
create policy comments_update on public.process_comments
for update to authenticated
using (
  public.current_user_role() = 'superintendente'
  or (public.current_user_role() = 'administrativo' and author_user_id = auth.uid())
)
with check (
  public.current_user_role() = 'superintendente'
  or (public.current_user_role() = 'administrativo' and author_user_id = auth.uid())
);

drop policy if exists comments_delete on public.process_comments;
create policy comments_delete on public.process_comments
for delete to authenticated
using (
  public.current_user_role() = 'superintendente'
  or (public.current_user_role() = 'administrativo' and author_user_id = auth.uid())
);

drop policy if exists audit_insert on public.process_audit_log;
create policy audit_insert on public.process_audit_log
for insert to authenticated
with check (
  public.current_user_role() in ('superintendente', 'administrativo')
  and author_user_id = auth.uid()
);

notify pgrst, 'reload schema';

