-- Deixa a carga dos processos mais rápida.
-- Cada processo guardava em raw_data uma cópia de todos os seus comentários, com as imagens em base64.
-- Os comentários já ficam na tabela process_comments, e o site não usa essa cópia (passa a não gravá-la mais).
-- Rode uma vez no SQL Editor do Supabase.

update public.processes
set raw_data = raw_data - 'obs'
where raw_data ? 'obs';
