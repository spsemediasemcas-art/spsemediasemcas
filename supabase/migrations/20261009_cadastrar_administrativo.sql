drop function if exists public.cadastrar_administrativo(uuid, text, text);

create or replace function public.cadastrar_administrativo(
  p_email text,
  p_password text,
  p_display_name text
)
returns uuid
language plpgsql
security definer
set search_path = public, auth, extensions
as $$
declare
  clean_email text := lower(trim(p_email));
  clean_name text := trim(p_display_name);
  new_id uuid := gen_random_uuid();
begin
  if auth.uid() is null or not exists (
    select 1 from public.user_profiles
    where user_id = auth.uid() and role = 'superintendente' and coalesce(active, false)
  ) then
    raise exception 'Somente a Superintendente pode cadastrar usuários.';
  end if;

  if clean_name = '' or clean_email !~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$' then
    raise exception 'Informe o nome e um e-mail válido.';
  end if;

  if length(coalesce(p_password, '')) < 8 then
    raise exception 'A senha inicial deve ter pelo menos 8 caracteres.';
  end if;

  if exists (select 1 from auth.users where lower(email) = clean_email) then
    raise exception 'Já existe um usuário com esse e-mail.';
  end if;

  insert into auth.users (
    instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
    raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
    confirmation_token, email_change, email_change_token_new, recovery_token,
    is_sso_user, is_anonymous
  ) values (
    '00000000-0000-0000-0000-000000000000',
    new_id,
    'authenticated',
    'authenticated',
    clean_email,
    extensions.crypt(p_password, extensions.gen_salt('bf')),
    now(),
    '{"provider":"email","providers":["email"]}'::jsonb,
    jsonb_build_object('display_name', clean_name),
    now(),
    now(),
    '',
    '',
    '',
    '',
    false,
    false
  );

  insert into auth.identities (
    id, user_id, identity_data, provider, provider_id, last_sign_in_at, created_at, updated_at
  ) values (
    gen_random_uuid(),
    new_id,
    jsonb_build_object('sub', new_id::text, 'email', clean_email, 'email_verified', true),
    'email',
    new_id::text,
    now(),
    now(),
    now()
  );

  insert into public.user_profiles (user_id, email, display_name, role, active)
  values (new_id, clean_email, clean_name, 'administrativo', true);

  return new_id;
end;
$$;

revoke all on function public.cadastrar_administrativo(text, text, text) from public;
grant execute on function public.cadastrar_administrativo(text, text, text) to authenticated;
