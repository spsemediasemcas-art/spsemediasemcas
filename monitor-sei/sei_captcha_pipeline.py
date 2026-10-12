#!/usr/bin/env python3
"""
sei_captcha_pipeline.py
=======================
Reconhecimento dos codigos de verificacao de imagem do SEI Sao Luis-MA.
Base de padroes: rotulos.txt + modelo modelo_svm.pkl.

Desenvolvido por: Jurandy Santana
WhatsApp: (98) 98401-6496

Uso: python sei_captcha_pipeline.py --captcha captcha_0001.png
     python sei_captcha_pipeline.py --batch captchas/

Fases:
    0: Auditoria do dataset
    1: Pre-processamento robusto
    2: Segmentacao de caracteres
    3: Dataset de glifos
    4: Reconhecedor (vizinho mais proximo, templates de rotulos.txt)
    5: Politica de submissao
"""

import sys
import argparse
import json
import pickle
import cv2
import numpy as np
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent
MODELO_FILE = BASE_DIR / "modelo_svm.pkl"
POLITICA_FILE = BASE_DIR / "politica.json"
# Padrão: aceita se a probabilidade mínima do captcha for >= isto
LIMIAR_PROB_PADRAO = 0.76


# ============================================================
# FASE 0: Pré-requisitos
# ============================================================

ROTULOS_FILE = BASE_DIR / "rotulos.txt"
SPLIT_FILE = BASE_DIR / "dataset_split.json"
CAPTCHAS_DIR = BASE_DIR / "captchas"
DEBUG_FASE1 = BASE_DIR / "debug_fase1"
GLIFOS_DIR = BASE_DIR / "glifos"
GLIFOS_CLASE_DIR = BASE_DIR / "glifos_por_classe"
CONFUSOES = {
    '7': ['Z'], 'Z': ['7'],
    'V': ['Y'], 'Y': ['V'],
    'G': ['2', '6'], '2': ['G'], '6': ['G'],
    '1': ['I'], 'I': ['1'],
    'O': ['0', '9'], '9': ['O', '0'], '0': ['O'],
    'A': ['4'], '4': ['A'],
    '5': ['S'], 'S': ['5'],
    '8': ['B'], 'B': ['8'],
    'U': ['V'], 'V': ['U'],
}


