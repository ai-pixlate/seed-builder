# -*- coding: utf-8 -*-
"""
kr_ocr_blocks.py — 한국어 상세페이지 OCR 줄을 '붙어 있는 것끼리 한 덩어리'로 묶는다 (OCR 은 다시 하지 않음)

[왜 필요한가]
  한국 상세페이지는 카드형 배치가 많다 (Point 1·2·3 이 옆으로 나란히, 아이콘 + 아래 설명, 수치 카드).
  OCR 결과를 '읽는 순서상 바로 앞 줄'과만 비교해 이어 붙이면, 가로로 읽을 때 바로 앞 줄이 옆 카드의 글이라
  같은 카드 안의 위아래 글이 서로 떨어지고 옆 카드 글과 섞인다.
  → 이미지 안의 모든 글자 상자끼리 비교해서, 서로 붙어 있는 것들을 한 덩어리(연결 요소)로 묶는다.

[묶는 규칙] 두 상자가 아래 중 하나면 같은 덩어리
  ① 위아래로 붙음: 세로 간격 ≤ 작은 글자 높이 × STACK_GAP
                   그리고 가로로 겹침(좁은 쪽 기준 ≥ MIN_X_OVERLAP) 또는 가운데 정렬(가로 중심 차 ≤ 넓은 쪽 너비 × CENTER_TOL)
  ② 같은 줄에서 붙음: 세로 중심 차 ≤ 작은 글자 높이 × 0.5, 가로 간격 ≤ 작은 글자 높이 × SAME_LINE_GAP
[나누는 규칙] 붙어 있어도 다른 덩어리
  - 글자 크기 비 > MAX_H_RATIO (큰 제목 ↔ 작은 주석)
  - 큰 쪽이 숫자 없는 글이고 크기 비 > TITLE_H_RATIO (제목 ↔ 설명). 큰 숫자 + 작은 설명(수치 카드)은 묶음
  - 각주(*, ※, 1) …)는 본문과 따로. 단 각주 아래 이어지는 줄은 각주에 붙임
  - 글머리(·, •, ■ …)로 시작하는 줄은 새 항목
  - 'OO합니다.XX' 처럼 마침표 뒤에 띄어쓰기 없이 이어지면, OCR 이 옆 칸 글까지 한 상자로 읽은 것으로 보고 상자를 나눔
[덩어리 안 / 덩어리 순서]
  - 덩어리 안: 줄 단위(세로 중심이 가까운 것끼리) 위→아래, 줄 안 왼→오.
    같은 줄 조각은 띄어 잇고, 줄과 줄 사이는 kiwipiepy 띄어쓰기 판단으로 잇는다 (단어 중간 줄바꿈 대응)
  - 덩어리 순서: 위쪽부터. 세로 범위가 절반 이상 겹치는 덩어리끼리는 같은 행으로 보고 왼→오.

입력 CSV (OCR 줄 1개 = 1행, utf-8-sig): image_id, text, x1, y1, x2, y2, confidence  (+ 다른 열은 덩어리 첫 줄 값을 그대로 이어 받음)
출력 CSV: block_id, image_id, (입력의 다른 열), block_order, text, line_count, x1, y1, x2, y2, confidence(평균)
실행:  py -3.12 korean/kr_ocr_blocks.py <입력 OCR 줄 CSV> <출력 덩어리 CSV>
검수: 올리브영 상세 이미지 50장 × 2회 (docs/한국어_OCR_후처리.md)
"""
import csv
import re
import statistics
import sys
from collections import defaultdict

