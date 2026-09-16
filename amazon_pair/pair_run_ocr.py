# -*- coding: utf-8 -*-
"""
run_ocr.py
----------
images/ 폴더의 이미지에서 PaddleOCR로 텍스트를 뽑는다.

[중요 1] 모델 캐시를 C:\\paddlex_cache 로 옮긴다.
        Paddle 의 C++ 추론 엔진은 경로에 한글이 들어가면 모델 파일을 열지 못한다.
        기본 캐시 위치가 C:\\Users\\인공지능사관학교\\.paddlex 라서 그대로 두면
        "Cannot open file ... inference.json" 에러가 난다.

[중요 2] 모델을 PP-OCRv5 로 못박는다.
        paddleocr 3.7 은 기본값이 PP-OCRv6 인데, 설치된 paddlepaddle 3.0.0 에서는
        "Type of attribute: strides is not right" 로 죽는다. v5 는 정상 동작한다.

[중요 3] PaddleOCR() 통합 파이프라인 대신
        TextDetection(글자 위치 찾기) + TextRecognition(글자 읽기) 두 모델만 직접 쓴다.
        통합 파이프라인은 문서방향판별 모델을 강제로 불러오는데 초기화에 실패한다.
        상품 이미지는 항상 똑바로 되어 있어 방향 판별이 필요 없다.

파일명(I00002.jpg)이 곧 out_images.csv 의 image_id 이므로
결과를 정확히 같은 행에 되돌려 넣을 수 있다.

만들어지는 파일:
  out_images_ocr.csv   out_images.csv + OCR 결과 컬럼  (이미지당 1행)
  out_ocr_lines.csv    인식된 글자 덩어리 하나하나 + 좌표  (줄당 1행)
  ocr_progress.json    진행 상황 저장 (중간에 멈춰도 이어서 실행됨)

실행:  py -3.12 run_ocr.py
"""

# ── 실행 위치와 상관없이 저장소 최상위 폴더를 기준으로 동작하게 만든다 ──────────
#    이 파일은 하위 폴더에 있지만, 읽고 쓰는 CSV 등은 모두 최상위 폴더에 있다.
#    sys.path : 최상위의 env_loader.py 를 import 할 수 있게 한다
#    os.chdir : "out_images.csv" 같은 파일명이 항상 최상위를 가리키게 한다
import os as _os, sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parent.parent
_sys.path.insert(0, str(_ROOT))
_os.chdir(_ROOT)
# ──────────────────────────────────────────────────────────────────────────

import os

# ---------------------------------------------------------------
# paddleocr 를 import 하기 "전에" 캐시 경로를 잡아야 한다.
# ---------------------------------------------------------------
CACHE_DIR = r"C:\paddlex_cache"
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", CACHE_DIR)
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

import csv
import json
import time

INPUT_CSV = "pair_images.csv"
IMAGE_DIR = "images_pair"
OUT_IMAGES_CSV = "pair_images_ocr.csv"
OUT_LINES_CSV = "pair_ocr_lines.csv"
PROGRESS_JSON = "ocr_progress_pair.json"
ENCODING = "utf-8-sig"

# 사용할 모델. server_det 은 글자 영역을 잘 찾고, mobile_rec 은 빠르면서 정확하다.
# (server_rec 은 6배 느린데 오히려 오인식이 더 많아서 쓰지 않는다)
DET_MODEL = "PP-OCRv5_server_det"
REC_MODEL = "PP-OCRv5_mobile_rec"

# 신뢰도가 이 값보다 낮은 줄은 결과에서 제외 (오인식 걸러내기)
MIN_CONFIDENCE = 0.60

# 글자 영역을 잘라낼 때 여유 픽셀 (너무 딱 맞게 자르면 인식률이 떨어짐)
CROP_PADDING = 3

# 진행 상황을 몇 장마다 저장할지
SAVE_EVERY = 25


def find_image_file(image_id):
    for ext in (".jpg", ".png", ".webp", ".gif"):
        path = os.path.join(IMAGE_DIR, image_id + ext)
        if os.path.exists(path):
            return path
    return None


def load_progress():
    if os.path.exists(PROGRESS_JSON):
        try:
            with open(PROGRESS_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_progress(progress):
    tmp = PROGRESS_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False)
    os.replace(tmp, PROGRESS_JSON)


def poly_to_bbox(poly, w, h):
    """네 꼭짓점 좌표 -> (x1, y1, x2, y2) 사각형. 이미지 범위를 넘지 않게 자름"""
    xs = [float(p[0]) for p in poly]
    ys = [float(p[1]) for p in poly]
    x1 = max(0, int(min(xs)) - CROP_PADDING)
    y1 = max(0, int(min(ys)) - CROP_PADDING)
    x2 = min(w, int(max(xs)) + CROP_PADDING)
    y2 = min(h, int(max(ys)) + CROP_PADDING)
    return x1, y1, x2, y2


