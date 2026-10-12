"""
buscar_link_processo.py
-----------------------
Modulo de consulta processual: recebe o numero do processo e devolve a URL
da pagina do processo no SEI (md_pesq_processo_exibir.php?...), com
preenchimento automatico do codigo de verificacao de imagem.

Desenvolvido por: Jurandy Santana
WhatsApp: (98) 98401-6496

Uso como biblioteca:
    from buscar_link_processo import buscar_link
    url = buscar_link("25101.006859/2026", orgao="SEMCAS", headless=True)

Uso na linha de comando (teste):
    python buscar_link_processo.py 25101.006859/2026 [SEMCAS]
"""

import sys
import time
import urllib.parse
from pathlib import Path
from playwright.sync_api import sync_playwright

URL_PESQUISA = (
    "https://sei.saoluis.ma.gov.br/sei/modulos/pesquisa/"
    "md_pesq_processo_pesquisar.php?acao_externa=protocolo_pesquisar"
    "&acao_origem_externa=protocolo_pesquisar&id_orgao_acesso_externo=0"
)

LINKS_PROCESSO = (
    "a[href*='md_pesq_processo_exibir'], a[href*='procedimento_trabalhar']"
)

PASTA = Path(__file__).resolve().parent
CAPTCHAS_DIR = PASTA / "captchas"
PADROES_FILE = PASTA / "rotulos.txt"


def _proximo_id():
    """Próximo número livre de CAPTCHA_XXXX, baseado nas imagens existentes."""
    existentes = [int(p.stem.split("_")[1]) for p in CAPTCHAS_DIR.glob("captcha_*.png")
                  if p.stem.split("_")[-1].isdigit()]
    return max(existentes, default=0) + 1


def _salvar_padrao_validado(img_bytes, codigo):
    """Guarda o codigo de verificacao aceito pelo SEI como novo padrao da base.

    O SEI so deixa passar quando o codigo esta certo, entao aceitacao e
    acerto comprovado — nao precisa revisao humana.
    """
    try:
        CAPTCHAS_DIR.mkdir(exist_ok=True)
        cid = f"CAPTCHA_{_proximo_id():04d}"
        (CAPTCHAS_DIR / f"{cid.lower()}.png").write_bytes(img_bytes)
        with open(PADROES_FILE, "a", encoding="utf-8") as f:
            f.write(f"{cid} = {codigo.upper()}\n")
        print(f"[base] novo padrao validado: {cid} = {codigo.upper()}")
        return cid
    except Exception as e:
        print(f"[base] falha ao salvar padrao: {e}")
        return None


def _carregar_reconhecedor():
    """Base de padroes; fallback para templates se o modelo nao abrir."""
    modelo, templates = None, None
    try:
        from sei_captcha_pipeline import carregar_modelo, carregar_templates
        modelo = carregar_modelo(treinar_se_faltar=False)
        if modelo is None:
            templates = carregar_templates()
    except Exception as e:
        print(f"[busca] Falha ao carregar reconhecedor: {e}")
    return modelo, templates


def _preparar_formulario(page, processo, orgao):
    page.goto(URL_PESQUISA, wait_until="domcontentloaded")
    # espera o campo existir em vez de networkidle (página do SEI tem
    # conexões que ficam abertas e o networkidle pode nunca disparar)
    page.wait_for_selector("#txtProtocoloPesquisa", timeout=45000)
    page.fill("#txtProtocoloPesquisa", processo)
    chk = page.locator("#chkSinProcessos")
    if chk.count() > 0 and not chk.is_checked():
        chk.check()
    try:
        btn_choice = page.locator("button.ms-choice")
        if btn_choice.count() > 0:
            btn_choice.first.click()
            time.sleep(0.3)
            label = page.locator(f"li label:has-text('{orgao}')")
            if label.count() > 0:
                label.first.click()
            btn_choice.first.click()
    except Exception:
        pass
    page.evaluate("""() => {
        const select = document.querySelector('#selOrgaoPesquisa')
                     || document.querySelector('#lblOrgaoPesquisa');
        if (select) {
            for (let opt of select.options) {
                opt.selected = opt.text.toUpperCase().includes('%s');
            }
            if (window.$ && $(select).multipleSelect) {
                try { $(select).multipleSelect('refresh'); } catch(e) {}
            }
        }
    }""" % orgao.upper())


def _resolver_captcha(img_bytes, modelo, templates):
    from sei_captcha_pipeline import resolver_captcha
    return resolver_captcha(img_bytes, modelo=modelo, templates=templates)


