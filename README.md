# Acompanhamento de Processos — Média Complexidade

Sistema interno para acompanhamento de processos do SEI, com autenticação, controle de permissões, histórico de atividades e persistência no Supabase.

**Responsável pelo projeto:** Jurandy1

## Perfis e permissões

- **Superintendente:** visualiza o painel geral e a auditoria, cadastra usuários, altera qualquer processo, conclui/reabre processos e exclui qualquer processo ou comentário.
- **Administrativo:** cadastra processos, altera ou exclui somente os processos que criou, comenta em qualquer processo e edita ou exclui somente os próprios comentários.
- As permissões também são verificadas no banco por políticas RLS; esconder botões na interface não é a única proteção.

## Implantação no Netlify

1. No Netlify, escolha **Add new site > Import an existing project** e conecte este repositório.
2. Não informe comando de build. O arquivo `netlify.toml` já define a pasta de publicação e as Functions.
3. Em **Site configuration > Environment variables**, crie `SUPABASE_SECRET_KEY` com a chave secreta do projeto Supabase.
4. Faça um novo deploy depois de salvar a variável.

Sem `SUPABASE_SECRET_KEY`, login e consulta continuam funcionando, mas o menu **Usuários** não consegue criar contas.

## Segurança

- Nunca envie `.env`, senha do banco, chave `service_role` ou chave secreta para o GitHub.
- A chave publicável do Supabase pode permanecer no navegador; a proteção dos dados depende das políticas RLS.
- O cadastro de usuários passa por `netlify/functions/create-user.mjs`, que confirma no servidor se a pessoa logada é Superintendente.
- Caso alguma chave secreta tenha sido compartilhada fora do Netlify/Supabase, gere outra antes de colocar o sistema em uso.

## Estrutura

- `index.html`: aplicação.
- `support.js`: runtime da interface.
- `netlify/functions/create-user.mjs`: criação protegida de usuários.
- `supabase/migrations/20261009_permissions.sql`: versão das regras de autoria e perfis do banco.
- `netlify.toml`: publicação e cabeçalhos de segurança.

