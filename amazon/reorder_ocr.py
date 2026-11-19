# -*- coding: utf-8 -*-
"""
reorder_ocr.py
--------------
이미 뽑아둔 OCR 결과(out_ocr_lines.csv)의 "읽는 순서"를 고친다.
OCR을 다시 돌리지 않는다. 저장된 좌표만 보고 순서를 재배열한다.

문제:
    상세페이지 이미지는 글자가 좌우 여러 칸으로 나뉘어 있는데
    지금 결과는 위에서 아래로 한 줄씩만 읽어서 칸끼리 글자가 섞인다.
      (X) Triple / Micellar / Ultra-Soft / Emollient / Technology / Wipe / Blend
      (O) Triple Emollient Blend ‖ Micellar Technology ‖ Ultra-Soft Wipe

방법: XY-cut (사람이 신문 읽는 순서를 흉내내는 고전 알고리즘)
    1) 글자 덩어리들 사이의 "빈 여백"을 찾는다
    2) 세로 여백이 가장 크면 -> 칸이 나뉜 것. 왼쪽 칸부터 통째로 읽는다
    3) 가로 여백이 가장 크면 -> 문단이 나뉜 것. 위 문단부터 읽는다
    4) 더 나눌 여백이 없을 때까지 반복
    5) 남은 덩어리는 위->아래, 왼->오 순으로 이어붙여 한 문장으로 만든다

만들어지는 파일:
    out_ocr_lines_ordered.csv   줄마다 block_id(문단 번호) + reading_order(읽는 순서) 추가
    out_images_ocr_ordered.csv  이미지마다 순서 고친 텍스트(ocr_text_ordered) 추가

실행:  py -3 reorder_ocr.py
"""

# ── 실행 위치와 상관없이 저장소 최상위 폴더를 기준으로 동작하게 만든다 ──────────
#    이 파일은 하위 폴더에 있지만, 읽고 쓰는 CSV 등은 모두 data/main/ 에 있다.
#    sys.path : 최상위의 env_loader.py 를 import 할 수 있게 한다
#    os.chdir : 읽고 쓰는 결과 파일은 전부 data/main/ 폴더 안에 둔다
import os as _os, sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parent.parent
_sys.path.insert(0, str(_ROOT))
_DATA = _ROOT / "data" / "main"
_DATA.mkdir(parents=True, exist_ok=True)
_os.chdir(_DATA)
# ──────────────────────────────────────────────────────────────────────────

import csv
import io
import statistics

LINES_CSV = "out_ocr_lines.csv"
IMAGES_CSV = "out_images_ocr.csv"
OUT_LINES = "out_ocr_lines_ordered.csv"
OUT_IMAGES = "out_images_ocr_ordered.csv"
ENCODING = "utf-8-sig"

# 여백이 글자 높이의 몇 배 이상이어야 "칸/문단이 나뉘었다"고 볼지.
# 크게 잡으면 안 나눠서 여전히 섞이고, 작게 잡으면 한 문장을 토막낸다.
GAP_RATIO = 0.8

# 문단과 문단 사이에 넣을 구분 기호
BLOCK_SEP = " ‖ "  # 원문에 | 가 들어있는 이미지가 있어서 겹치지 않는 기호를 쓴다


def widest_gap(boxes, lo_key, hi_key):
    """한 방향(가로 또는 세로)으로 훑어서 가장 넓은 빈 여백을 찾는다."""
    spans = sorted((b[lo_key], b[hi_key]) for b in boxes)
    best_size, best_cut = 0.0, None
    reach = spans[0][1]
    for lo, hi in spans[1:]:
        if lo - reach > best_size:
            best_size, best_cut = lo - reach, (reach + lo) / 2.0
        reach = max(reach, hi)
    return best_size, best_cut


