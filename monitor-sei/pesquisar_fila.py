"""
Pesquisa em fila - SEI Sao Luis
Desenvolvido por: Jurandy Santana - WhatsApp: (98) 98401-6496

Le os numeros de processo de 'numeros.txt' (um por linha), pesquisa cada um no
SEI e grava o resultado em 'fila_resultado.csv' (numero;url;quando;erro).

Roda em lotes, pula quem nao achar e continua. Pode ser interrompido e
retomado a qualquer momento: quem ja tem resultado no CSV nao e pesquisado
de novo.

Uso:
    python pesquisar_fila.py              (todos os pendentes)
    python pesquisar_fila.py 100          (so os 100 primeiros pendentes)
    python pesquisar_fila.py --visivel    (mostra o navegador)
"""
import csv
import os
import sys
import time
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
ARQ_NUMEROS = os.path.join(AQUI, "numeros.txt")
ARQ_RESULTADO = os.path.join(AQUI, "fila_resultado.csv")
PAUSA_ENTRE = 3          # segundos entre uma pesquisa e outra (gentileza com o SEI)


def _ja_feitos():
    """Numeros que ja tem resultado gravado (achou ou nao_encontrado)."""
    feitos = {}
    if not os.path.exists(ARQ_RESULTADO):
        return feitos
    with open(ARQ_RESULTADO, "r", encoding="utf-8-sig", newline="") as f:
        for linha in csv.DictReader(f, delimiter=";"):
            if linha.get("numero"):
                feitos[linha["numero"]] = linha
    return feitos


def _refazer_nao_encontrados():
    """Tira os 'nao_encontrado' do arquivo (virao de novo na proxima rodada).

    Serve porque muito 'nao_encontrado' e falso negativo: o codigo de
    verificacao errou varias vezes e o processo nem chegou a ser procurado
    de verdade. Refazendo, esses costumam aparecer.
    """
    if not os.path.exists(ARQ_RESULTADO):
        return 0
    linhas = []
    removidos = 0
    with open(ARQ_RESULTADO, "r", encoding="utf-8-sig", newline="") as f:
        leitor = csv.DictReader(f, delimiter=";")
        campos = leitor.fieldnames or ["numero", "url", "quando", "erro"]
        for linha in leitor:
            if linha.get("erro") == "nao_encontrado":
                removidos += 1
                continue
            linhas.append(linha)
    with open(ARQ_RESULTADO, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, delimiter=";", fieldnames=campos)
        w.writeheader()
        w.writerows(linhas)
    return removidos


def _gravar(numero, url, erro):
    novo = not os.path.exists(ARQ_RESULTADO)
    with open(ARQ_RESULTADO, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        if novo:
            w.writerow(["numero", "url", "quando", "erro"])
        w.writerow([numero, url or "", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), erro or ""])


def main():
    limite = None
    visivel = "--visivel" in sys.argv
    for a in sys.argv[1:]:
        if a.isdigit():
            limite = int(a)

    if "--refazer" in sys.argv:
        n = _refazer_nao_encontrados()
        print(f"[fila] {n} 'nao encontrado' foram liberados para nova tentativa")

    if not os.path.exists(ARQ_NUMEROS):
        print(f"[fila] arquivo nao encontrado: {ARQ_NUMEROS}")
        return 1

    with open(ARQ_NUMEROS, "r", encoding="utf-8") as f:
        todos = [l.strip() for l in f if l.strip()]

    feitos = _ja_feitos()
    pendentes = [n for n in todos if n not in feitos]
    if limite:
        pendentes = pendentes[:limite]

    print(f"[fila] total: {len(todos)} | ja pesquisados: {len(feitos)} | nesta rodada: {len(pendentes)}")
    if not pendentes:
        print("[fila] nada pendente. Fim.")
        return 0

    from buscar_link_processo import buscar_link

    achou = nao_achou = falhou = 0
    t0 = time.time()
    for i, numero in enumerate(pendentes, 1):
        try:
            url = buscar_link(numero, "SEMCAS", oculto=not visivel, max_tentativas=8, verbose=False)
            if url:
                _gravar(numero, url, "")
                achou += 1
                marca = "OK"
            else:
                _gravar(numero, "", "nao_encontrado")
                nao_achou += 1
                marca = "nao achou"
        except Exception as e:
            _gravar(numero, "", f"erro: {e}")
            falhou += 1
            marca = f"erro ({e})"

        decorrido = time.time() - t0
        ritmo = decorrido / i
        resta = ritmo * (len(pendentes) - i)
        print(f"[{i}/{len(pendentes)}] {numero}: {marca} | "
              f"ok={achou} sem={nao_achou} err={falhou} | "
              f"faltam ~{resta/60:.0f} min", flush=True)
        time.sleep(PAUSA_ENTRE)

    print(f"\n[fila] FIM. achou={achou} nao_achou={nao_achou} erro={falhou}")
    print(f"[fila] resultado em: {ARQ_RESULTADO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