STACK_GAP = 0.9        # 위아래 간격이 (작은 쪽) 글자 높이의 이 배수 이하면 붙은 것. 큰 쪽 기준이면 나란한 수치 카드끼리 붙었다
MIN_X_OVERLAP = 0.2    # 위아래 상자가 가로로 이만큼(좁은 쪽 기준) 겹치면 같은 칸
CENTER_TOL = 0.25      # 가운데 정렬 글: 가로 중심 차가 넓은 쪽 너비의 이 비율 이하
MAX_H_RATIO = 2.2      # 글자 크기 비가 이보다 크면 다른 성격(큰 제목 ↔ 작은 주석)
TITLE_H_RATIO = 1.5    # 큰 쪽이 숫자 없는 글이면 이 비율부터 '제목 ↔ 설명'으로 보고 나눈다
SAME_LINE_GAP = 0.4    # 같은 줄 조각 사이 가로 간격 한도 (글자 높이 배수). 0.8 이면 좁은 두 칸(STEP1·STEP2 설명)이 붙었다
FOOTNOTE = re.compile(r"^\s*(\*|※|\d{1,2}\)|\(\d{1,2}\))")   # 각주·주석은 본문과 묶지 않는다
BULLET = re.compile(r"^\s*[·•▪◦■□●○✓✔-]")                 # 글머리 기호로 시작하는 줄은 새 항목
MERGED = re.compile(r"(?<=다\.)(?=[가-힣A-Za-z])")           # 'OO합니다.XX' = OCR 이 옆 칸 글까지 한 상자로 읽은 것
ASCII_WORD = re.compile(r"[A-Za-z0-9]")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def needs_space(kiwi, prev_text, next_text):
    """두 줄을 이을 때 사이에 띄어쓰기를 넣어야 하는지.
    문장 전체에 띄어쓰기 교정을 걸면 '엑스폴리에이팅'이 '엑스 폴리 에이 팅'으로 쪼개지는 등 원문이 망가지므로,
    원문은 그대로 두고 이어 붙이는 '경계' 앞뒤 몇 글자만 kiwi 띄어쓰기 교정에 물어본다. 영어·숫자끼리는 항상 띄운다."""
    if not prev_text or not next_text:
        return False
    a, b = prev_text[-1], next_text[0]
    if a in ".!?…,:;)]”\"'":
        return True
    if ASCII_WORD.match(a) and ASCII_WORD.match(b):
        return True
    if kiwi is None:
        return True
    tail, head = prev_text[-8:], next_text[:8]
    spaced = kiwi.space(tail + head)
    n_tail = len(tail.replace(" ", ""))   # tail 안의 띄어쓰기는 빼고 세야 경계 위치가 맞는다
    seen = 0
    for ch in spaced:
        if ch == " ":
            if seen == n_tail:
                return True
            continue
        seen += 1
        if seen > n_tail:
            break
    return False


def h(b):
    return max(1, b["y2"] - b["y1"])


def split_merged(boxes):
    """OCR 이 두 칸 글을 한 상자로 읽은 경우('잡아줍니다.눈썹빈곳을…') 글자 수 비율로 상자를 나눈다.
    나뉜 조각끼리는 서로 묶지 않는다(sib) → 각 조각이 위쪽 자기 칸 글과 묶인다"""
    out = []
    for k, b in enumerate(boxes):
        parts = [p for p in MERGED.split(b["text"]) if p.strip()]
        if len(parts) < 2:
            out.append(b); continue
        total, x = sum(len(p) for p in parts), b["x1"]
        for p in parts:
            w = (b["x2"] - b["x1"]) * len(p) / total
            out.append({**b, "text": p, "x1": int(x), "x2": int(x + w), "sib": k})
            x += w
    return out


def linked(a, b):
    if "sib" in a and a.get("sib") == b.get("sib"):
        return False
    ha, hb = h(a), h(b)
    if max(ha, hb) / min(ha, hb) > MAX_H_RATIO:
        return False
    big = a if ha >= hb else b
    if max(ha, hb) / min(ha, hb) > TITLE_H_RATIO and not re.search(r"\d", big["text"]):
        return False
    cya, cyb = (a["y1"] + a["y2"]) / 2, (b["y1"] + b["y2"]) / 2
    top, bot = (a, b) if (a["y1"], a["x1"]) <= (b["y1"], b["x1"]) else (b, a)
    # 각주 아래 이어지는 줄(별표 없음)은 각주에 붙인다. 본문 아래 각주는 떼어 둔다
    if bool(FOOTNOTE.match(top["text"])) != bool(FOOTNOTE.match(bot["text"])) and not FOOTNOTE.match(top["text"]):
        return False
    # ② 같은 줄
    if abs(cya - cyb) <= min(ha, hb) * 0.5:
        if FOOTNOTE.match(a["text"]) or FOOTNOTE.match(b["text"]):
            if bool(FOOTNOTE.match(a["text"])) != bool(FOOTNOTE.match(b["text"])):
                return False
        gap = max(a["x1"], b["x1"]) - min(a["x2"], b["x2"])
        return gap <= min(ha, hb) * SAME_LINE_GAP
    # ① 위아래
    if BULLET.match(bot["text"]):
        return False
    gap = bot["y1"] - top["y2"]
    if gap < -min(ha, hb) * 0.5 or gap > min(ha, hb) * STACK_GAP:
        return False
    left, right = max(a["x1"], b["x1"]), min(a["x2"], b["x2"])
    narrow = min(a["x2"] - a["x1"], b["x2"] - b["x1"]) or 1
    if (right - left) / narrow >= MIN_X_OVERLAP:
        return True
    wide = max(a["x2"] - a["x1"], b["x2"] - b["x1"]) or 1
    return abs((a["x1"] + a["x2"]) / 2 - (b["x1"] + b["x2"]) / 2) <= wide * CENTER_TOL


