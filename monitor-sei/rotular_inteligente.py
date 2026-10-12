#!/usr/bin/env python3
"""
rotular_inteligente.py
======================
Coleta + rotula com interface "só confirma o que está errado":

- Baixa um captcha novo e já roda a pipeline.
- Cada um dos 6 caracteres aparece em uma CAIXA GRANDE separada:
  verde se a pipeline tem certeza, amarelo se duvidou, vermelho se chutou.
- Embaixo de cada caixa, até 3 botões com as alternativas mais prováveis.
- Enter: aceita como está e já pede o próximo captcha.
- Clicar no botão certo troca aquele caractere sozinho.
- Ou digita direto no campo. Tab anda entre os caracteres.
- Esc: pula sem salvar.
- ← Voltar: volta ao último.
- A cada 10 rótulos, a pipeline aprende de novo.
"""

import queue, threading, time
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk
from pathlib import Path

from playwright.sync_api import sync_playwright

import sei_captcha_pipeline as p

ESCALA = 4
CARACTERES_VALIDOS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
TOP_K = 3        # quantos botões de alternativa mostrar por caractere
MARGEM_OK = 0.08 # verde se a margem for >= isto
MARGEM_DUVIDA = 0.03

URL_PESQUISA = (
    "https://sei.saoluis.ma.gov.br/sei/modulos/pesquisa/"
    "md_pesq_processo_pesquisar.php?acao_externa=protocolo_pesquisar"
    "&acao_origem_externa=protocolo_pesquisar&id_orgao_acesso_externo=0"
)


def salvar_rotulos(rotulos):
    with open(p.ROTULOS_FILE, 'w', encoding='utf-8') as f:
        for cid in sorted(rotulos):
            f.write(f"{cid} = {rotulos[cid]}\n")


def proximo_nome():
    p.CAPTCHAS_DIR.mkdir(exist_ok=True)
    existentes = sorted(p.CAPTCHAS_DIR.glob("captcha_*.png"))
    ultimo = int(existentes[-1].stem.split("_")[1]) if existentes else 0
    return p.CAPTCHAS_DIR / f"captcha_{ultimo + 1:04d}.png"


def predizer_detalhado(caminho, templates, modelo, limiar):
    """
    Para cada caractere do captcha, devolve:
    (palpite, [(classe, score), ...] top-K, cor pela margem).
    Se `modelo` (SVM) existir, usa ele. Senão, cai nos templates.
    """
    ink = p.preprocess(caminho)
    boxes = p.segmentar_caracteres(ink)
    resultados = []
    for x1, y1, x2, y2 in boxes:
        feat = p.extrair_features(ink[y1:y2, x1:x2])
        if feat is None:
            resultados.append(('?', [], '#f5b0b0')); continue
        if modelo is not None:
            top = p.predizer_topk(feat, modelo, k=TOP_K)
        else:
            scores = {}
            for cls, exs in templates.items():
                if exs:
                    scores[cls] = max(p.coseno_similarity(feat, e) for e in exs)
            top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:TOP_K]
        if not top:
            resultados.append(('?', [], '#f5b0b0')); continue
        c1, s1 = top[0]
        s2 = top[1][1] if len(top) > 1 else 0
        margem = s1 - s2
        if margem >= MARGEM_OK:
            cor = '#c6f0c0'   # verde
        elif margem >= MARGEM_DUVIDA:
            cor = '#fff0b0'   # amarelo
        else:
            cor = '#f5b0b0'   # vermelho
        resultados.append((c1, top, cor))
    while len(resultados) < p.N_CARACTERES:
        resultados.append(('?', [], '#f5b0b0'))
    return resultados[:p.N_CARACTERES]


