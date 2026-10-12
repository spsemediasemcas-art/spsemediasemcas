"""
supabase_sync.py
----------------
Integracao opcional do Monitor SEI com o Supabase (banco na nuvem).

O navegador e as consultas continuam rodando na sua maquina (IP domestico,
que passa pelo Cloudflare do SEI). So os DADOS sao enviados ao Supabase
via API REST — nao precisa instalar o pacote 'supabase', usa a stdlib
+ requests.

Desenvolvido por: Jurandy Santana
WhatsApp: (98) 98401-6496

Configuracao (arquivo `supabase_config.txt` ao lado deste arquivo):

    url=https://xxxxxxxx.supabase.co
    key=<service_role key>          # painel do Supabase: Settings -> API

Sem o arquivo (ou sem as duas linhas), o monitor funciona normalmente
em modo local — o Supabase so e ignorado.

Uso programatico (chamado pelo sei_monitor.py automaticamente):

    import supabase_sync
    supabase_sync.sincronizar_processo(con, processo_id)   # upsert processo+itens
    supabase_sync.sincronizar_tudo(con)                    # primeira carga / reparo
    supabase_sync.status()                                 # {"ativo": bool, ...}

Todas as funcoes sao tolerantes a falhas: se o Supabase estiver fora,
o erro e registrado no terminal e o monitor local segue funcionando.
"""

import json
import threading
import urllib.parse
from pathlib import Path

import requests

PASTA = Path(__file__).resolve().parent
ARQUIVO_CONFIG = PASTA / "supabase_config.txt"
TIMEOUT = 30
LOCK = threading.Lock()
_ultimo_erro = None      # última mensagem de erro (ou None)
_ultimo_envio = None     # "dd/mm/YYYY HH:MM" do último envio com sucesso


# --------------------------------------------------------------- configuração
def config():
    """Lê o arquivo supabase_config.txt -> (url, key) ou (None, None)."""
    if not ARQUIVO_CONFIG.is_file():
        return None, None
    url = key = None
    for linha in ARQUIVO_CONFIG.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        nome, _, valor = linha.partition("=")
        nome, valor = nome.strip().lower(), valor.strip()
        if nome == "url":
            url = valor
        elif nome == "key":
            key = valor
    if url and key and url.startswith("http"):
        return url.rstrip("/"), key
    return None, None


def ativo():
    url, key = config()
    return bool(url and key)


def status():
    url, _ = config()
    return {"ativo": bool(url),
            "url": url or None,
            "ultimo_envio": _ultimo_envio,
            "erro": _ultimo_erro}


# --------------------------------------------------------------- REST
def _headers(key):
    return {"apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=representation"}


def _post(tabela, linhas, key, url):
    """Upsert de uma ou mais linhas. Devolve o JSON retornado (lista)."""
    resp = requests.post(f"{url}/rest/v1/{tabela}", headers=_headers(key),
                         data=json.dumps(linhas), timeout=TIMEOUT)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def _row_para_dict(row):
    return {k: row[k] for k in row.keys()}


def _itens_do_processo(con, processo_id):
    return [dict(i) for i in con.execute(
        "SELECT * FROM itens WHERE processo_id=? ORDER BY CAST(chave AS INTEGER) DESC",
        (processo_id,))]


