"""
Monitor de Processos SEI - Prefeitura de São Luís
-------------------------------------------------
Acompanha processos pela Pesquisa Pública do SEI e avisa quando aparece
documento novo ou andamento novo. Consulta automática por número e
integração opcional com Supabase (dados na nuvem).

Desenvolvido por: Jurandy Santana
WhatsApp: (98) 98401-6496

Uso:
    python sei_monitor.py            -> abre o painel em http://localhost:8765
    python sei_monitor.py --uma-vez  -> só verifica tudo uma vez e sai

Ambiente Python: veja LEIA-ME.txt (a pasta ja traz o ambiente portatil)
"""
import html
import json
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import supabase_sync
except ImportError:                       # arquivo sumiu/renomeado -> modo local puro
    supabase_sync = None

try:
    import semcas_sync                    # envio para o Controle de Processos SEMCAS
except ImportError:
    semcas_sync = None

semcas_ultimo_erro = None

PORTA = 8765
INTERVALO_MIN = 30          # de quanto em quanto tempo verifica (minutos)
PAUSA_ENTRE_PROCESSOS = 3   # segundos entre um processo e outro (não sobrecarregar o SEI)
NOTIFICAR_WINDOWS = True    # balão de notificação no Windows

BASE_PESQUISA = "https://sei.saoluis.ma.gov.br/sei/modulos/pesquisa/"
PASTA = Path(__file__).resolve().parent
DB = PASTA / "sei_monitor.db"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")

lock = threading.Lock()