def normalizar_glifo(img):
    """Normaliza glifo para 32x32 float32 [0,1]"""
    if img is None:
        return None
    if img.dtype != np.uint8:
        img = img.astype(np.uint8)
    if np.mean(img) > 127:
        img = 255 - img
    coords = np.where(img > 0)
    if len(coords[0]) == 0:
        return None
    y_min, y_max = int(coords[0].min()), int(coords[0].max())
    x_min, x_max = int(coords[1].min()), int(coords[1].max())
    glifo_cortado = img[y_min:y_max+1, x_min:x_max+1]
    h, w = glifo_cortado.shape
    scale = 26.0 / max(h, w)
    new_h = max(1, int(h * scale))
    new_w = max(1, int(w * scale))
    glifo_resized = cv2.resize(glifo_cortado, (new_w, new_h), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((32, 32), dtype=np.float32)
    start_y = (32 - new_h) // 2
    start_x = (32 - new_w) // 2
    canvas[start_y:start_y+new_h, start_x:start_x+new_w] = glifo_resized.astype(np.float32) / 255.0
    return canvas.flatten()


def coseno_similarity(a, b):
    """Similaridade de cosseno entre dois vetores"""
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


# ============================================================
# FASE 1: Pré-processamento
# ============================================================

def preprocess(caminho_ou_bytes, remover_linhas=True):
    """Pipeline de pré-processamento robusto"""
    if isinstance(caminho_ou_bytes, (bytes, bytearray)):
        arr = np.frombuffer(caminho_ou_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    else:
        caminho = Path(caminho_ou_bytes)
        if not caminho.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")
        img = cv2.imread(str(caminho), cv2.IMREAD_GRAYSCALE)
    
    if img is None:
        raise ValueError(f"Falha ao carregar imagem: {caminho_ou_bytes}")
    
    # 1. Suavização inicial (remove o "sal" de pontos isolados)
    img_blur = cv2.medianBlur(img, 3)

    # 2. Binarização Otsu com polaridade TINTA=255, FUNDO=0
    _, ink = cv2.threshold(img_blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # 3. Remoção de linhas: as linhas do SEI têm ~2px e os traços das letras ~4-5px,
    #    então uma abertura 3x3 apaga as linhas sem cortar as letras.
    #    (O HoughLinesP antigo apagava pedaços de V, Y, 7, G...)
    if remover_linhas:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, kernel)

    # 4. Limpeza de ruído por área
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    out = np.zeros_like(ink)
    for i in range(1, num_labels):
        x, y, w, h, area = stats[i]
        if area >= 25 and h >= 6:
            out[labels == i] = 255

    return out


# ============================================================
# FASE 2: Segmentação
# ============================================================

N_CARACTERES = 6


def segmentar_caracteres(ink_img, n_expected=N_CARACTERES):
    """
    Segmenta caracteres por colunas com tinta.
    1. Acha "corridas" de colunas com >=2 pixels de tinta.
    2. Se houver corridas demais, junta o par vizinho mais estreito.
    3. Se houver de menos, divide a corrida mais larga no vale da projeção.
    """
    h, w = ink_img.shape
    col = (ink_img > 0).sum(axis=0)
    ativo = col >= 2

    corridas = []
    inicio = None
    for x, v in enumerate(ativo):
        if v and inicio is None:
            inicio = x
        elif not v and inicio is not None:
            corridas.append([inicio, x])
            inicio = None
    if inicio is not None:
        corridas.append([inicio, w])

    # Descarta fragmentos pequenos (resto de linha/ruído)
    corridas = [c for c in corridas
                if c[1] - c[0] >= 3 and np.count_nonzero(ink_img[:, c[0]:c[1]]) >= 40]

    if n_expected:
        while len(corridas) > n_expected:
            larguras = [corridas[i+1][1] - corridas[i][0] for i in range(len(corridas)-1)]
            i = int(np.argmin(larguras))
            corridas[i] = [corridas[i][0], corridas[i+1][1]]
            corridas.pop(i+1)

        while 0 < len(corridas) < n_expected:
            i = int(np.argmax([c[1] - c[0] for c in corridas]))
            a, b = corridas[i]
            faltam = n_expected - len(corridas)
            # ~20px por caractere: decide em quantos pedaços dividir
            k = min(max(2, round((b - a) / 20)), faltam + 1)
            cortes = []
            for j in range(1, k):
                c = a + int((b - a) * j / k)
                lo, hi = max(a + 4, c - 5), min(b - 4, c + 6)
                cortes.append(lo + int(np.argmin(col[lo:hi])) if hi > lo else c)
            bordas = [a] + cortes + [b]
            corridas[i:i+1] = [[bordas[j], bordas[j+1]] for j in range(k)]

    return [(int(a), 0, int(b), h) for a, b in corridas]


# ============================================================
# FASE 4/5: Reconhecimento com política de rejeição
# ============================================================

def extrair_features(glifo):
    """Pixels suavizados + histograma de gradientes (tipo HOG) em blocos 8x8"""
    vetor = normalizar_glifo(glifo)
    if vetor is None:
        return None
    im = vetor.reshape(32, 32)
    gx = cv2.Sobel(im, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(im, cv2.CV_32F, 0, 1)
    mag = np.hypot(gx, gy)
    bins = np.minimum(((np.arctan2(gy, gx) % np.pi) / np.pi * 9).astype(int), 8)
    hist = []
    for y in range(0, 32, 8):
        for x in range(0, 32, 8):
            hist.append(np.bincount(bins[y:y+8, x:x+8].ravel(),
                                    mag[y:y+8, x:x+8].ravel(), minlength=9))
    hist = np.concatenate(hist)
    hist /= np.linalg.norm(hist) + 1e-6
    pixels = cv2.GaussianBlur(im, (5, 5), 0).ravel() / 20.0
    return np.concatenate([hist, pixels]).astype(np.float32)


def carregar_rotulos():
    """Lê rotulos.txt -> {'CAPTCHA_0001': 'LNJC9C', ...}"""
    rotulos = {}
    if ROTULOS_FILE.exists():
        with open(ROTULOS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                if '=' in line:
                    cid, codigo = line.split('=', 1)
                    rotulos[cid.strip()] = codigo.strip().upper()
    return rotulos


def glifos_rotulados(rotulos=None):
    """Gera (captcha_id, caractere, features) usando a MESMA pipeline da produção"""
    if rotulos is None:
        rotulos = carregar_rotulos()
    amostras = []
    for cid, codigo in sorted(rotulos.items()):
        caminho = CAPTCHAS_DIR / f"{cid.lower()}.png"
        if not caminho.exists():
            print(f"  [!] {cid}: imagem não encontrada ({caminho.name})")
            continue
        if len(codigo) != N_CARACTERES:
            print(f"  [!] {cid}: rótulo '{codigo}' não tem {N_CARACTERES} caracteres, ignorado")
            continue
        ink = preprocess(caminho)
        for (x1, y1, x2, y2), char in zip(segmentar_caracteres(ink), codigo):
            feat = extrair_features(ink[y1:y2, x1:x2])
            if feat is not None:
                amostras.append((cid, char, feat))
    return amostras


def carregar_templates():
    """Templates por classe gerados direto de rotulos.txt + captchas/"""
    templates = defaultdict(list)
    for _, char, feat in glifos_rotulados():
        templates[char].append(feat)
    return dict(templates)


# ============================================================
# Classificador SVM treinado (opcional, mais preciso)
# ============================================================

def _augment_glyph(glifo_ink):
    """Pequenas variações do glifo binarizado para o treino."""
    h, w = glifo_ink.shape
    saida = [glifo_ink]
    for ang in (-6, 6):
        M = cv2.getRotationMatrix2D((w/2, h/2), ang, 1.0)
        saida.append(cv2.warpAffine(glifo_ink, M, (w, h), borderValue=0))
    for dx, dy in ((-2, 0), (2, 0), (0, -1), (0, 1)):
        M = np.float32([[1, 0, dx], [0, 1, dy]])
        saida.append(cv2.warpAffine(glifo_ink, M, (w, h), borderValue=0))
    return saida


def treinar_modelo(salvar=True):
    """Treina SVM RBF com data augmentation a partir de rotulos.txt + captchas/."""
    try:
        from sklearn.svm import SVC
    except ImportError:
        print("[-] sklearn não instalado. Rode: pip install scikit-learn")
        return None

    rotulos = carregar_rotulos()
    X, y = [], []
    for cid, codigo in sorted(rotulos.items()):
        caminho = CAPTCHAS_DIR / f"{cid.lower()}.png"
        if not caminho.exists() or len(codigo) != N_CARACTERES:
            continue
        ink = preprocess(caminho)
        boxes = segmentar_caracteres(ink)
        if len(boxes) != N_CARACTERES:
            continue
        for (x1, _, x2, _), ch in zip(boxes, codigo):
            glyph = ink[:, x1:x2]
            for var in _augment_glyph(glyph):
                feat = extrair_features(var)
                if feat is not None:
                    X.append(feat); y.append(ch)
    if not X:
        print("[-] Nenhuma amostra para treinar.")
        return None

    print(f"[+] Treinando SVM com {len(X)} amostras aumentadas ({len(set(y))} classes)...")
    clf = SVC(kernel='rbf', C=4.0, gamma='scale', probability=True)
    clf.fit(np.asarray(X), np.asarray(y))
    if salvar:
        with open(MODELO_FILE, 'wb') as f:
            pickle.dump({'clf': clf, 'n_amostras': len(X), 'classes': list(clf.classes_)}, f)
        print(f"[+] Modelo salvo em {MODELO_FILE.name}")
    return clf


def carregar_modelo(treinar_se_faltar=True):
    """Carrega o SVM salvo. Treina na hora se faltar."""
    if MODELO_FILE.exists():
        try:
            with open(MODELO_FILE, 'rb') as f:
                return pickle.load(f)['clf']
        except Exception as e:
            print(f"[-] Falha ao abrir {MODELO_FILE.name}: {e}")
    if treinar_se_faltar:
        return treinar_modelo()
    return None


def predizer_topk(feat, modelo, k=3):
    """Devolve [(classe, score), ...] top-k para o glifo. Score em [0,1]."""
    if modelo is None or feat is None:
        return []
    probs = modelo.predict_proba(feat.reshape(1, -1))[0]
    classes = modelo.classes_
    idx = np.argsort(probs)[::-1][:k]
    return [(classes[i], float(probs[i])) for i in idx]


def reconhecer_com_politica(glifo, templates, limiar_margem=0.05, modelo=None):
    """
    Reconhece glifo. Se `modelo` (SVM) for passado, usa ele. Senão usa templates.
    Aceita a imagem do glifo ou um vetor de features já extraído.
    Retorna: (classe, c2, margem, score, rejeitar, motivo)
    """
    if isinstance(glifo, np.ndarray) and glifo.ndim == 1:
        feat = glifo
    else:
        feat = extrair_features(glifo)
    if feat is None:
        return None, None, -1, -1, True, "glifo invalido"

    if modelo is not None:
        topk = predizer_topk(feat, modelo, k=2)
        if not topk:
            return None, None, -1, -1, True, "sem modelo"
        sorted_scores = topk
    else:
        scores = {}
        for classe, exemplos in templates.items():
            if exemplos:
                scores[classe] = max(coseno_similarity(feat, ex) for ex in exemplos)
        if not scores:
            return None, None, -1, -1, True, "sem templates"
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    if len(sorted_scores) < 2:
        return sorted_scores[0][0], None, 0, sorted_scores[0][1], True, "poucas classes"

    c1, s1 = sorted_scores[0]
    c2, s2 = sorted_scores[1]
    margem = s1 - s2

    # Política de rejeição
    if margem < limiar_margem:
        return c1, c2, margem, s1, True, "margem baixa"

    if c2 in CONFUSOES.get(c1, []):
        return c1, c2, margem, s1, True, "confusao conhecida"

    return c1, c2, margem, s1, False, "ok"


def _ler_politica():
    """Carrega o limiar de probabilidade salvo pela avaliação."""
    if POLITICA_FILE.exists():
        try:
            with open(POLITICA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f).get('limiar_prob', LIMIAR_PROB_PADRAO)
        except Exception:
            pass
    return LIMIAR_PROB_PADRAO


def resolver_captcha(caminho_png, templates=None, modelo=None, limiar=0.05):
    """
    Resolve um captcha completo.
    Se `modelo` (SVM) for passado, usa a probabilidade do SVM para decidir aceitar.
    Senão, usa a margem dos templates (política antiga).
    Retorna: {'codigo': str, 'confianca': float, 'rejeitado': bool, 'motivos': list}
    """
    ink = preprocess(caminho_png)
    boxes = segmentar_caracteres(ink)

    if modelo is None and templates is None:
        modelo = carregar_modelo(treinar_se_faltar=False)
        if modelo is None:
            templates = carregar_templates()

    codigos = []
    scores = []
    motivos = []

    for x1, y1, x2, y2 in boxes:
        feat = extrair_features(ink[y1:y2, x1:x2])
        if feat is None:
            codigos.append('?'); scores.append(0.0); continue
        if modelo is not None:
            top = predizer_topk(feat, modelo, k=1)
            if top:
                codigos.append(top[0][0]); scores.append(top[0][1])
            else:
                codigos.append('?'); scores.append(0.0)
        else:
            c1, c2, margem, score, rejeitar, motivo = reconhecer_com_politica(
                feat, templates or {}, limiar)
            codigos.append(c1 if c1 else '?'); scores.append(max(0.0, margem))

    if len(boxes) != N_CARACTERES:
        motivos.append(f"segmentou {len(boxes)} caracteres")

    # Política de aceitação:
    #   com SVM: aceita se prob_min >= limiar_prob (aprendido pela avaliação)
    #   com templates: aceita se margem_min >= limiar (0.05 por padrão)
    confianca = min(scores) if scores else 0.0
    if modelo is not None:
        limiar_prob = _ler_politica()
        if confianca < limiar_prob:
            motivos.append(f"prob mínima {confianca:.2f} < {limiar_prob:.2f}")
    else:
        if confianca < limiar:
            motivos.append(f"margem mínima {confianca:.2f} < {limiar}")

    return {
        'codigo': ''.join(codigos),
        'confianca': min(1.0, confianca),
        'rejeitado': bool(motivos),
        'motivos': motivos,
        'n_caracteres': len(boxes)
    }


def avaliar_leave_one_out(limiar, usar_svm=True):
    """
    Avaliação por grupos (5-fold por captcha): nenhum caractere do mesmo captcha
    fica em treino e teste. Mede o acerto REAL em captchas nunca vistos.
    Se usar_svm=True (padrão), treina um SVM a cada fold.
    Também calcula o limiar ótimo da política de aceitar/rejeitar.
    """
    amostras = glifos_rotulados()
    ids = sorted({cid for cid, _, _ in amostras})
    if len(ids) < 5:
        print("[-] Precisa de pelo menos 5 captchas rotulados")
        return

    try:
        from sklearn.svm import SVC
        from sklearn.model_selection import GroupKFold
    except ImportError:
        print("[-] sklearn não instalado; usando templates. pip install scikit-learn")
        usar_svm = False

    X = np.array([f for _, _, f in amostras])
    y = np.array([c for _, c, _ in amostras])
    g = np.array([cid for cid, _, _ in amostras])

    predicoes = [None] * len(amostras)   # (classe, prob_top)

    if usar_svm:
        print(f"[+] 5-fold GroupKFold em {len(ids)} captchas, treinando SVM (com augmentation)...\n")
        # Pré-computa versões aumentadas de cada glifo
        aug_feats = defaultdict(list)   # idx -> [feats aumentadas]
        for i, (cid, char, _) in enumerate(amostras):
            caminho = CAPTCHAS_DIR / f"{cid.lower()}.png"
            ink = preprocess(caminho)
            boxes = segmentar_caracteres(ink)
            if len(boxes) != N_CARACTERES: continue
            # localiza o box desse char (ordem de aparição no captcha)
            pos = [j for j, (c2, _, _) in enumerate(amostras) if c2 == cid].index(i)
            x1, _, x2, _ = boxes[pos]
            glyph = ink[:, x1:x2]
            feats = []
            for var in _augment_glyph(glyph):
                f = extrair_features(var)
                if f is not None: feats.append(f)
            aug_feats[i] = feats
        gkf = GroupKFold(n_splits=5)
        for fold, (tr, te) in enumerate(gkf.split(X, y, g), 1):
            Xtr = np.vstack([np.array(aug_feats[i]) for i in tr if aug_feats[i]])
            ytr = np.concatenate([[y[i]] * len(aug_feats[i]) for i in tr if aug_feats[i]])
            clf = SVC(kernel='rbf', C=4.0, gamma='scale', probability=True)
            clf.fit(Xtr, ytr)
            probs = clf.predict_proba(X[te])
            classes = clf.classes_
            idx_top = probs.argmax(axis=1)
            for i, j in enumerate(te):
                predicoes[j] = (classes[idx_top[i]], float(probs[i, idx_top[i]]))
            print(f"  fold {fold}/5 ok ({len(Xtr)} amostras aumentadas)")
    else:
        print(f"[+] 5-fold GroupKFold em {len(ids)} captchas (templates)...\n")
        from sklearn.model_selection import GroupKFold
        gkf = GroupKFold(n_splits=5)
        for fold, (tr, te) in enumerate(gkf.split(X, y, g), 1):
            templates = defaultdict(list)
            for i in tr:
                templates[y[i]].append(X[i])
            for i in te:
                scores = {cls: max(coseno_similarity(X[i], e) for e in exs)
                          for cls, exs in templates.items() if exs}
                ordenado = sorted(scores.items(), key=lambda x: x[1], reverse=True)
                predicoes[i] = (ordenado[0][0], ordenado[0][1] - (ordenado[1][1] if len(ordenado) > 1 else 0))
            print(f"  fold {fold}/5 ok")

    # Monta captchas inteiros
    por_captcha = defaultdict(list)
    for (cid, char, _), pred in zip(amostras, predicoes):
        por_captcha[cid].append((char, pred))

    acertos_char = total_char = acertos_captcha = 0
    casos_captcha = []  # (acerto_total, min_prob)
    print("")
    for cid in ids:
        itens = por_captcha[cid]
        real = ''.join(c for c, _ in itens)
        pred = ''.join(p[0] for _, p in itens)
        probs = [p[1] for _, p in itens]
        hits = sum(a == b for a, b in zip(pred, real))
        acertos_char += hits
        total_char += len(real)
        certo = pred == real
        acertos_captcha += certo
        casos_captcha.append((certo, min(probs)))
        if cid in list(ids)[:20] or not certo:
            marca = "✓" if certo else " "
            print(f"  [{marca}] {cid}: '{pred}' (esperado: {real}) {hits}/{len(real)}  prob_min={min(probs):.2f}")

    # Encontra o melhor limiar: ponto onde aceitar não introduz mais erros que valor x
    casos_captcha.sort(key=lambda x: -x[1])
    melhor = (0, 0, 0, 1.0)  # (certos_aceitos, errados_aceitos, limiar, pct_erro)
    certos_cum = errados_cum = 0
    for certo, pmin in casos_captcha:
        certos_cum += int(certo); errados_cum += int(not certo)
        total = certos_cum + errados_cum
        pct_erro = errados_cum / total if total else 0
        if pct_erro <= 0.05 and certos_cum > melhor[0]:  # <=5% de erro
            melhor = (certos_cum, errados_cum, pmin, pct_erro)

    cobertas = sorted(set(y))
    print("\n" + "=" * 70)
    print("RESUMO:")
    print(f"  - Acerto por caractere: {acertos_char}/{total_char} = {acertos_char/total_char*100:.1f}%")
    print(f"  - Captcha inteiro certo: {acertos_captcha}/{len(ids)} = {100*acertos_captcha/len(ids):.1f}%")
    if melhor[0] > 0 and usar_svm:
        print(f"  - Política aprendida: aceitar quando prob mínima >= {melhor[2]:.2f}")
        print(f"    → aceita {melhor[0]+melhor[1]} captchas ({100*(melhor[0]+melhor[1])/len(ids):.0f}% do total), "
              f"{melhor[0]} certos, {melhor[1]} errados ({melhor[3]*100:.1f}% de erro)")
        with open(POLITICA_FILE, 'w', encoding='utf-8') as f:
            json.dump({'limiar_prob': float(melhor[2]),
                       'aceitos': int(melhor[0] + melhor[1]),
                       'certos': int(melhor[0]),
                       'erro_estimado': float(melhor[3]),
                       'n_captchas_avaliacao': len(ids)}, f, indent=2)
        print(f"    (salvo em {POLITICA_FILE.name}; resolver_captcha vai usar automaticamente)")
    print(f"  - Classes com exemplo ({len(cobertas)}): {''.join(cobertas)}")
    print("=" * 70)


# ============================================================
# Interface CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='Pipeline SEI Captcha Solver')
    parser.add_argument('--captcha', '-c', help='Arquivo captcha individual')
    parser.add_argument('--batch', '-b', help='Pasta com captchas')
    parser.add_argument('--limiar', '-l', type=float, default=0.05,
                        help='Limiar de margem para aceitação')
    parser.add_argument('--treinar', action='store_true',
                        help='Treina o modelo SVM a partir de rotulos.txt e salva')
    parser.add_argument('--sem-modelo', action='store_true',
                        help='Avaliação só com templates (ignora o SVM)')

    args = parser.parse_args()

    if args.treinar:
        treinar_modelo()
        return

    modelo = None if args.sem_modelo else carregar_modelo(treinar_se_faltar=False)

    if args.captcha:
        result = resolver_captcha(args.captcha, modelo=modelo, limiar=args.limiar)
        print(f"Código: {result['codigo']}")
        print(f"Confianca: {result['confianca']:.3f}")
        print(f"Rejeitado: {result['rejeitado']}")
        if result['motivos']:
            print(f"Motivos: {', '.join(result['motivos'])}")
        return

    if args.batch:
        pasta = Path(args.batch)
        templates = None if modelo is not None else carregar_templates()
        for arq in sorted(pasta.glob("captcha_*.png")):
            result = resolver_captcha(arq, templates=templates, modelo=modelo, limiar=args.limiar)
            status = "REJEITADO" if result['rejeitado'] else "ACEITO"
            print(f"[{status}] {arq.name}: {result['codigo']} (conf: {result['confianca']:.2f})")
        return

    # Sem argumentos - avaliar com os captchas rotulados
    print("=" * 70)
    print("                 PIPELINE COMPLETO SEI CAPTCHA")
    print("=" * 70)

    if not ROTULOS_FILE.exists():
        print("[-] Execute fase0_auditoria.py primeiro")
        return

    avaliar_leave_one_out(args.limiar)


if __name__ == "__main__":
    main()