class Capturador(threading.Thread):
    """Thread do navegador. À prova de morte: qualquer falha (página demorar,
    elemento sumir, rede oscilar, navegador fechado) gera recuperação
    automática — recarrega a página ou reabre o navegador — em vez de
    congelar a janela esperando um captcha que nunca vem."""

    def __init__(self, pedidos, respostas):
        super().__init__(daemon=True)
        self.pedidos, self.respostas = pedidos, respostas
        self._sair = False

    def run(self):
        while not self._sair:
            pw = None
            browser = None
            try:
                # driver e navegador NOVOS a cada recuperacao: quando o navegador
                # morre, o driver fica zumbi e o proximo launch travaria sem timeout
                pw = sync_playwright().start()
                browser = pw.chromium.launch(headless=False, timeout=30000)
                ctx = browser.new_context(viewport={"width": 1280, "height": 720})
                page = ctx.new_page()
                # abrir a página com retry (SEI às vezes demora/oscila)
                for tent in range(3):
                    try:
                        page.goto(URL_PESQUISA, wait_until="domcontentloaded")
                        page.wait_for_selector("#txtProtocoloPesquisa", timeout=45000)
                        break
                    except Exception as e:
                        if tent == 2:
                            raise RuntimeError(f"não consegui abrir a página do SEI: {e}")
                        self.respostas.put({'erro': f"página demorou ({e}), tentando de novo..."})
                        time.sleep(3)
                btn = page.locator("#infraImgRecarregarCaptcha")
                img = page.locator("#imgCaptcha, #imgInfraCaptcha")
                if img.count() == 0 or btn.count() == 0:
                    raise RuntimeError("captcha não encontrado na página do SEI")
                primeiro = True
                while not self._sair:
                    msg = self.pedidos.get()
                    if msg == "sair":
                        self._sair = True
                        break
                    try:
                        if not primeiro:
                            btn.first.click(); time.sleep(0.4)
                        primeiro = False
                        b = img.first.screenshot()
                        caminho = proximo_nome()
                        caminho.write_bytes(b)
                        self.respostas.put({'path': caminho})
                    except Exception as e:
                        # erro pontual: recarrega a página e segue no mesmo navegador
                        self.respostas.put({'erro': f"{e} — recarregando a página"})
                        try:
                            page.reload(wait_until="domcontentloaded")
                            page.wait_for_selector("#txtProtocoloPesquisa", timeout=45000)
                        except Exception:
                            raise  # nem recarregar funcionou: reinicia o navegador (while externo)
                        primeiro = True
            except Exception as e:
                self.respostas.put({'erro': f"Navegador caiu ({e}). Reabrindo em 3s..."})
                time.sleep(3)
            finally:
                if browser is not None:
                    try: browser.close()
                    except Exception: pass
                if pw is not None:
                    try: pw.stop()   # mata driver zumbi — sem isso o proximo launch trava
                    except Exception: pass