def extract_polys(det_result):
    """
    탐지 결과에서 글자 영역 좌표 목록을 꺼낸다.

    dt_polys 는 numpy 배열이라 `a or b` 같은 식을 쓰면
    "truth value of an array is ambiguous" 로 죽는다. 길이로만 판단할 것.
    """
    if det_result is None or len(det_result) == 0:
        return []
    first = det_result[0]
    if not isinstance(first, dict):
        return []
    for key in ("dt_polys", "rec_polys"):
        polys = first.get(key)
        if polys is not None and len(polys) > 0:
            return polys
    return []


def reading_order(items):
    """
    글자 덩어리를 사람이 읽는 순서(위->아래, 왼쪽->오른쪽)로 정렬한다.

    단순히 y 로만 정렬하면 같은 줄에 나란히 있는 글자가 1px 차이로
    뒤바뀌므로, 높이의 절반만큼 겹치면 같은 줄로 묶어서 처리한다.

    items: [(text, (x1, y1, x2, y2), score), ...]
    """
    if not items:
        return []

    heights = sorted(b[3] - b[1] for _, b, _ in items)
    tol = max(8, heights[len(heights) // 2] // 2)

    # 세로 중심 y 기준으로 훑으면서, 직전 줄과 tol 안쪽이면 같은 줄로 본다
    ordered_by_y = sorted(items, key=lambda k: (k[1][1] + k[1][3]) / 2)
    rows = []
    current = [ordered_by_y[0]]
    base_y = (ordered_by_y[0][1][1] + ordered_by_y[0][1][3]) / 2

    for it in ordered_by_y[1:]:
        cy = (it[1][1] + it[1][3]) / 2
        if cy - base_y <= tol:
            current.append(it)
        else:
            rows.append(current)
            current = [it]
            base_y = cy
    rows.append(current)

    ordered = []
    for row in rows:
        row.sort(key=lambda k: k[1][0])
        ordered.extend(row)
    return ordered


def main():
    if not os.path.exists(INPUT_CSV):
        print(f"[에러] {INPUT_CSV} 가 없습니다. to_csv.py 를 먼저 실행하세요.")
        return
    if not os.path.isdir(IMAGE_DIR):
        print(f"[에러] {IMAGE_DIR} 폴더가 없습니다. download_images.py 를 먼저 실행하세요.")
        return

    print(f"PaddleOCR 준비 중... (모델 캐시: {os.environ['PADDLE_PDX_CACHE_HOME']})")
    print("처음 실행하면 모델을 내려받느라 몇 분 걸립니다.\n")

    try:
        from paddleocr import TextDetection, TextRecognition
    except ImportError:
        print("[에러] paddleocr 이 설치되어 있지 않습니다.")
        print("       py -3.12 -m pip install paddleocr")
        return

    try:
        import cv2
        import numpy as np
    except ImportError:
        print("[에러] opencv 가 필요합니다.")
        print("       py -3.12 -m pip install opencv-python numpy")
        return

    try:
        detector = TextDetection(model_name=DET_MODEL)
        recognizer = TextRecognition(model_name=REC_MODEL)
    except Exception as e:
        print(f"[에러] 모델 초기화 실패: {e}")
        print("\n해결 방법:")
        print(f'  1) 모델 캐시를 지우고 다시 실행:  Remove-Item -Recurse -Force "{CACHE_DIR}"')
        print('  2) 다운로드 출처를 바꿔서 실행:    $env:PADDLE_PDX_MODEL_SOURCE="bos"')
        return

    print(f"준비 완료 ({DET_MODEL} + {REC_MODEL})\n")

    with open(INPUT_CSV, "r", encoding=ENCODING) as f:
        rows = list(csv.DictReader(f))
        base_fields = list(rows[0].keys())

    targets = [r for r in rows if (r.get("ocr_target") or "").strip().upper() == "Y"]
    progress = load_progress()
    todo = [r for r in targets if r["image_id"] not in progress]

    print(f"OCR 대상 {len(targets)}장 (이미 처리됨 {len(targets) - len(todo)}장, "
          f"이번에 처리할 것 {len(todo)}장)\n")

    start = time.time()
    processed = 0
    no_text = 0

    for i, row in enumerate(todo, start=1):
        image_id = row["image_id"]
        path = find_image_file(image_id)

        if path is None:
            progress[image_id] = {"status": "missing"}
            continue

        try:
            # 경로에 한글이 있어도 읽히도록 fromfile + imdecode 사용
            img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                raise Exception("이미지를 읽을 수 없음")
            h, w = img.shape[:2]

            # 1) 글자 위치 찾기 (경로 대신 이미 읽어둔 배열을 넘긴다)
            polys = extract_polys(detector.predict(img))

            crops = []
            boxes = []
            for poly in polys:
                x1, y1, x2, y2 = poly_to_bbox(poly, w, h)
                if x2 - x1 < 4 or y2 - y1 < 4:
                    continue
                crop = img[y1:y2, x1:x2]
                if crop.size == 0:
                    continue
                crops.append(crop)
                boxes.append((x1, y1, x2, y2))

            # 2) 잘라낸 조각을 한 번에 묶어서 읽는다 (한 장씩 부르면 몇 배 느림)
            kept = []
            if crops:
                for box, out in zip(boxes, recognizer.predict(crops)):
                    text = (out.get("rec_text") or "").strip()
                    score = float(out.get("rec_score") or 0.0)
                    if text and score >= MIN_CONFIDENCE:
                        kept.append((text, box, score))

            kept = reading_order(kept)

            full_text = " ".join(t for (t, _, _) in kept)
            avg_conf = round(sum(s for (_, _, s) in kept) / len(kept), 3) if kept else 0.0

            # 줄 정보를 progress 에도 넣어둔다.
            # 이렇게 해야 중간에 멈췄다 다시 실행해도
            # out_ocr_lines.csv 가 앞부분까지 온전하게 다시 만들어진다.
            progress[image_id] = {
                "status": "ok",
                "text": full_text,
                "line_count": len(kept),
                "avg_conf": avg_conf,
                "lines": [
                    {"text": t, "x1": b[0], "y1": b[1], "x2": b[2], "y2": b[3],
                     "conf": round(s, 3)}
                    for (t, b, s) in kept
                ],
            }

            if not kept:
                no_text += 1
            processed += 1

        except Exception as e:
            progress[image_id] = {"status": "error", "error": str(e)[:200]}

        if i % SAVE_EVERY == 0 or i == len(todo):
            save_progress(progress)
            elapsed = time.time() - start
            speed = i / elapsed if elapsed > 0 else 0
            eta = (len(todo) - i) / speed / 60 if speed > 0 else 0
            print(f"  {i}/{len(todo)}  처리 {processed} / 글자없음 {no_text}"
                  f"  ({speed:.2f}장/초, 남은시간 약 {eta:.0f}분)")

    save_progress(progress)

    # ---------- 결과 저장 ----------
    print("\n결과 저장 중...")

    ocr_fields = ["ocr_done", "ocr_text", "ocr_line_count", "ocr_avg_confidence"]
    out_fields = base_fields + [f for f in ocr_fields if f not in base_fields]

    with open(OUT_IMAGES_CSV, "w", newline="", encoding=ENCODING) as f:
        w_csv = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
        w_csv.writeheader()
        for row in rows:
            info = progress.get(row["image_id"])
            new_row = dict(row)
            if info and info.get("status") == "ok":
                new_row["ocr_done"] = "Y"
                new_row["ocr_text"] = info.get("text", "")
                new_row["ocr_line_count"] = info.get("line_count", 0)
                new_row["ocr_avg_confidence"] = info.get("avg_conf", "")
            else:
                new_row["ocr_done"] = "N"
                new_row["ocr_text"] = ""
                new_row["ocr_line_count"] = ""
                new_row["ocr_avg_confidence"] = ""
            w_csv.writerow(new_row)
    print(f"  {OUT_IMAGES_CSV}  ({len(rows)}행)")

    # 줄 단위 CSV 는 progress 전체를 훑어서 만든다 (이어서 실행한 경우도 온전함)
    meta = {r["image_id"]: r for r in rows}
    line_fields = ["line_id", "image_id", "asin", "source_category",
                   "image_type", "text", "x1", "y1", "x2", "y2", "confidence"]
    n = 0
    with open(OUT_LINES_CSV, "w", newline="", encoding=ENCODING) as f:
        w_csv = csv.DictWriter(f, fieldnames=line_fields)
        w_csv.writeheader()
        for row in rows:
            info = progress.get(row["image_id"])
            if not info or info.get("status") != "ok":
                continue
            for ln in info.get("lines", []):
                n += 1
                w_csv.writerow({
                    "line_id": f"L{n:06d}",
                    "image_id": row["image_id"],
                    "asin": row.get("asin", ""),
                    "source_category": row.get("source_category", ""),
                    "image_type": row.get("image_type", ""),
                    "text": ln["text"],
                    "x1": ln["x1"], "y1": ln["y1"], "x2": ln["x2"], "y2": ln["y2"],
                    "confidence": ln["conf"],
                })
    print(f"  {OUT_LINES_CSV}  ({n}행)")

    # ---------- 요약 ----------
    ok = sum(1 for v in progress.values() if v.get("status") == "ok")
    err = sum(1 for v in progress.values() if v.get("status") == "error")
    miss = sum(1 for v in progress.values() if v.get("status") == "missing")
    with_text = sum(1 for v in progress.values()
                    if v.get("status") == "ok" and v.get("line_count", 0) > 0)

    print(f"\n{'='*50}")
    print(f"처리 완료 {ok}장")
    print(f"  글자가 있던 이미지  {with_text}장")
    print(f"  글자가 없던 이미지  {ok - with_text}장")
    if err:
        print(f"  오류               {err}장")
    if miss:
        print(f"  파일 없음           {miss}장")
    print(f"추출된 텍스트 줄 수: {n}개")


if __name__ == "__main__":
    main()
