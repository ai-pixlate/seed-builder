# -*- coding: utf-8 -*-
"""
reorder_ocr_v2.py
-----------------
reorder_ocr.py (XY-cut 순서 정리)의 버그 수정판. 기존 파일은 그대로 두고 이 파일이 대신 쓴다.

버그: 더 나눌 여백이 없는 문단 안에서 글자 덩어리를 (위쪽 y1, 왼쪽 x1) 순으로만 정렬했다.
      같은 줄인데 높이가 몇 픽셀 다른 글자가 앞뒤로 뒤바뀌었다.
      예) "Lip"(y1=422) "Stain"(y1=427, x=384) "Set"(y1=423, x=761) → "Lip Set Stain"
수정: 문단 안에서도 세로 중심이 글자 키의 절반 이내로 가까우면 같은 줄로 묶고,
      줄 안에서는 왼쪽부터 읽는다. (run_ocr.py 의 reading_order 와 같은 방식)
추가: 겹친 글자 상자 때문에 앞 단어 끝 글자가 한 번 더 읽힌 것("Deep o Hydration")을 지운다 → text_clean

실행:  py -3.12 amazon/reorder_ocr_v2.py <폴더>   (기본: data/saturation)
       폴더 안의 out_ocr_lines.csv, out_images_ocr.csv 를 읽어 *_ordered.csv 를 다시 만든다.
"""
import csv
import os
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "amazon"))

import reorder_ocr  # noqa: E402  (불러오는 순간 data/main 으로 이동하므로 아래에서 다시 이동)


def order_lines(boxes):
    """한 문단 안의 글자 덩어리를 줄 단위로 묶어 위→아래, 줄 안에서는 왼→오 순으로 정렬"""
    if len(boxes) <= 1:
        return list(boxes)
    heights = [b["y2"] - b["y1"] for b in boxes if b["y2"] > b["y1"]]
    tol = max(8.0, (statistics.median(heights) if heights else 20.0) / 2)
    by_center = sorted(boxes, key=lambda b: (b["y1"] + b["y2"]) / 2)
    lines, current = [], [by_center[0]]
    base = (by_center[0]["y1"] + by_center[0]["y2"]) / 2
    for b in by_center[1:]:
        cy = (b["y1"] + b["y2"]) / 2
        if cy - base <= tol:
            current.append(b)
        else:
            lines.append(current)
            current, base = [b], cy
    lines.append(current)
    out = []
    for line in lines:
        out.extend(sorted(line, key=lambda b: b["x1"]))
    return out


def xy_cut_v2(boxes, min_gap):
    if len(boxes) <= 1:
        return [boxes]
    gap_x, cut_x = reorder_ocr.widest_gap(boxes, "x1", "x2")
    gap_y, cut_y = reorder_ocr.widest_gap(boxes, "y1", "y2")
    if gap_x >= min_gap and gap_x >= gap_y:
        left = [b for b in boxes if b["x1"] < cut_x]
        right = [b for b in boxes if b["x1"] >= cut_x]
        return xy_cut_v2(left, min_gap) + xy_cut_v2(right, min_gap)
    if gap_y >= min_gap:
        top = [b for b in boxes if b["y1"] < cut_y]
        bottom = [b for b in boxes if b["y1"] >= cut_y]
        return xy_cut_v2(top, min_gap) + xy_cut_v2(bottom, min_gap)
    return [order_lines(boxes)]          # ← 수정된 부분


LEADING_STRAY = re.compile(r"^([A-Za-z0-9,.;:])\s*(?=\S)")   # 기호(, . ; :)는 붙어 있어도 해당


def strip_stray(block):
    """
    겹친 글자 상자 때문에 앞 단어의 마지막 글자가 다음 상자 맨 앞에 한 번 더 읽히는 경우를 지운다.
      예) "Deep" + "o Hydration", "choose" + "e your", "and" + "d radiant."
    조건: 상자 글자가 '한 글자 + 띄어쓰기'로 시작하고, 같은 줄 바로 왼쪽에 붙어 있거나 겹친 상자가 있을 때.
    원래 글자(text)는 그대로 두고 고친 글자를 text_clean 에 담는다.
    """
    for b in block:
        b["text_clean"] = b["text"].strip()
    for b in block:
        m = LEADING_STRAY.match(b["text_clean"])
        if not m:
            continue
        if m.group(1).isalnum() and not re.match(r"^\S\s", b["text_clean"]):
            continue                      # 글자·숫자는 뒤에 띄어쓰기가 있을 때만 (단어 첫 글자를 지우지 않게)
        h = max(1.0, b["y2"] - b["y1"])
        cy = (b["y1"] + b["y2"]) / 2
        left = [o for o in block if o is not b
                and abs((o["y1"] + o["y2"]) / 2 - cy) <= h / 2          # 같은 줄
                and o["x1"] < b["x1"] and b["x1"] - o["x2"] <= h * 0.3]  # 바로 왼쪽에 붙거나 겹침
        if not left:
            continue
        prev = max(left, key=lambda o: o["x2"])["text"].strip()
        if prev and looks_like_tail(m.group(1), prev[-1]):
            b["text_clean"] = b["text_clean"][m.end():]


# 겹친 상자가 앞 단어 끝 글자를 다시 읽을 때 자주 나오는 모양 (같은 글자이거나 생김새가 비슷한 글자)
SIMILAR = [set("1Iil|dt"), set("oO0pdbqaecg")]