def xy_cut(boxes, min_gap):
    """글자 덩어리들을 읽는 순서대로 문단 리스트로 쪼갠다."""
    if len(boxes) <= 1:
        return [boxes]

    gap_x, cut_x = widest_gap(boxes, "x1", "x2")   # 세로로 벌어진 여백 = 칸 구분
    gap_y, cut_y = widest_gap(boxes, "y1", "y2")   # 가로로 벌어진 여백 = 문단 구분

    # 더 넓게 벌어진 쪽을 먼저 자른다
    if gap_x >= min_gap and gap_x >= gap_y:
        left = [b for b in boxes if b["x1"] < cut_x]
        right = [b for b in boxes if b["x1"] >= cut_x]
        return xy_cut(left, min_gap) + xy_cut(right, min_gap)

    if gap_y >= min_gap:
        top = [b for b in boxes if b["y1"] < cut_y]
        bottom = [b for b in boxes if b["y1"] >= cut_y]
        return xy_cut(top, min_gap) + xy_cut(bottom, min_gap)

    # 더 나눌 여백이 없다 = 한 문단. 위->아래, 왼->오 순으로 정렬
    return [sorted(boxes, key=lambda b: (b["y1"], b["x1"]))]


def order_image(boxes):
    """이미지 한 장의 글자 덩어리들을 읽는 순서대로 문단 리스트로 만든다."""
    if not boxes:
        return []
    heights = [b["y2"] - b["y1"] for b in boxes if b["y2"] > b["y1"]]
    line_h = statistics.median(heights) if heights else 20.0
    return xy_cut(boxes, line_h * GAP_RATIO)


def main():
    with io.open(LINES_CSV, encoding=ENCODING, newline="") as f:
        rows = list(csv.DictReader(f))

    by_image = {}
    for r in rows:
        for k in ("x1", "y1", "x2", "y2"):
            r[k] = float(r[k])
        by_image.setdefault(r["image_id"], []).append(r)

    ordered_rows = []
    text_by_image = {}

    for image_id, boxes in by_image.items():
        blocks = order_image(boxes)
        seq = 0
        chunks = []
        for block_no, block in enumerate(blocks, start=1):
            for b in block:
                seq += 1
                b["block_id"] = block_no
                b["reading_order"] = seq
                ordered_rows.append(b)
            chunks.append(" ".join(b["text"].strip() for b in block if b["text"].strip()))
        text_by_image[image_id] = BLOCK_SEP.join(c for c in chunks if c)

    # --- 줄 단위 파일 ---
    line_header = list(rows[0].keys())
    for extra in ("block_id", "reading_order"):
        if extra not in line_header:
            line_header.append(extra)
    ordered_rows.sort(key=lambda r: (r["image_id"], r["reading_order"]))
    with io.open(OUT_LINES, "w", encoding=ENCODING, newline="") as f:
        w = csv.DictWriter(f, fieldnames=line_header)
        w.writeheader()
        for r in ordered_rows:
            for k in ("x1", "y1", "x2", "y2"):
                r[k] = int(round(r[k]))
            w.writerow(r)

    # --- 이미지 단위 파일 ---
    with io.open(IMAGES_CSV, encoding=ENCODING, newline="") as f:
        img_rows = list(csv.DictReader(f))
    img_header = list(img_rows[0].keys())
    if "ocr_text_ordered" not in img_header:
        img_header.append("ocr_text_ordered")
    if "ocr_block_count" not in img_header:
        img_header.append("ocr_block_count")

    changed = 0
    for r in img_rows:
        blocks_txt = text_by_image.get(r["image_id"], "")
        r["ocr_text_ordered"] = blocks_txt
        r["ocr_block_count"] = blocks_txt.count(BLOCK_SEP) + 1 if blocks_txt else ""
        flat = lambda s: "".join(s.split())
        if blocks_txt and flat(blocks_txt.replace("|", "")) != flat(r["ocr_text"]):
            changed += 1

    with io.open(OUT_IMAGES, "w", encoding=ENCODING, newline="") as f:
        w = csv.DictWriter(f, fieldnames=img_header)
        w.writeheader()
        w.writerows(img_rows)

    print("이미지 %d장, 글자덩어리 %d개 재정렬 완료" % (len(by_image), len(ordered_rows)))
    print("순서가 실제로 바뀐 이미지: %d장" % changed)
    print("생성: %s, %s" % (OUT_LINES, OUT_IMAGES))


if __name__ == "__main__":
    main()
