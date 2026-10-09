create or replace function public.cadastrar_administrativo(
  p_user_id uuid,
  p_email text,
  p_display_name text
)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  clean_email text := lower(trim(p_email));
begin
  if auth.uid() is null or not exists (
    select 1 from public.user_profiles
    where user_id = auth.uid() and role = 'superintendente' and coalesce(active, false)
  ) then
    raise exception 'Somente a Superintendente pode cadastrar usuários.';
  end if;

  if p_user_id is null or clean_email !~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$' then
    raise exception 'Usuário inválido.';
  end if;

  if not exists (
    select 1 from auth.users
    where id = p_user_id and lower(email) = clean_email
  ) then
    raise exception 'A conta de acesso ainda não existe.';
  end if;

  if exists (
    select 1 from public.user_profiles
    where user_id = p_user_id and role = 'superintendente'
  ) then
    raise exception 'Este cadastro só adiciona o perfil Administrativo.';
  end if;

  update auth.users
  set email_confirmed_at = coalesce(email_confirmed_at, now())
  where id = p_user_id;

  insert into public.user_profiles (user_id, email, display_name, role, active)
  values (p_user_id, clean_email, trim(p_display_name), 'administrativo', true)
  on conflict (user_id) do update
  set email = excluded.email,
      display_name = excluded.display_name,
      role = 'administrativo',
      active = true,
      updated_at = now();
end;
$$;

revoke all on function public.cadastrar_administrativo(uuid, text, text) from public;
grant execute on function public.cadastrar_administrativo(uuid, text, text) to authenticated;
