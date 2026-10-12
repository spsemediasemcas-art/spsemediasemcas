"""
Importar resultados da fila para o monitor
Desenvolvido por: Jurandy Santana - WhatsApp: (98) 98401-6496

Le 'fila_resultado.csv' (gerado pelo pesquisar_fila.py), pega os processos
que foram encontrados e cadastra no banco do monitor (sei_monitor.db) e, se
o Supabase estiver ligado, envia para lá também.

Roda quantas vezes quiser: processo que já está no monitor nao e duplicado.

Uso:
    python importar_fila.py
    python importar_fila.py --enviar-nuvem
"""
import csv
import os
import sys
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
ARQ_RESULTADO = os.path.join(AQUI, "fila_resultado.csv")


def main():
    enviar_nuvem = "--enviar-nuvem" in sys.argv

    if not os.path.exists(ARQ_RESULTADO):
        print(f"[importar] nao encontrei {ARQ_RESULTADO} - rode o pesquisar_fila.py primeiro.")
        return 1

    import sei_monitor as m

    achados = []
    with open(ARQ_RESULTADO, "r", encoding="utf-8-sig", newline="") as f:
        for linha in csv.DictReader(f, delimiter=";"):
            if linha.get("numero") and linha.get("url"):
                achados.append(linha)

    print(f"[importar] {len(achados)} processos com link no arquivo")

    novos = repetidos = 0
    ids_novos = []
    for linha in achados:
        url, numero = linha["url"].strip(), linha["numero"].strip()
        ja = m.con.execute("SELECT id FROM processos WHERE url=?", (url,)).fetchone()
        if ja:
            repetidos += 1
            continue
        cur = m.con.execute(
            "INSERT INTO processos(url,apelido,numero,criado_em) VALUES(?,?,?,?)",
            (url, numero, numero, datetime.now().isoformat(timespec="seconds")))
        m.con.commit()
        novos += 1
        ids_novos.append(cur.lastrowid)

    print(f"[importar] novos: {novos} | ja existiam: {repetidos}")

    if enviar_nuvem and ids_novos:
        try:
            import supabase_sync as sb
            if sb.ativo():
                print(f"[importar] enviando {len(ids_novos)} processos para a nuvem...")
                for pid in ids_novos:
                    sb.sincronizar_processo(m.con, pid)
                print("[importar] nuvem: envio concluido")
            else:
                print("[importar] Supabase desligado (sem supabase_config.txt) - nada enviado")
        except Exception as e:
            print(f"[importar] aviso: falha ao enviar para a nuvem: {e}")

    if novos:
        print(f"[importar] baixando o conteudo dos {novos} processos novos...")
        for pid in ids_novos:
            try:
                m.verificar_em_segundo_plano(pid)
            except Exception as e:
                print(f"[importar] aviso: processo {pid} falhou na verificacao: {e}")

    print("[importar] FIM. Abra o monitor para ver os processos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
