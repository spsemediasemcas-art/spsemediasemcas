"""
Ponte com o Controle de Processos SEMCAS
Desenvolvido por: Jurandy Santana - WhatsApp: (98) 98401-6496

Envia o acompanhamento dos processos (o que o monitor SEI encontrou) para o
sistema Controle de Processos SEMCAS. La, cada envio aparece no submenu
"Acompanhamento de processo" dentro do processo.

Configuracao - arquivo "semcas_config.txt" na pasta (copie do exemplo).
Ha duas formas de entrar, escolha UMA:

  A) Conta do sistema (usa o mesmo login do Controle de Processos):
        url=https://xxxxxxxx.supabase.co
        email=seuemail@exemplo.com
        senha=suasenha

  B) Chave de servico (se voce tiver acesso ao painel do Supabase):
        url=https://xxxxxxxx.supabase.co
        key=CHAVE_SERVICE_ROLE

Sem esse arquivo, tudo funciona normalmente - apenas nao envia.

Uso:
    python semcas_sync.py --testar    (confere a configuracao e o login)
    python semcas_sync.py --enviar    (envia o que ainda nao foi enviado)
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
ARQ_CONFIG = os.path.join(AQUI, "semcas_config.txt")
ARQ_MARCA = os.path.join(AQUI, "semcas_enviados.json")   # guarda o que ja subiu
ARQ_SESSAO = os.path.join(AQUI, "semcas_sessao.json")    # guarda o token do login

# chave publica do sistema (a mesma que o app usa) - nao e secreta
CHAVE_PUBLICA = "sb_publishable_fR6nS5GOjrISTwNQjTuhUQ_e9zThR05"


def _ler_config():
    if not os.path.exists(ARQ_CONFIG):
        return None
    cfg = {}
    with open(ARQ_CONFIG, "r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            k, v = linha.split("=", 1)
            cfg[k.strip().lower()] = v.strip()
    if not cfg.get("url"):
        return None
    if cfg.get("key") or (cfg.get("email") and cfg.get("senha")):
        return cfg
    return None


def ativo():
    return _ler_config() is not None


# ---------------------------------------------------------------- sessao
def _ler_sessao():
    if os.path.exists(ARQ_SESSAO):
        try:
            return json.load(open(ARQ_SESSAO, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _salvar_sessao(d):
    try:
        json.dump(d, open(ARQ_SESSAO, "w", encoding="utf-8"))
    except Exception:
        pass


def _entrar(cfg):
    """Entra com a conta do sistema e guarda o token."""
    corpo = json.dumps({"email": cfg["email"], "password": cfg["senha"]}).encode("utf-8")
    req = urllib.request.Request(
        cfg["url"].rstrip("/") + "/auth/v1/token?grant_type=password",
        data=corpo,
        headers={"apikey": cfg.get("key") or CHAVE_PUBLICA,
                 "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=45) as r:
        dados = json.loads(r.read().decode("utf-8"))
    usuario = (dados.get("user") or {}).get("id", "")
    _salvar_sessao({"access_token": dados.get("access_token"),
                    "refresh_token": dados.get("refresh_token"),
                    "user_id": usuario,
                    "email": cfg.get("email", "")})
    return dados.get("access_token")


def _renovar(cfg, refresh):
    corpo = json.dumps({"refresh_token": refresh}).encode("utf-8")
    req = urllib.request.Request(
        cfg["url"].rstrip("/") + "/auth/v1/token?grant_type=refresh_token",
        data=corpo,
        headers={"apikey": cfg.get("key") or CHAVE_PUBLICA,
                 "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=45) as r:
        dados = json.loads(r.read().decode("utf-8"))
    usuario = (dados.get("user") or {}).get("id", "")
    _salvar_sessao({"access_token": dados.get("access_token"),
                    "refresh_token": dados.get("refresh_token"),
                    "user_id": usuario,
                    "email": cfg.get("email", "")})
    return dados.get("access_token")


def _usuario_id(cfg):
    """Id do usuario logado (o banco exige author_user_id = quem entrou)."""
    return _ler_sessao().get("user_id", "")


def _token(cfg):
    """Devolve o token: chave de servico, ou token do login (renovando se preciso)."""
    if cfg.get("key"):
        return cfg["key"]
    s = _ler_sessao()
    if s.get("access_token"):
        return s["access_token"]
    if s.get("refresh_token"):
        try:
            return _renovar(cfg, s["refresh_token"])
        except Exception:
            pass
    return _entrar(cfg)


def _cabecalhos(cfg, token, extra=None):
    h = {"apikey": cfg.get("key") or CHAVE_PUBLICA,
         "Authorization": f"Bearer {token}",
         "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


# ---------------------------------------------------------------- requisicoes
def _novo_token(cfg):
    """Token venceu: renova pelo refresh_token ou entra de novo."""
    if cfg.get("key"):
        return cfg["key"]
    s = _ler_sessao()
    if s.get("refresh_token"):
        try:
            return _renovar(cfg, s["refresh_token"])
        except Exception:
            pass
    return _entrar(cfg)


def _requisitar(cfg, caminho, metodo="GET", corpo=None, prefer=None, timeout=45):
    """Faz a chamada; se o token tiver vencido (401), renova e tenta uma vez mais."""
    dados = None if corpo is None else json.dumps(corpo).encode("utf-8")
    token = _token(cfg)
    for tentativa in (1, 2):
        extra = {"Prefer": prefer} if prefer else None
        req = urllib.request.Request(cfg["url"].rstrip("/") + caminho, data=dados,
                                     headers=_cabecalhos(cfg, token, extra), method=metodo)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                bruto = r.read().decode("utf-8")
                return r.status, (json.loads(bruto) if bruto.strip() else None)
        except urllib.error.HTTPError as e:
            if e.code == 401 and tentativa == 1:
                token = _novo_token(cfg)
                continue
            raise


def _get(cfg, caminho):
    return _requisitar(cfg, caminho)[1]


def _post(cfg, caminho, corpo):
    return _requisitar(cfg, caminho, "POST", corpo,
                       "return=minimal,resolution=merge-duplicates", timeout=60)[0]


# ---------------------------------------------------------------- marca local
def _marca():
    if os.path.exists(ARQ_MARCA):
        try:
            return json.load(open(ARQ_MARCA, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _salvar_marca(m):
    json.dump(m, open(ARQ_MARCA, "w", encoding="utf-8"), ensure_ascii=False)


# ---------------------------------------------------------------- conteudo
def _texto_item(item):
    """Monta o texto de um item (documento/andamento) para o registro."""
    data = (item.get("data") or "").strip()
    unidade = (item.get("unidade") or "").strip()
    desc = (item.get("descricao") or "").strip()
    # a descricao costuma vir "4479247Ofício - 24/07/2026" (numero colado no tipo)
    desc = re.sub(r"^(\d{6,})(?=[A-Za-zÀ-ÿ])", r"\1 - ", desc)
    cabeca = " ".join(p for p in (data, f"({unidade})" if unidade else "", desc) if p).strip()
    resumo = (item.get("resumo") or "").strip()
    if resumo:
        return cabeca + "\n\n" + resumo[:1500]
    return cabeca


def _achar_processo_semcas(cfg, numero):
    """Procura o id do processo no SEMCAS pelo numero SEI (campo sei_number)."""
    if not numero:
        return None
    marca = _marca()
    cache = marca.get("_ids", {})
    if numero in cache:
        return cache[numero]
    try:
        dados = _get(cfg, "/rest/v1/processes?select=id,sei_number&sei_number=eq."
                     + urllib.parse.quote(numero))
        if dados:
            ids = marca.get("_ids", {})
            ids[numero] = dados[0]["id"]
            marca["_ids"] = ids
            _salvar_marca(marca)
            return dados[0]["id"]
    except Exception:
        return None
    return None


def sincronizar_processo(con, processo_id, cfg=None):
    """Envia os itens novos de UM processo para o SEMCAS. Devolve quantos foram."""
    cfg = cfg or _ler_config()
    if not cfg:
        return 0

    proc = con.execute("SELECT * FROM processos WHERE id=?", (processo_id,)).fetchone()
    if not proc:
        return 0
    proc = dict(proc)
    numero = (proc.get("numero") or "").strip()

    pid_semcas = _achar_processo_semcas(cfg, numero)
    if not pid_semcas:
        return 0

    marca = _marca()
    ja = set(marca.get(str(processo_id), []))

    itens = con.execute(
        "SELECT * FROM itens WHERE processo_id=? ORDER BY id", (processo_id,)).fetchall()
    novos = 0
    for it in itens:
        it = dict(it)
        chave = f"{it['categoria']}:{it['chave']}"
        if chave in ja:
            continue
        corpo = {
            "process_id": pid_semcas,
            "source_index": 900000 + int(it["id"]),   # faixa propria do monitor
            "title": "Documento novo" if it["categoria"] == "documento" else "Andamento novo",
            "category": "monitor_sei",
            "comment_type": "monitor_sei",
            "body": _texto_item(it),
            "sei_message": it.get("link") or "",
            "attachments": [],
            "event_date_text": it.get("data") or datetime.now().strftime("%d/%m/%Y"),
            "author_name": "Monitor SEI",
            "author_role": "consulta automatica",
            "display_date": datetime.now().strftime("%d/%m/%Y %H:%M"),
        }
        uid = _usuario_id(cfg)
        if uid:
            corpo["author_user_id"] = uid
        try:
            _post(cfg, "/rest/v1/process_comments", corpo)
            ja.add(chave)
            novos += 1
        except urllib.error.HTTPError as e:
            detalhe = e.read().decode("utf-8", "replace")[:200]
            raise RuntimeError(f"SEMCAS recusou ({e.code}): {detalhe}")
        except Exception as e:
            raise RuntimeError(f"falha ao enviar: {e}")

    marca[str(processo_id)] = sorted(ja)
    _salvar_marca(marca)
    return novos


# ---------------------------------------------------------------- "Verificar agora"
# O site grava pedidos em monitor_pedidos; o monitor pega, verifica e devolve o resultado.
def _agora_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def so_digitos(numero):
    return re.sub(r"\D", "", numero or "")


def pedidos_pendentes(cfg=None, limite=10):
    cfg = cfg or _ler_config()
    if not cfg:
        return []
    return _get(cfg, "/rest/v1/monitor_pedidos?select=id,process_id,sei_number"
                     "&status=eq.pendente&order=criado_em&limit=%d" % limite) or []


def pegar_pedido(pedido_id, cfg=None):
    """Marca o pedido como 'rodando'. Devolve False se outro monitor já pegou."""
    cfg = cfg or _ler_config()
    _, linhas = _requisitar(
        cfg, "/rest/v1/monitor_pedidos?id=eq.%s&status=eq.pendente" % urllib.parse.quote(pedido_id),
        "PATCH", {"status": "rodando", "iniciado_em": _agora_iso()}, "return=representation")
    return bool(linhas)


def concluir_pedido(pedido_id, status, mensagem="", novidades=0, cfg=None):
    cfg = cfg or _ler_config()
    _requisitar(cfg, "/rest/v1/monitor_pedidos?id=eq.%s" % urllib.parse.quote(pedido_id), "PATCH",
                {"status": status, "mensagem": (mensagem or "")[:500],
                 "novidades": int(novidades or 0), "finalizado_em": _agora_iso()},
                "return=minimal")


def sinal_de_vida(processos_monitorados, ultima_rodada="", cfg=None, nome="monitor-pc1"):
    cfg = cfg or _ler_config()
    if not cfg:
        return
    _requisitar(cfg, "/rest/v1/monitor_status?on_conflict=id", "POST",
                {"id": nome, "ultimo_sinal": _agora_iso(),
                 "processos_monitorados": int(processos_monitorados),
                 "ultima_rodada": ultima_rodada or ""},
                "return=minimal,resolution=merge-duplicates")


def sincronizar_tudo(con):
    cfg = _ler_config()
    if not cfg:
        return 0
    total = 0
    for r in con.execute("SELECT id FROM processos").fetchall():
        try:
            total += sincronizar_processo(con, r[0], cfg)
        except Exception as e:
            print(f"[semcas] processo {r[0]}: {e}")
    return total


if __name__ == "__main__":
    if "--testar" in sys.argv:
        cfg = _ler_config()
        if not cfg:
            print("[semcas] sem semcas_config.txt - modo desligado")
            sys.exit(0)
        modo = "chave de servico" if cfg.get("key") else f"login ({cfg.get('email')})"
        print(f"[semcas] configuracao encontrada: {cfg['url']} | modo: {modo}")
        try:
            tok = _token(cfg)
            print(f"[semcas] entrada: OK (token com {len(tok)} caracteres)")
        except Exception as e:
            print(f"[semcas] FALHA na entrada: {e}")
            sys.exit(1)
        try:
            dados = _get(cfg, "/rest/v1/processes?select=id,sei_number&limit=2")
            print(f"[semcas] leitura: OK ({len(dados)} processos de amostra)")
        except Exception as e:
            print(f"[semcas] leitura FALHOU: {e}")
        sys.exit(0)

    if "--enviar" in sys.argv:
        import sei_monitor as m
        n = sincronizar_tudo(m.con)
        print(f"[semcas] enviados: {n} registros novos")
        sys.exit(0)

    print(__doc__)
