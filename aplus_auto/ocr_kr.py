"""섹션 그림에서 한국어 글자를 읽는다 (PaddleOCR, 팀 확정 설정 그대로).

설정 (CLAUDE.md · ai-poc README ② 와 같음, 바꾸지 말 것)
    글자 위치: PP-OCRv5_server_det · 글자 읽기: korean_PP-OCRv5_mobile_rec · 신뢰도 0.60 미만 버림
    모델 캐시 C:\\paddlex_cache (한글 경로 문제) — paddleocr import 전에 설정
    4,000px 넘는 섹션은 2,000px 띠·300px 겹침으로 나눠 읽는다(검출기가 긴 변을 줄여 글자가 사라지는 문제)
줄 읽는 순서·자르기 방식은 amazon/run_ocr.py 와 같다. 줄을 문단으로 묶는 것만 여기서 간단히 한다.
"""
import os

os.environ.setdefault("PADDLE_PDX_CACHE_HOME", r"C:\paddlex_cache")
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

DET_MODEL = "PP-OCRv5_server_det"
REC_MODEL = "korean_PP-OCRv5_mobile_rec"
MIN_CONFIDENCE = 0.60
CROP_PADDING = 3
BAND, OVERLAP, LONG = 2000, 300, 4000

_models = None


def models():
    global _models
    if _models is None:
        from paddleocr import TextDetection, TextRecognition
        _models = (TextDetection(model_name=DET_MODEL), TextRecognition(model_name=REC_MODEL))
    return _models


def _polys(det):
    if det is None or len(det) == 0 or not isinstance(det[0], dict):
        return []
    for k in ("dt_polys", "rec_polys"):
        p = det[0].get(k)
        if p is not None and len(p) > 0:
            return p
    return []


def _read(img):
    det, rec = models()
    h, w = img.shape[:2]
    boxes, crops = [], []
    for poly in _polys(det.predict(img)):
        xs = [float(p[0]) for p in poly]
        ys = [float(p[1]) for p in poly]
        x1, y1 = max(0, int(min(xs)) - CROP_PADDING), max(0, int(min(ys)) - CROP_PADDING)
        x2, y2 = min(w, int(max(xs)) + CROP_PADDING), min(h, int(max(ys)) + CROP_PADDING)
        if x2 - x1 < 4 or y2 - y1 < 4:
            continue
        boxes.append((x1, y1, x2, y2))
        crops.append(img[y1:y2, x1:x2])
    out = []
    if crops:
        for b, r in zip(boxes, rec.predict(crops)):
            t = (r.get("rec_text") or "").strip()
            s = float(r.get("rec_score") or 0)
            if t and s >= MIN_CONFIDENCE:
                out.append({"text": t, "x1": b[0], "y1": b[1], "x2": b[2], "y2": b[3], "conf": round(s, 3)})
    return out


def read_lines(path):
    """그림 한 장 → 줄 목록 (좌표는 그 그림 기준)."""
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"그림을 읽을 수 없음: {path}")
    h = img.shape[0]
    if h <= LONG:
        return _read(img)
    lines, top = [], 0
    while top < h:
        bot = min(h, top + BAND)
        own0 = top + (OVERLAP // 2 if top > 0 else 0)
        own1 = bot - (OVERLAP // 2 if bot < h else 0)
        for ln in _read(img[top:bot]):
            ln["y1"] += top
            ln["y2"] += top
            cy = (ln["y1"] + ln["y2"]) / 2
            if own0 <= cy < own1:  # 겹치는 띠에서 두 번 읽힌 줄은 한 번만
                lines.append(ln)
        if bot >= h:
            break
        top = bot - OVERLAP
    return lines


def reading_order(lines):
    if not lines:
        return []
    hs = sorted(l["y2"] - l["y1"] for l in lines)
    tol = max(8, hs[len(hs) // 2] // 2)
    by_y = sorted(lines, key=lambda l: (l["y1"] + l["y2"]) / 2)
    rows, cur = [], [by_y[0]]
    base = (by_y[0]["y1"] + by_y[0]["y2"]) / 2
    for l in by_y[1:]:
        cy = (l["y1"] + l["y2"]) / 2
        if cy - base <= tol:
            cur.append(l)
        else:
            rows.append(cur)
            cur, base = [l], cy
    rows.append(cur)
    out = []
    for r in rows:
        out.extend(sorted(r, key=lambda l: l["x1"]))
    return out


def paragraphs(lines):
    """읽는 순서대로 훑으며, 바로 위 문단과 가깝고(줄 높이 0.8배 이내) 가로로 겹치면 같은 문단으로 묶는다."""
    paras = []
    for l in reading_order(lines):
        lh = l["y2"] - l["y1"]
        p = paras[-1] if paras else None
        if p and 0 <= l["y1"] - p["y2"] <= lh * 0.8 and min(l["x2"], p["x2"]) - max(l["x1"], p["x1"]) > 0:
            p["text"] += " " + l["text"]
            p["x1"], p["x2"] = min(p["x1"], l["x1"]), max(p["x2"], l["x2"])
            p["y2"] = max(p["y2"], l["y2"])
            p["confs"].append(l["conf"])
        else:
            paras.append({**l, "confs": [l["conf"]]})
    for p in paras:
        cs = p.pop("confs")
        p["conf"] = round(sum(cs) / len(cs), 3)
    return paras