def components(boxes):
    """union-find 로 서로 붙은 상자들을 덩어리로 모은다"""
    parent = list(range(len(boxes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if linked(boxes[i], boxes[j]):
                parent[find(i)] = find(j)
    groups = defaultdict(list)
    for i, b in enumerate(boxes):
        groups[find(i)].append(b)
    return list(groups.values())


def lines_of(block):
    """덩어리 안을 줄로 나눈다 (세로 중심이 낮은 쪽 높이의 절반 이내면 같은 줄)"""
    rows = []
    for b in sorted(block, key=lambda b: (b["y1"] + b["y2"]) / 2):
        cy = (b["y1"] + b["y2"]) / 2
        if rows and abs(cy - rows[-1]["cy"]) <= min(h(b), rows[-1]["h"]) * 0.5:
            rows[-1]["items"].append(b)
        else:
            rows.append({"cy": cy, "h": h(b), "items": [b]})
    return [sorted(r["items"], key=lambda b: b["x1"]) for r in rows]


def order_blocks(blocks):
    """위쪽부터. 세로 범위가 절반 이상 겹치면 같은 행 → 왼쪽부터"""
    info = [{"b": bl, "x1": min(x["x1"] for x in bl), "y1": min(x["y1"] for x in bl),
             "y2": max(x["y2"] for x in bl)} for bl in blocks]
    info.sort(key=lambda d: d["y1"])
    rows = []
    for d in info:
        r = rows[-1] if rows else None
        if r:
            f = r[0]
            ov = min(f["y2"], d["y2"]) - max(f["y1"], d["y1"])
            if ov >= 0.5 * min(f["y2"] - f["y1"], d["y2"] - d["y1"]):
                r.append(d); continue
        rows.append([d])
    return [d["b"] for r in rows for d in sorted(r, key=lambda d: d["x1"])]


def blocks_of_image(boxes, kiwi):
    """한 이미지의 OCR 줄 → [(덩어리 상자 목록, 이은 글)]  (읽는 순서대로)"""
    out = []
    for bl in order_blocks(components(split_merged(boxes))):
        text = ""
        for line in lines_of(bl):
            piece = " ".join(x["text"].strip() for x in line)
            text = piece if not text else (text + (" " if needs_space(kiwi, text, piece) else "") + piece)
        out.append((bl, text))
    return out


CORE = ("image_id", "text", "x1", "y1", "x2", "y2", "confidence")


def main():
    if len(sys.argv) < 3:
        print("사용법: py -3.12 korean/kr_ocr_blocks.py <입력 OCR 줄 CSV> <출력 덩어리 CSV>")
        sys.exit(1)
    src, dst = sys.argv[1], sys.argv[2]
    try:
        from kiwipiepy import Kiwi
        kiwi = Kiwi()
    except ImportError:
        kiwi = None
        print("[주의] kiwipiepy 가 없어 줄 사이를 항상 띄어 잇습니다 (pip install kiwipiepy 권장)")
    rows = list(csv.DictReader(open(src, encoding="utf-8-sig")))
    extra = [c for c in rows[0].keys() if c not in CORE and c not in ("line_id",)] if rows else []
    by_img = defaultdict(list)
    for r in rows:
        for k in ("x1", "y1", "x2", "y2"):
            r[k] = int(float(r[k]))
        by_img[r["image_id"]].append(r)
    out, n = [], 0
    for img, boxes in by_img.items():
        for order, (bl, text) in enumerate(blocks_of_image(boxes, kiwi), 1):
            n += 1
            f = bl[0]
            out.append({"block_id": f"B{n:06d}", "image_id": img, **{c: f.get(c, "") for c in extra},
                        "block_order": order, "text": text, "line_count": len(bl),
                        "x1": min(x["x1"] for x in bl), "y1": min(x["y1"] for x in bl),
                        "x2": max(x["x2"] for x in bl), "y2": max(x["y2"] for x in bl),
                        "confidence": round(statistics.mean(float(x["confidence"]) for x in bl), 3)})
    with open(dst, "w", newline="", encoding="utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
    print(f"이미지 {len(by_img)}장, 글자 상자 {len(rows)}개 → 덩어리 {len(out)}개  ({dst})")


if __name__ == "__main__":
    main()