def buscar_link(processo, orgao="SEMCAS", oculto=True,
                max_tentativas=8, verbose=True, ao_progresso=None):
    """
    Pesquisa o processo no SEI e devolve a URL do primeiro resultado.
    Devolve None se nao achar (codigo nao reconhecido ou processo inexistente).

    `oculto=True` (padrão): a janela do navegador abre fora da área visível
    da tela (coordenadas negativas). Headless puro é barrado pelo Cloudflare,
    e janela visível atrapalha — essa é a saída: headful, mas invisível.
    `oculto=False`: abre a janela na tela (útil para acompanhar/depurar).
    """
    modelo, templates = _carregar_reconhecedor()
    if modelo is None and not templates:
        print("[busca] Base de reconhecimento indisponivel (verifique sei_captcha_pipeline).")

    def log(msg):
        if verbose:
            print(f"[busca] {msg}")
        if ao_progresso:
            try:
                ao_progresso(msg)
            except Exception:
                pass

    def ja_achou():
        return len(page.locator(LINKS_PROCESSO).all()) > 0

    def sei_recusou():
        try:
            t = page.locator("body").inner_text().lower()
        except Exception:
            return False
        return any(x in t for x in (
            "inválido", "invalido", "não confere", "nao confere",
            "código de confirmação", "codigo de confirmacao",
            "nenhum processo", "não encontrado",
        ))

    def recarregar():
        try:
            page.click("#infraImgRecarregarCaptcha", timeout=3000)
        except Exception:
            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector("#txtProtocoloPesquisa", timeout=45000)
            _preparar_formulario(page, processo, orgao)
            time.sleep(1.2)

    args_lancamento = [
        # --no-sandbox: obrigatório para Chromium como root no container Linux
        "--no-sandbox",
        # --disable-dev-shm-usage: o /dev/shm do Docker é minúsculo (64MB) e
        # faz o Chromium travar sem erro — usar disco no lugar.
        "--disable-dev-shm-usage",
        "--disable-gpu",
    ]
    if oculto:
        args_lancamento += ["--window-position=-4000,-4000", "--window-size=1200,800"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=args_lancamento)
        context = browser.new_context(viewport={"width": 1366, "height": 800})
        page = context.new_page()
        try:
            _preparar_formulario(page, processo, orgao)

            for tent in range(1, max_tentativas + 1):
                captcha_el = page.locator("#imgCaptcha, #imgInfraCaptcha")
                if captcha_el.count() == 0:
                    log("captcha não encontrado, recarregando página")
                    page.reload(wait_until="domcontentloaded")
                    page.wait_for_selector("#txtProtocoloPesquisa", timeout=45000)
                    _preparar_formulario(page, processo, orgao)
                    continue

                try:
                    img_bytes = captcha_el.first.screenshot()
                    result = _resolver_captcha(img_bytes, modelo, templates)
                    codigo = result['codigo']
                    log(f"tentativa {tent}: leu '{codigo}' "
                        f"(certeza {result['confianca']:.2f})")
                except Exception as e:
                    log(f"tentativa {tent}: erro no solver ({e})")
                    recarregar()
                    continue

                if not codigo or len(codigo) < 5:
                    log("leitura incompleta, gerando novo codigo")
                    recarregar()
                    continue

                page.fill("#txtInfraCaptcha", codigo[:6])
                time.sleep(0.4)
                try:
                    page.click("#sbmPesquisar")
                except Exception as e:
                    log(f"falha ao clicar em Pesquisar: {e}")
                    continue
                time.sleep(3)

                if ja_achou():
                    href = page.locator(LINKS_PROCESSO).first.get_attribute("href")
                    url = urllib.parse.urljoin(URL_PESQUISA, href or "")
                    log(f"achou: {url}")
                    # O SEI aceitou o código, então ele está certo:
                    # vira padrao novo para a proxima atualizacao da base.
                    _salvar_padrao_validado(img_bytes, codigo)
                    return url

                if sei_recusou():
                    log("SEI recusou o captcha, tentando outro")
                    recarregar()
                    continue

                if page.locator("#txtInfraCaptcha").count() > 0:
                    log("sem confirmação de sucesso, tentando outro captcha")
                    recarregar()
                    continue
                break
        finally:
            browser.close()
    return None


if __name__ == "__main__":
    proc = sys.argv[1] if len(sys.argv) > 1 else "25101.006859/2026"
    org = sys.argv[2] if len(sys.argv) > 2 else "SEMCAS"
    visivel = "--visivel" in sys.argv
    achou = buscar_link(proc, org, oculto=not visivel)
    print("URL:", achou or "(não encontrado)")
