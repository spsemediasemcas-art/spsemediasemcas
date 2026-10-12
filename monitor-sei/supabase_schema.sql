-- Schema do Supabase para o Monitor SEI
-- Desenvolvido por: Jurandy Santana — WhatsApp: (98) 98401-6496
-- Rode no SQL Editor do Supabase (https://supabase.com/dashboard -> SQL Editor)

-- ---------------------------------------------------------------- processos
CREATE TABLE IF NOT EXISTS processos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    url TEXT UNIQUE NOT NULL,            -- md_pesq_processo_exibir.php?...
    apelido TEXT,
    numero TEXT,
    tipo TEXT,
    interessados TEXT,
    ultima_verificacao TEXT,
    ultima_novidade TEXT,
    erro TEXT,
    criado_em TEXT DEFAULT to_char(now(), 'YYYY-MM-DD"T"HH24:MI:SS')
);

CREATE INDEX IF NOT EXISTS idx_processos_numero ON processos(numero);

-- ---------------------------------------------------------------- itens
-- documentos e andamentos de cada processo
CREATE TABLE IF NOT EXISTS itens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    processo_id UUID NOT NULL REFERENCES processos(id) ON DELETE CASCADE,
    categoria TEXT NOT NULL,             -- 'documento' ou 'andamento'
    chave TEXT NOT NULL,                 -- id do doc no SEI (ou o nº)
    data TEXT,
    unidade TEXT,
    descricao TEXT,
    link TEXT,
    detectado_em TEXT,
    novo BOOLEAN DEFAULT FALSE,
    conteudo TEXT,                       -- texto extraído do documento
    resumo TEXT,
    assinatura TEXT,
    arquivo TEXT,                        -- path/URL do PDF salvo
    conteudo_status TEXT,
    UNIQUE(processo_id, categoria, chave)
);

CREATE INDEX IF NOT EXISTS idx_itens_processo ON itens(processo_id);
CREATE INDEX IF NOT EXISTS idx_itens_novo ON itens(novo);

-- ---------------------------------------------------------------- buscas
-- fila de buscas com captcha: o painel insere 'pendente',
-- o worker no Railway consome e atualiza o status.
CREATE TABLE IF NOT EXISTS buscas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    numero TEXT NOT NULL,
    apelido TEXT,
    status TEXT NOT NULL DEFAULT 'pendente',  -- pendente|rodando|achou|nao_encontrado|erro
    passos JSONB DEFAULT '[]',                -- últimas mensagens de progresso
    url TEXT,
    erro TEXT,
    criado_em TEXT DEFAULT to_char(now(), 'YYYY-MM-DD"T"HH24:MI:SS'),
    iniciado_em TEXT,
    finalizado_em TEXT
);

CREATE INDEX IF NOT EXISTS idx_buscas_status ON buscas(status, criado_em);

-- ---------------------------------------------------------------- RLS
-- O worker usa a service_role key (bypassa RLS). O painel, se público,
-- pode precisar de leitura — política opcional liberando leitura geral:
-- ALTER TABLE processos ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE itens     ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE buscas    ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY "leitura pública" ON processos FOR SELECT USING (true);
-- CREATE POLICY "leitura pública" ON itens     FOR SELECT USING (true);
-- CREATE POLICY "leitura pública" ON buscas    FOR SELECT USING (true);
-- CREATE POLICY "inserção pública" ON buscas    FOR INSERT WITH CHECK (true);
-- (só habilite se o painel usar a anon key; com service_role no backend,
--  deixe o RLS desligado)

-- ---------------------------------------------------------------- Realtime
-- para o painel atualizar sozinho quando o worker muda o status:
-- ALTER PUBLICATION supabase_realtime ADD TABLE buscas, itens, processos;