def looks_like_tail(ch, prev_last):
    """지우려는 한 글자가 앞 단어의 마지막 글자와 같거나 생김새가 비슷하면 True"""
    if ch.lower() == prev_last.lower():
        return True
    return any(ch in s and prev_last in s for s in SIMILAR)


# ---- 2026-10-19 최종 수집 검수(60장)에서 추가한 글자 정리 ----
# 전각 영문·숫자·기호(ＢＥＴＴＥＲ, １００％, ，)만 반각으로. NFKC 는 ①·™·한글 자모까지 바꾸므로 쓰지 않는다
FULLWIDTH = {c: c - 0xFEE0 for c in range(0xFF01, 0xFF5F)}
FULLWIDTH[0x3000] = 0x20
# 숫자 사이에 낀 o/O (1o,ooo / 1oo% / SPF 5O / 13.O). 숫자로 시작하고 숫자·o·쉼표·점만 있는 덩어리
NUM_WITH_O = re.compile(r"(?<![A-Za-z])(\d[\doO]*(?:[.,][\doO]+)*)(?=%|\b)")
# 맨 앞의 작은따옴표·백틱 + 띄어쓰기 (체크 표시·글머리 아이콘을 따옴표로 읽은 것). 큰따옴표는 진짜 인용일 수 있어 둔다
LEADING_QUOTE = re.compile(r"^['`‘’]\s+(?=\S)")


def fix_chars(text):
    """글자 모양 정리. 고친 글자와 고친 종류(set)를 돌려준다"""
    kinds = set()
    t = text.translate(FULLWIDTH)
    if t != text:
        kinds.add("fullwidth")
    t2 = NUM_WITH_O.sub(lambda m: m.group(1).replace("o", "0").replace("O", "0") if re.search(r"[oO]", m.group(1)) else m.group(1), t)
    if t2 != t:
        kinds.add("num_o")
    t3 = LEADING_QUOTE.sub("", t2)
    if t3 != t2:
        kinds.add("quote")
    return t3, kinds


def main(folder=None):
    folder = Path(folder) if folder else ROOT / "data" / "saturation"
    os.chdir(folder)
    enc = reorder_ocr.ENCODING
    with open(reorder_ocr.LINES_CSV, encoding=enc, newline="") as f:
        rows = list(csv.DictReader(f))
    by_image = {}
    for r in rows:
        for k in ("x1", "y1", "x2", "y2"):
            r[k] = float(r[k])
        by_image.setdefault(r["image_id"], []).append(r)

    ordered_rows, text_by_image, stray_fixed = [], {}, 0
    char_fixed = {"fullwidth": 0, "num_o": 0, "quote": 0}
    for image_id, boxes in by_image.items():
        heights = [b["y2"] - b["y1"] for b in boxes if b["y2"] > b["y1"]]
        line_h = statistics.median(heights) if heights else 20.0
        blocks = xy_cut_v2(boxes, line_h * reorder_ocr.GAP_RATIO)
        seq, chunks = 0, []
        for block_no, block in enumerate(blocks, start=1):
            strip_stray(block)
            for b in block:
                seq += 1
                b["block_id"], b["reading_order"] = block_no, seq
                stray_fixed += b["text_clean"] != b["text"].strip()
                b["text_clean"], kinds = fix_chars(b["text_clean"])
                for k in kinds:
                    char_fixed[k] += 1
                ordered_rows.append(b)
            chunks.append(" ".join(b["text_clean"] for b in block if b["text_clean"]))
        text_by_image[image_id] = reorder_ocr.BLOCK_SEP.join(c for c in chunks if c)

    header = list(rows[0].keys()) + [c for c in ("block_id", "reading_order", "text_clean") if c not in rows[0]]
    ordered_rows.sort(key=lambda r: (r["image_id"], r["reading_order"]))
    with open(reorder_ocr.OUT_LINES, "w", encoding=enc, newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in ordered_rows:
            for k in ("x1", "y1", "x2", "y2"):
                r[k] = int(round(r[k]))
            w.writerow(r)

    with open(reorder_ocr.IMAGES_CSV, encoding=enc, newline="") as f:
        img_rows = list(csv.DictReader(f))
    img_header = list(img_rows[0].keys()) + [c for c in ("ocr_text_ordered", "ocr_block_count") if c not in img_rows[0]]
    for r in img_rows:
        t = text_by_image.get(r["image_id"], "")
        r["ocr_text_ordered"] = t
        r["ocr_block_count"] = t.count(reorder_ocr.BLOCK_SEP) + 1 if t else ""
    with open(reorder_ocr.OUT_IMAGES, "w", encoding=enc, newline="") as f:
        w = csv.DictWriter(f, fieldnames=img_header)
        w.writeheader()
        w.writerows(img_rows)
    print(f"이미지 {len(by_image)}장, 글자덩어리 {len(ordered_rows)}개 재정렬 완료 (겹침 글자 제거 {stray_fixed}건)")
    print(f"글자 정리: 전각→반각 {char_fixed['fullwidth']}건, 숫자 속 o→0 {char_fixed['num_o']}건, 맨 앞 따옴표 {char_fixed['quote']}건")
    print(f"생성: {reorder_ocr.OUT_LINES}, {reorder_ocr.OUT_IMAGES}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main(sys.argv[1] if len(sys.argv) > 1 else None)