# ---------------------------------------------------------------- banco
def conectar():
    con = sqlite3.connect(DB, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript("""
    CREATE TABLE IF NOT EXISTS processos(
        id INTEGER PRIMARY KEY,
        url TEXT UNIQUE NOT NULL,
        apelido TEXT,
        numero TEXT, tipo TEXT, interessados TEXT,
        ultima_verificacao TEXT, ultima_novidade TEXT, erro TEXT,
        criado_em TEXT);
    CREATE TABLE IF NOT EXISTS itens(
        id INTEGER PRIMARY KEY,
        processo_id INTEGER NOT NULL REFERENCES processos(id) ON DELETE CASCADE,
        categoria TEXT NOT NULL,          -- 'documento' ou 'andamento'
        chave TEXT NOT NULL,
        data TEXT, unidade TEXT, descricao TEXT, link TEXT,
        detectado_em TEXT, novo INTEGER DEFAULT 0,
        UNIQUE(processo_id, categoria, chave));
    """)
    # colunas do conteúdo dos documentos (adicionadas depois)
    existentes = {r[1] for r in con.execute("PRAGMA table_info(itens)")}
    for col in ("conteudo", "resumo", "assinatura", "arquivo", "conteudo_status"):
        if col not in existentes:
            con.execute(f"ALTER TABLE itens ADD COLUMN {col} TEXT")
    con.commit()
    return con


con = conectar()


# ---------------------------------------------------------------- leitura do SEI
def baixar_bruto(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read(), r.headers


def decodificar(dados):
    try:
        return dados.decode("utf-8")
    except UnicodeDecodeError:
        return dados.decode("iso-8859-1")


def baixar(url):
    return decodificar(baixar_bruto(url)[0])


def limpar(trecho):
    trecho = re.sub(r"<br\s*/?>", " ", trecho, flags=re.I)
    trecho = re.sub(r"<[^>]+>", "", trecho)
    return re.sub(r"\s+", " ", html.unescape(trecho)).strip()


def tabela(pagina, id_tabela):
    m = re.search(r'<table[^>]*id="%s".*?</table>' % id_tabela, pagina, re.S | re.I)
    return m.group(0) if m else ""


def analisar(pagina):
    if "tblHistorico" not in pagina and "tblCabecalho" not in pagina:
        raise ValueError("Página não reconhecida (link expirado/errado ou SEI fora do ar).")

    cab = {}
    for rot, val in re.findall(r"<td[^>]*><b>(.*?):</b></td>\s*<td>(.*?)</td>",
                               tabela(pagina, "tblCabecalho"), re.S):
        cab[limpar(rot)] = limpar(val)

    documentos = []
    for linha in re.findall(r"<tr class=\"infraTr[^\"]*\">(.*?)</tr>",
                            tabela(pagina, "tblDocumentos"), re.S):
        # O SEI erra os data-label das colunas, então lemos pela posição:
        # [0] seleção, [1] nº documento, [2] tipo, [3] data, [4] inclusão, [5] unidade
        tds = re.findall(r"<td[^>]*>(.*?)</td>", linha, re.S)
        if len(tds) < 6:
            continue
        chave = re.search(r'type="checkbox" value="(\d+)"', linha)
        link = re.search(r"window\.open\('([^']+)'\)", linha)
        numero = limpar(tds[1])
        documentos.append({
            "chave": chave.group(1) if chave else numero,
            "data": limpar(tds[3]),
            "unidade": limpar(tds[5]),
            "descricao": f"{numero} - {limpar(tds[2])}",
            "link": urllib.parse.urljoin(BASE_PESQUISA, link.group(1)) if link else "",
        })

    andamentos = []
    for ativ, linha in re.findall(r'<tr[^>]*data-atividade="(\d+)"[^>]*>(.*?)</tr>',
                                  tabela(pagina, "tblHistorico"), re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", linha, re.S)
        if len(tds) < 3:
            continue
        andamentos.append({"chave": ativ, "data": limpar(tds[0]),
                           "unidade": limpar(tds[1]), "descricao": limpar(tds[2]),
                           "link": ""})
    return cab, documentos, andamentos


def nome_arquivo_seguro(nome):
    return re.sub(r'[\\/:*?"<>|]+', "_", nome).strip(" .")[:150] or "documento"


def ler_documento(item, numero_processo):
    """Abre o link do documento. HTML -> guarda o texto; PDF/outros -> salva o arquivo."""
    dados, cab = baixar_bruto(item["link"])
    tipo = (cab.get("Content-Type") or "").lower()
    if "text/html" in tipo:
        bruto = decodificar(dados)
        bruto = re.sub(r"<(script|style|title)[^>]*>.*?</\1>", " ", bruto, flags=re.S | re.I)
        bruto = re.sub(r"</(p|div|tr|h\d|li)>|<br\s*/?>", "\n", bruto, flags=re.I)
        texto = html.unescape(re.sub(r"<[^>]+>", " ", bruto))
        linhas = [re.sub(r"[ \t\xa0]+", " ", l).strip() for l in texto.splitlines()]
        texto = "\n".join(l for l in linhas if l)
        if "captcha" in texto.lower() and len(texto) < 1500:
            raise ValueError("SEI pediu captcha para este documento.")
        assin = [f"{n.strip()} ({c.strip()}) em {d} {h}" for n, c, d, h in re.findall(
            r"assinado eletronicamente.*?por\s+(.+?)\s*,\s*(.+?)\s*,\s*em\s+(\d\d/\d\d/\d{4}),?\s*às\s+(\d\d:\d\d)",
            texto, re.S | re.I)]
        # resumo = corpo do texto, sem cabeçalho e sem rodapé de assinatura
        corpo = re.split(r"\n(?:Logado por:|Documento assinado eletronicamente|"
                         r"A autenticidade deste documento)", texto)[0]
        data_doc = re.search(r"\d{1,2} de \w+ de \d{4}\s*\n", corpo)
        if data_doc:
            corpo = corpo[data_doc.end():]
        return {"conteudo": texto, "resumo": re.sub(r"\s+", " ", corpo).strip()[:400],
                "assinatura": "; ".join(assin), "arquivo": None}

    disp = cab.get("Content-Disposition") or ""
    m = re.search(r'filename="?([^";]+)', disp)
    ext = ".pdf" if "pdf" in tipo else ""
    nome = m.group(1) if m else f"documento{ext}"
    pasta = PASTA / "documentos" / nome_arquivo_seguro(numero_processo or "processo")
    pasta.mkdir(parents=True, exist_ok=True)
    num_doc = item["descricao"].split(" - ")[0]
    destino = pasta / nome_arquivo_seguro(f"{num_doc} - {nome}")
    destino.write_bytes(dados)
    return {"conteudo": None, "resumo": f"Arquivo anexado: {nome}", "assinatura": None,
            "arquivo": str(destino)}


def buscar_conteudos(processo_id, numero_processo, limite=30):
    """Baixa o conteúdo dos documentos que ainda não foram lidos."""
    with lock:
        pend = [dict(r) for r in con.execute(
            "SELECT * FROM itens WHERE processo_id=? AND categoria='documento' AND link<>'' "
            "AND conteudo_status IS NULL ORDER BY novo DESC, CAST(chave AS INTEGER) DESC LIMIT ?",
            (processo_id, limite))]
    for it in pend:
        try:
            r = ler_documento(it, numero_processo)
            status = "ok"
        except Exception as e:  # noqa: BLE001
            r = {"conteudo": None, "resumo": None, "assinatura": None, "arquivo": None}
            status = f"erro: {e}"
        with lock:
            con.execute("UPDATE itens SET conteudo=?, resumo=?, assinatura=?, arquivo=?, "
                        "conteudo_status=? WHERE id=?",
                        (r["conteudo"], r["resumo"], r["assinatura"], r["arquivo"], status, it["id"]))
            con.commit()
        it.update(r)
        time.sleep(1)
    return {it["chave"]: it for it in pend}


def verificar(proc):
    """Verifica um processo. Retorna lista de novidades."""
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    try:
        cab, docs, ands = analisar(baixar(proc["url"]))
    except Exception as e:  # noqa: BLE001
        with lock:
            con.execute("UPDATE processos SET erro=?, ultima_verificacao=? WHERE id=?",
                        (str(e), agora, proc["id"]))
            con.commit()
        return []

    with lock:
        primeira = con.execute("SELECT COUNT(*) FROM itens WHERE processo_id=?",
                               (proc["id"],)).fetchone()[0] == 0
        novidades = []
        for categoria, lista in (("documento", docs), ("andamento", ands)):
            for it in lista:
                cur = con.execute(
                    "INSERT OR IGNORE INTO itens(processo_id,categoria,chave,data,unidade,"
                    "descricao,link,detectado_em,novo) VALUES(?,?,?,?,?,?,?,?,?)",
                    (proc["id"], categoria, it["chave"], it["data"], it["unidade"],
                     it["descricao"], it["link"], agora, 0 if primeira else 1))
                if cur.rowcount and not primeira:
                    novidades.append((categoria, it))
        con.execute(
            "UPDATE processos SET numero=?, tipo=?, interessados=?, ultima_verificacao=?, "
            "erro=NULL, ultima_novidade=COALESCE(?, ultima_novidade) WHERE id=?",
            (cab.get("Processo"), cab.get("Tipo"), cab.get("Interessados"), agora,
             agora if novidades else None, proc["id"]))
        con.commit()

    # abre os documentos (novos primeiro) e guarda texto / PDF
    lidos = buscar_conteudos(proc["id"], cab.get("Processo"))
    for categoria, it in novidades:
        if categoria == "documento" and it["chave"] in lidos:
            it["resumo"] = lidos[it["chave"]].get("resumo")
    _enviar_nuvem(proc["id"])
    return novidades


def notificar(titulo, texto):
    if not NOTIFICAR_WINDOWS or sys.platform != "win32":
        return
    t = titulo.replace("'", "''")[:60]
    m = texto.replace("'", "''")[:250]
    ps = ("Add-Type -AssemblyName System.Windows.Forms;"
          "$n=New-Object System.Windows.Forms.NotifyIcon;"
          "$n.Icon=[System.Drawing.SystemIcons]::Information;$n.Visible=$true;"
          f"$n.ShowBalloonTip(15000,'{t}','{m}','Info');Start-Sleep 16;$n.Dispose()")
    subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def verificar_todos():
    with lock:
        procs = [dict(p) for p in con.execute("SELECT * FROM processos")]
    total = []
    for i, p in enumerate(procs):
        nov = verificar(p)
        if nov:
            nome = p["apelido"] or p["numero"] or "Processo"
            linhas = [f"{'Doc' if c == 'documento' else 'Andamento'}: {it['descricao']}"
                      + (f" — {it['resumo'][:120]}" if it.get("resumo") else "")
                      for c, it in nov]
            print(f"[{datetime.now():%H:%M}] {nome}: {len(nov)} novidade(s)")
            for l in linhas:
                print("   ", l)
            notificar(f"SEI: {nome}", "\n".join(linhas))
            total += nov
        if i < len(procs) - 1:
            time.sleep(PAUSA_ENTRE_PROCESSOS)
    return total


def laco():
    while True:
        try:
            verificar_todos()
        except Exception as e:  # noqa: BLE001
            print("Erro na verificação:", e)
        time.sleep(INTERVALO_MIN * 60)


# ---------------------------------------------------------------- painel web
PAGINA = r"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Monitor SEI</title><style>
:root{--bg:#f4f6f9;--card:#fff;--tx:#1d2733;--mut:#667;--pri:#1f5fa8;--nov:#d9480f;--bd:#dde3ea}
*{box-sizing:border-box}body{margin:0;font:15px/1.45 system-ui,Segoe UI,sans-serif;background:var(--bg);color:var(--tx)}
header{background:var(--pri);color:#fff;padding:14px 20px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
header h1{font-size:18px;margin:0;flex:1}main{max-width:1100px;margin:0 auto;padding:16px}
button{font:inherit;border:0;border-radius:6px;padding:7px 12px;cursor:pointer;background:var(--pri);color:#fff}
button.sec{background:#e8edf3;color:var(--tx)}button.del{background:#fde8e8;color:#a61b1b}
form{display:flex;gap:8px;flex-wrap:wrap;background:var(--card);padding:12px;border-radius:8px;border:1px solid var(--bd);margin-bottom:16px}
input{font:inherit;padding:7px 10px;border:1px solid var(--bd);border-radius:6px;flex:1;min-width:180px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:8px;margin-bottom:12px;overflow:hidden}
.card.temnovo{border-left:5px solid var(--nov)}
.topo{padding:12px 14px;display:flex;gap:10px;align-items:flex-start;flex-wrap:wrap;cursor:pointer}
.topo .info{flex:1;min-width:240px}.num{font-weight:700}.mut{color:var(--mut);font-size:13px}
.badge{background:var(--nov);color:#fff;border-radius:99px;padding:2px 9px;font-size:12px;font-weight:700}
.erro{color:#a61b1b;font-size:13px}.det{display:none;border-top:1px solid var(--bd);padding:10px 14px}
.card.aberto .det{display:block}table{width:100%;border-collapse:collapse;font-size:13.5px}
td,th{text-align:left;padding:5px 6px;border-bottom:1px solid var(--bd);vertical-align:top}
tr.novo td{background:#fff3e6;font-weight:600}h3{font-size:14px;margin:12px 0 4px}a{color:var(--pri)}
.acoes{display:flex;gap:6px;flex-wrap:wrap}.resumo{margin:3px 0;color:#333;font-weight:400}
pre{white-space:pre-wrap;font:13px/1.45 system-ui,sans-serif;background:#f7f9fb;padding:8px;border-radius:6px;max-height:420px;overflow:auto}
summary{cursor:pointer;color:var(--pri);font-size:13px}#busca{max-width:280px;flex:0 1 280px}
</style></head><body>
<header><h1>Monitor de Processos SEI</h1><span id="status" class="mut" style="color:#dfe8f5"></span>
<span id="nuvem" class="mut" style="color:#cfe0f5;font-size:13px"></span>
<input id="busca" placeholder="Buscar (nº, nome, texto dos documentos...)" oninput="filtrar()">
<button class="sec" onclick="verificarAgora()">Verificar agora</button></header>
<main>
<form onsubmit="adicionar(event)">
<input id="url" placeholder="Cole o link do processo, ou digite o nº para consulta automática" required>
<input id="apelido" placeholder="Apelido (opcional)" style="max-width:260px">
<button>Adicionar / Pesquisar</button>
<button type="button" class="sec" onclick="retreinar()" title="Atualiza a base de reconhecimento com os codigos validados nas consultas">🔄 Atualizar base</button></form>
<div id="buscas"></div>
<div id="lista">Carregando...</div></main>
<script>
const abertos=new Set();
const esc=s=>(s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function api(c,d){const r=await fetch('/api/'+c,{method:'POST',body:JSON.stringify(d||{})});return r.json()}
function linhas(it){return it.map(i=>`<tr class="${i.novo?'novo':''}"><td>${esc(i.data)}</td><td>${esc(i.unidade)}</td>
<td>${i.link?`<a href="${esc(i.link)}" target="_blank">${esc(i.descricao)}</a>`:esc(i.descricao)}</td></tr>`).join('')}
function docs(it){return it.map(i=>`<tr class="${i.novo?'novo':''}"><td>${esc(i.data)}</td><td>${esc(i.unidade)}</td>
<td><a href="${esc(i.link)}" target="_blank">${esc(i.descricao)}</a>
 ${i.resumo?`<div class="resumo">${esc(i.resumo)}</div>`:''}
 ${i.assinatura?`<div class="mut">✍ Assinado por ${esc(i.assinatura)}</div>`:''}
 ${i.conteudo?`<details><summary>Ver texto completo</summary><pre>${esc(i.conteudo)}</pre></details>`:''}
 ${i.arquivo?`<a href="/arquivo/${i.id}" target="_blank">📄 Abrir arquivo salvo</a>`:''}
 ${i.conteudo_status&&i.conteudo_status.startsWith('erro')?`<div class="erro">${esc(i.conteudo_status)}</div>`:''}
 ${!i.conteudo_status&&i.link?`<div class="mut">(conteúdo ainda não baixado)</div>`:''}
</td></tr>`).join('')}
function filtrar(){const q=busca.value.trim().toLowerCase();document.querySelectorAll('.card').forEach(c=>{
 c.style.display=!q||c.dataset.txt.includes(q)?'':'none'})}
async function carregar(){
 const d=await (await fetch('/api/lista')).json();
 document.getElementById('status').textContent=d.verificando?'Verificando...':`Verifica a cada ${d.intervalo} min`;
 const sb=d.supabase||{};
 document.getElementById('nuvem').innerHTML=sb.ativo
  ?`☁ Supabase${sb.ultimo_envio?' · último envio '+sb.ultimo_envio:''}${sb.erro?' ⚠ '+sb.erro:''}`
  :'☁ Supabase desativado (só local)';
 if(!d.processos.length){document.getElementById('lista').innerHTML='<p class="mut">Nenhum processo ainda. Cole um link acima.</p>';return}
 document.getElementById('lista').innerHTML=d.processos.map(p=>{
  const docs=p.itens.filter(i=>i.categoria=='documento'),ands=p.itens.filter(i=>i.categoria=='andamento');
  const ult=ands[0];
  return `<div class="card ${p.novos?'temnovo':''} ${abertos.has(p.id)?'aberto':''}" id="c${p.id}">
  <div class="topo" onclick="alternar(${p.id})"><div class="info">
   <div><span class="num">${esc(p.numero||'(aguardando 1ª verificação)')}</span> ${p.apelido?'— '+esc(p.apelido):''}
   ${p.novos?`<span class="badge">${p.novos} novo(s)</span>`:''}</div>
   <div class="mut">${esc(p.tipo)}${p.interessados?' · '+esc(p.interessados):''}</div>
   ${ult?`<div class="mut">Último andamento: <b>${esc(ult.data)}</b> · ${esc(ult.unidade)} · ${esc(ult.descricao)}</div>`:''}
   <div class="mut">Verificado: ${esc(p.ultima_verificacao||'-')} ${p.ultima_novidade?'· Última novidade: '+esc(p.ultima_novidade):''}</div>
   ${p.erro?`<div class="erro">Erro: ${esc(p.erro)}</div>`:''}</div>
  <div class="acoes" onclick="event.stopPropagation()">
   ${p.novos?`<button class="sec" onclick="lido(${p.id})">Marcar como lido</button>`:''}
   <a href="${esc(p.url)}" target="_blank"><button class="sec">Abrir no SEI</button></a>
   <button class="del" onclick="remover(${p.id})">Remover</button></div></div>
  <div class="det"><h3>Andamentos (${ands.length})</h3><table>${linhas(ands)}</table>
  <h3>Documentos (${docs.length})</h3><table>${window.docs(docs)}</table></div></div>`}).join('');
 d.processos.forEach(p=>{const c=document.getElementById('c'+p.id);c.dataset.txt=[p.numero,p.apelido,p.tipo,p.interessados,
  ...p.itens.map(i=>[i.descricao,i.unidade,i.conteudo,i.assinatura].join(' '))].join(' ').toLowerCase()});filtrar();
 const bs=Object.entries(d.buscas||{});
 document.getElementById('buscas').innerHTML=bs.length?`<div class="card" style="padding:10px 14px">
 <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
 <b>Buscas em andamento</b>
 <button class="sec" style="padding:3px 10px;font-size:12.5px" onclick="limparBuscas()">Limpar</button></div>
 <div class="mut">`+
  bs.map(([n,b])=>`${esc(n)}: `+({buscando:'🔍 consultando o SEI (código automático)...',
   achou:'✅ encontrado e adicionado à lista',nao_encontrado:'❌ não encontrado',erro:'⚠ '+(b.msg||'erro')}[b.estado]||b.estado)
   +(b.passos&&b.passos.length?`<div style="margin:2px 0 6px 12px;font-size:12px;line-height:1.5">`+
    b.passos.map(p=>`· ${esc(p)}<br>`).join('')+`</div>`:'')).join('')+
  `</div></div>`:'';
 if(bs.some(([n,b])=>b.estado==='buscando')){clearTimeout(window.rt);window.rt=setTimeout(carregar,1500)}}
function alternar(id){abertos.has(id)?abertos.delete(id):abertos.add(id);document.getElementById('c'+id).classList.toggle('aberto')}
const PESQUISA='https://sei.saoluis.ma.gov.br/sei/modulos/pesquisa/md_pesq_processo_pesquisar.php?acao_externa=protocolo_pesquisar&acao_origem_externa=protocolo_pesquisar&id_orgao_acesso_externo=0';
async function adicionar(e){e.preventDefault();
 const valor=url.value.trim();
 if(/^\s*\d{5}\.\d{6}\/\d{4}(-\d{2})?\s*$/.test(valor)){
  const r=await api('pesquisar',{numero:valor,apelido:apelido.value.trim()});
  if(r.erro)alert(r.erro);
  else{url.value='';apelido.value='';
   alert('Busca automática iniciada para '+valor+'.\n\n'+
    'O sistema pesquisa o SEI em segundo plano (código de verificação automático)\n'+
    'e, quando achar, o processo aparece na lista aqui em baixo.\n'+
    'Acompanhe o status em "Buscas em andamento".');}
  carregar();return}
 const r=await api('adicionar',{url:valor,apelido:apelido.value.trim()});
 if(r.erro)alert(r.erro);else{url.value='';apelido.value=''}carregar()}
async function lido(id){await api('lido',{id});carregar()}
async function retreinar(){if(!confirm('Atualizar a base de reconhecimento agora?\n\nUsa todos os códigos validados, incluindo os das últimas consultas.\nLeva alguns segundos e o próximo código usa a base atualizada.'))return;
 alert('Atualizando... quando terminar, uma mensagem aparece no terminal do monitor.');await api('retreinar');carregar()}
async function limparBuscas(){if(!confirm('Limpar a lista de buscas?\n\nBuscas ativas continuam rodando em segundo plano,\nmas saem da lista.'))return;await api('limpar_buscas');carregar()}
async function remover(id){if(confirm('Parar de acompanhar este processo?')){await api('remover',{id});carregar()}}
async function verificarAgora(){await api('verificar');carregar();setTimeout(carregar,4000)}
carregar();setInterval(carregar,30000);
</script></body></html>"""

verificando = threading.Event()


def _enviar_nuvem(processo_id):
    """Manda o processo pro Supabase em segundo plano.

    Nunca levanta erro pro monitor: se o Supabase estiver desconfigurado ou
    fora do ar, o acompanhamento local continua funcionando normalmente.
    """
    sync = supabase_sync
    if sync is not None and sync.ativo():
        threading.Thread(
            target=lambda: sync.sincronizar_processo(
                con, processo_id, db_lock=lock),
            daemon=True).start()

    # envia tambem para o Controle de Processos SEMCAS (submenu de acompanhamento)
    if semcas_sync is not None and semcas_sync.ativo():
        threading.Thread(
            target=lambda: _enviar_semcas(processo_id),
            daemon=True).start()


def _enviar_semcas(processo_id):
    """Envia o acompanhamento pro Controle de Processos SEMCAS.

    Igual ao Supabase: qualquer falha e registrada, nunca derruba o monitor.
    """
    try:
        semcas_sync.sincronizar_processo(con, processo_id)
    except Exception as e:
        global semcas_ultimo_erro
        semcas_ultimo_erro = str(e)[:200]
        print(f"[semcas] aviso: {semcas_ultimo_erro}")


def verificar_em_segundo_plano(proc=None):
    def tarefa():
        verificando.set()
        try:
            verificar(proc) if proc else verificar_todos()
        finally:
            verificando.clear()
    threading.Thread(target=tarefa, daemon=True).start()


# ------------------------------------------------- pesquisa automática por número
buscas_em_andamento = {}   # número -> {"estado": ..., "msg": ...}


def pesquisar_e_adicionar(numero, apelido=None, orgao="SEMCAS"):
    """Consulta o numero no SEI (codigo de verificacao automatico) e, ao achar,
    cadastra o processo na lista."""
    estado = buscas_em_andamento.setdefault(
        numero, {"estado": "buscando", "passos": []})

    def ao_progresso(msg):
        estado["passos"] = (estado.get("passos") or [])[-6:] + [msg]

    def tarefa():
        url = None
        # Uma retentativa completa: se o navegador morrer no meio da busca
        # (ex.: duas buscas simultâneas), refaz com navegador novo.
        for chance in (1, 2):
            try:
                from buscar_link_processo import buscar_link
                url = buscar_link(numero, orgao=orgao, oculto=True,
                                  max_tentativas=8, ao_progresso=ao_progresso)
                break
            except Exception as e:
                print(f"[pesquisa] {numero}: tentativa {chance} falhou -> {e}")
                if chance == 2:
                    estado["estado"] = "erro"
                    estado["msg"] = f"Falha na busca: {e}"
                    return
                time.sleep(2)
        if not url:
            estado["estado"] = "nao_encontrado"
            estado["msg"] = "Processo não encontrado (ou código de verificação não reconhecido em 8 tentativas)."
            print(f"[pesquisa] {numero}: não encontrado")
            return
        with lock:
            try:
                cur = con.execute(
                    "INSERT INTO processos(url,apelido,numero,criado_em) VALUES(?,?,?,?)",
                    (url, apelido, numero, datetime.now().isoformat()))
                con.commit()
                proc = dict(con.execute("SELECT * FROM processos WHERE id=?",
                                        (cur.lastrowid,)).fetchone())
            except sqlite3.IntegrityError:
                proc = dict(con.execute("SELECT * FROM processos WHERE url=?",
                                        (url,)).fetchone())
        estado["estado"] = "achou"
        estado["url"] = url
        print(f"[pesquisa] {numero}: achou -> {url}")
        verificar_em_segundo_plano(proc)

    threading.Thread(target=tarefa, daemon=True).start()


class Painel(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def responder(self, corpo, tipo="application/json"):
        dados = corpo.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", tipo + "; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_GET(self):
        if self.path == "/api/lista":
            with lock:
                procs = [dict(p) for p in con.execute(
                    "SELECT p.*, (SELECT COUNT(*) FROM itens i WHERE i.processo_id=p.id AND novo=1) novos "
                    "FROM processos p ORDER BY novos DESC, ultima_novidade DESC, id DESC")]
                for p in procs:
                    p["itens"] = [dict(i) for i in con.execute(
                        "SELECT * FROM itens WHERE processo_id=? ORDER BY CAST(chave AS INTEGER) DESC",
                        (p["id"],))]
            self.responder(json.dumps({"processos": procs, "intervalo": INTERVALO_MIN,
                                       "verificando": verificando.is_set(),
                                       "buscas": buscas_em_andamento,
                                       "supabase": (supabase_sync.status()
                                                    if supabase_sync else
                                                    {"ativo": False})}))
        elif self.path.startswith("/arquivo/"):
            with lock:
                r = con.execute("SELECT arquivo FROM itens WHERE id=?",
                                (self.path.rsplit("/", 1)[-1],)).fetchone()
            caminho = Path(r["arquivo"]) if r and r["arquivo"] else None
            if not caminho or not caminho.is_file():
                self.send_error(404, "Arquivo não encontrado")
                return
            dados = caminho.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf" if caminho.suffix.lower() == ".pdf"
                             else "application/octet-stream")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)
        else:
            self.responder(PAGINA, "text/html")

    def do_POST(self):
        tam = int(self.headers.get("Content-Length") or 0)
        d = json.loads(self.rfile.read(tam) or b"{}")
        acao = self.path.rsplit("/", 1)[-1]
        with lock:
            if acao == "adicionar":
                url = d.get("url", "")
                if not url.startswith("https://sei.saoluis.ma.gov.br/") or "processo_exibir" not in url:
                    return self.responder(json.dumps({"erro": "Cole o link da página do processo "
                                                      "(md_pesq_processo_exibir.php?...)."}))
                try:
                    cur = con.execute("INSERT INTO processos(url,apelido,criado_em) VALUES(?,?,?)",
                                      (url, d.get("apelido"), datetime.now().isoformat()))
                    con.commit()
                except sqlite3.IntegrityError:
                    return self.responder(json.dumps({"erro": "Esse processo já está na lista."}))
                proc = dict(con.execute("SELECT * FROM processos WHERE id=?",
                                        (cur.lastrowid,)).fetchone())
                verificar_em_segundo_plano(proc)
            elif acao == "lido":
                con.execute("UPDATE itens SET novo=0 WHERE processo_id=?", (d["id"],))
                con.commit()
            elif acao == "remover":
                row = con.execute("SELECT url FROM processos WHERE id=?",
                                  (d["id"],)).fetchone()
                con.execute("DELETE FROM itens WHERE processo_id=?", (d["id"],))
                con.execute("DELETE FROM processos WHERE id=?", (d["id"],))
                con.commit()
                if row and supabase_sync is not None:
                    url_rem = row["url"]
                    sync_rem = supabase_sync
                    threading.Thread(
                        target=lambda: sync_rem.remover_processo(url_rem),
                        daemon=True).start()
            elif acao == "limpar_buscas":
                buscas_em_andamento.clear()
                return self.responder(json.dumps({"ok": True}))
            elif acao == "verificar":
                verificar_em_segundo_plano()
            elif acao == "pesquisar":
                numero = (d.get("numero") or "").strip()
                if not numero:
                    return self.responder(json.dumps({"erro": "Informe o número do processo."}))
                if numero in buscas_em_andamento and \
                        buscas_em_andamento[numero].get("estado") == "buscando":
                    return self.responder(json.dumps({"erro": "Essa busca já está em andamento."}))
                pesquisar_e_adicionar(numero, d.get("apelido"),
                                      d.get("orgao") or "SEMCAS")
                return self.responder(json.dumps({"ok": True}))
            elif acao == "retreinar":
                def _retreinar():
                    from sei_captcha_pipeline import treinar_modelo
                    treinar_modelo(salvar=True)
                threading.Thread(target=_retreinar, daemon=True).start()
                return self.responder(json.dumps({"ok": True}))
        self.responder("{}")


def main():
    if "--uma-vez" in sys.argv:
        nov = verificar_todos()
        print(f"Concluído. {len(nov)} novidade(s).")
        return
    if supabase_sync is not None and supabase_sync.ativo():
        print("[supabase] configurado — enviando processos existentes...")
        sync_start = supabase_sync
        threading.Thread(target=lambda: sync_start.sincronizar_tudo(con),
                         daemon=True).start()
    elif supabase_sync is not None:
        print("[supabase] desativado (sem supabase_config.txt). Só local.")
    threading.Thread(target=laco, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORTA), Painel)
    print(f"Painel em http://localhost:{PORTA}  (Ctrl+C para sair)")
    if "--sem-navegador" not in sys.argv:
        webbrowser.open(f"http://localhost:{PORTA}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