class Janela:
    def __init__(self, root):
        self.root = root
        self.rotulos = p.carregar_rotulos()
        self.modelo = p.carregar_modelo(treinar_se_faltar=False)
        self.templates = None if self.modelo is not None else p.carregar_templates()
        self.rotulos_desde_treino = 0
        self.historico = []
        self.atual_path = None
        self.vars_chars = []     # 6 StringVars
        self.caixas_chars = []   # 6 Entrys
        self.frames_botoes = []  # 6 frames com botões
        self.pedidos = queue.Queue(); self.respostas = queue.Queue()
        self.capturador = Capturador(self.pedidos, self.respostas); self.capturador.start()

        root.title("Rotulagem inteligente - SEI")
        root.protocol("WM_DELETE_WINDOW", self.fechar)

        self.lbl_status = tk.Label(root, font=("Segoe UI", 11))
        self.lbl_status.pack(pady=(10, 4))
        self.lbl_img = tk.Label(root)
        self.lbl_img.pack(padx=10)
        self.lbl_limpa = tk.Label(root)
        self.lbl_limpa.pack(padx=10, pady=(4, 0))
        tk.Label(root, text="Verde = certeza   Amarelo = dúvida   Vermelho = chute",
                 font=("Segoe UI", 9), fg="gray").pack(pady=(2, 0))

        area = tk.Frame(root); area.pack(pady=10)
        for i in range(p.N_CARACTERES):
            col = tk.Frame(area); col.pack(side="left", padx=4)
            v = tk.StringVar()
            v.trace_add("write", self._maiusculas)
            e = tk.Entry(col, textvariable=v, font=("Consolas", 32),
                         width=2, justify="center", bg="white")
            e.pack()
            self.vars_chars.append(v); self.caixas_chars.append(e)
            fb = tk.Frame(col); fb.pack(pady=(2, 0))
            self.frames_botoes.append(fb)

        self.lbl_aviso = tk.Label(root, fg="red", font=("Segoe UI", 10))
        self.lbl_aviso.pack()

        botoes = tk.Frame(root); botoes.pack(pady=(4, 12))
        tk.Button(botoes, text="← Voltar", width=10, command=self.voltar).pack(side="left", padx=4)
        tk.Button(botoes, text="Pular (Esc)", width=12, command=self.pular).pack(side="left", padx=4)
        tk.Button(botoes, text="OK, salvar (Enter)", width=16, command=self.salvar).pack(side="left", padx=4)

        root.bind("<Return>", lambda e: self.salvar())
        root.bind("<Escape>", lambda e: self.pular())

        self.lbl_status.config(text="Abrindo o navegador...")
        self.pedir_proximo()
        root.after(200, self.verificar_resposta)

    def _maiusculas(self, *_):
        for v in self.vars_chars:
            s = v.get()
            if s != s.upper(): v.set(s.upper())
            if len(s) > 1: v.set(s[-1])

    def pedir_proximo(self):
        self.lbl_status.config(text="Baixando próximo captcha...")
        for e in self.caixas_chars: e.config(state="disabled")
        self.pedidos.put("próximo")

    def verificar_resposta(self):
        try:
            while True:
                r = self.respostas.get_nowait()
                if 'erro' in r:
                    self.lbl_aviso.config(text=f"Erro: {r['erro']}")
                    self.root.after(2000, self.pedir_proximo)
                else:
                    self.mostrar(r['path'])
        except queue.Empty:
            pass
        self.root.after(200, self.verificar_resposta)

    def mostrar(self, caminho):
        self.atual_path = caminho
        self.lbl_status.config(
            text=f"{caminho.name}   rotulados: {len(self.rotulos)}   (fecha a janela quando quiser)"
        )

        img = Image.open(caminho).convert("L")
        grande = img.resize((img.width * ESCALA, img.height * ESCALA), Image.NEAREST)
        self.foto_img = ImageTk.PhotoImage(grande)
        self.lbl_img.config(image=self.foto_img)

        try:
            ink = p.preprocess(caminho)
            limpa = Image.fromarray(255 - ink)
            limpa = limpa.resize((limpa.width * ESCALA, limpa.height * ESCALA), Image.NEAREST)
            self.foto_limpa = ImageTk.PhotoImage(limpa)
            self.lbl_limpa.config(image=self.foto_limpa, text="")
        except Exception as e:
            self.lbl_limpa.config(image="", text=f"preprocess falhou: {e}")

        resultados = predizer_detalhado(caminho, self.templates or {}, self.modelo, 0)
        for i, (palp, top, cor) in enumerate(resultados):
            e = self.caixas_chars[i]
            e.config(state="normal", bg=cor)
            self.vars_chars[i].set(palp if palp != '?' else '')
            # alternativas
            fb = self.frames_botoes[i]
            for w in fb.winfo_children(): w.destroy()
            for cls, score in top:
                def _troca(ch=cls, idx=i):
                    self.vars_chars[idx].set(ch)
                    self.caixas_chars[idx].config(bg='#c6f0c0')
                tk.Button(fb, text=cls, width=2, font=("Consolas", 11),
                          command=_troca).pack(side="top", pady=1)

        self.lbl_aviso.config(text="")
        self.caixas_chars[0].focus_set()
        self.caixas_chars[0].select_range(0, tk.END)

    def ler_codigo(self):
        return ''.join(v.get() for v in self.vars_chars)

    def salvar(self):
        if self.atual_path is None: return
        codigo = self.ler_codigo().strip().upper()
        if len(codigo) != p.N_CARACTERES or not set(codigo) <= CARACTERES_VALIDOS:
            self.lbl_aviso.config(text=f"Preencha os {p.N_CARACTERES} caracteres")
            return
        cid = self.atual_path.stem.upper()
        self.rotulos[cid] = codigo
        salvar_rotulos(self.rotulos)
        self.historico.append((self.atual_path, codigo))
        self.rotulos_desde_treino += 1
        # Retreina o SVM a cada 25 rótulos novos (o treino com aumento leva ~30s)
        if self.rotulos_desde_treino >= 25:
            self.lbl_status.config(text="Retreinando o modelo (aguarde ~30s)...")
            self.root.update()
            try:
                novo = p.treinar_modelo()
                if novo is not None:
                    self.modelo = novo
                    self.rotulos_desde_treino = 0
            except Exception as e:
                print(f"[-] Falha ao retreinar: {e}")
        self.atual_path = None
        self.pedir_proximo()

    def pular(self):
        if self.atual_path is None: return
        self.historico.append((self.atual_path, None))
        self.atual_path = None
        self.pedir_proximo()

    def voltar(self):
        if not self.historico: return
        caminho, _ = self.historico.pop()
        self.mostrar(caminho)
        cid = caminho.stem.upper()
        if cid in self.rotulos:
            for v, ch in zip(self.vars_chars, self.rotulos[cid]):
                v.set(ch)

    def fechar(self):
        try: self.pedidos.put("sair")
        except Exception: pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    Janela(root)
    root.mainloop()