# --------------------------------------------------------------- envio
def sincronizar_processo(con, processo_id, db_lock=None, max_itens_por_lote=200):
    """Envia um processo e seus itens para o Supabase (upsert idempotente).

    A chave de ligação é a URL do processo (UNIQUE nas duas bases).
    Reenviar o mesmo processo não duplica nada — só atualiza.

    `db_lock` é o threading.Lock do monitor: quando passado, as LEITURAS do
    sqlite são feitas sob ele (o envio HTTP fica fora do lock, pra não travar
    o painel durante o POST).
    """
    global _ultimo_erro, _ultimo_envio
    url, key = config()
    if not url or not key:
        return False
    if db_lock:
        with db_lock:
            proc = con.execute("SELECT * FROM processos WHERE id=?",
                               (processo_id,)).fetchone()
            itens = _itens_do_processo(con, processo_id) if proc else []
    else:
        proc = con.execute("SELECT * FROM processos WHERE id=?",
                           (processo_id,)).fetchone()
        itens = _itens_do_processo(con, processo_id) if proc else []
    if not proc:
        return False
    proc = _row_para_dict(proc)

    with LOCK:
        try:
            # 1) upsert do processo -> devolve o UUID do Supabase
            retorno = _post("processos", [{
                "url": proc["url"],
                "apelido": proc.get("apelido"),
                "numero": proc.get("numero"),
                "tipo": proc.get("tipo"),
                "interessados": proc.get("interessados"),
                "ultima_verificacao": proc.get("ultima_verificacao"),
                "ultima_novidade": proc.get("ultima_novidade"),
                "erro": proc.get("erro"),
                "criado_em": proc.get("criado_em"),
            }], key, url)
            if not retorno:
                raise RuntimeError("Supabase não devolveu o processo gravado.")
            proc_uuid = retorno[0]["id"]

            # 2) itens em lotes
            for i in range(0, len(itens), max_itens_por_lote):
                lote = [{
                    "processo_id": proc_uuid,
                    "categoria": it["categoria"],
                    "chave": str(it["chave"]),
                    "data": it.get("data"),
                    "unidade": it.get("unidade"),
                    "descricao": it.get("descricao"),
                    "link": it.get("link"),
                    "detectado_em": it.get("detectado_em"),
                    "novo": bool(it.get("novo")),
                    "conteudo": it.get("conteudo"),
                    "resumo": it.get("resumo"),
                    "assinatura": it.get("assinatura"),
                    "arquivo": None,          # PDFs ficam locais (path da sua máquina)
                    "conteudo_status": it.get("conteudo_status"),
                } for it in itens[i:i + max_itens_por_lote]]
                _post("itens", lote, key, url)

            _ultimo_erro = None
            from datetime import datetime
            _ultimo_envio = datetime.now().strftime("%d/%m/%Y %H:%M")
            print(f"[supabase] '{proc.get('apelido') or proc.get('numero') or proc['url']}' "
                  f"enviado ({len(itens)} itens).", flush=True)
            return True
        except Exception as e:  # noqa: BLE001
            _ultimo_erro = str(e)
            print(f"[supabase] falha ao enviar processo {proc['url'][:60]}: {e}",
                  flush=True)
            return False


def sincronizar_tudo(con):
    """Envia todos os processos (usar na 1ª configuração ou para reparar)."""
    if not ativo():
        print("[supabase] desativado (sem supabase_config.txt). "
              "Monitor rodando só local.", flush=True)
        return 0
    print("[supabase] sincronizando todos os processos...", flush=True)
    ids = [r[0] for r in con.execute("SELECT id FROM processos ORDER BY id")]
    ok = sum(1 for i in ids if sincronizar_processo(con, i))
    print(f"[supabase] {ok}/{len(ids)} processo(s) sincronizado(s).", flush=True)
    return ok


def remover_processo(processo_url):
    """Apaga um processo (e seus itens, pelo CASCADE) do Supabase."""
    url, key = config()
    if not url or not key:
        return False
    try:
        filtro = urllib.parse.quote(processo_url, safe="")
        resp = requests.delete(
            f"{url}/rest/v1/processos?url=eq.{filtro}",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=TIMEOUT)
        if resp.status_code not in (200, 204):
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        print(f"[supabase] processo removido da nuvem: {processo_url[:60]}",
              flush=True)
        return True
    except Exception as e:  # noqa: BLE001
        _ultimo_erro = str(e)
        print(f"[supabase] falha ao remover processo: {e}", flush=True)
        return False
