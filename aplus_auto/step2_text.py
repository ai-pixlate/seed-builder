"""② 글자 읽기 — 확정 섹션마다 한국어 글을 붙인다.

이 상품(A000000206826)은 2026-09-07 올리브영 표현빈도 작업 때 이미 한국어 OCR을 마쳤다
(PaddleOCR, 팀 확정 설정: PP-OCRv5_server_det + korean_PP-OCRv5_mobile_rec).
같은 원본 그림(가로·세로 크기 같음)이라 좌표가 그대로 맞으므로 **다시 OCR 하지 않고 그 결과를 쓴다**(무료·즉시).
    Desktop/Oliveyoung_표현빈도/data/main/kr_ocr_joined.csv  (줄을 문단으로 묶은 것)

문단 가운데 높이(y)가 섹션 범위 안에 있으면 그 섹션 글로 본다.

    py -3.12 aplus_auto/step2_text.py --product A000000206826

출력: aplus_auto/work/<상품>/step2/
    section_texts.json   섹션별 문단 목록 — ③ 라벨 단계 입력
    글자확인.html         확인 화면
"""
import argparse
import csv
import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OCR = Path(r"C:\Users\인공지능사관학교\Desktop\Oliveyoung_표현빈도\data\main\kr_ocr_joined.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--name", default="")
    a = ap.parse_args()

    base = HERE / "work" / a.product
    secs = json.loads((base / "step1_final" / "sections.json").read_text(encoding="utf-8"))["sections"]
    rows = []
    if OCR.exists():
        with open(OCR, encoding="utf-8-sig") as f:
            rows = [r for r in csv.DictReader(f) if r["goods_no"] == a.product]
    if not rows:
        return fresh_ocr(a, base, secs)

    used = set()
    out = []
    for s in secs:
        paras, off = [], 0
        for part in s.get("parts") or [{"image": s["image"], "range": s["range"]}]:  # 여러 그림에 걸친 섹션
            stem = Path(part["image"]).stem
            y0, y1 = part["range"]
            for i, r in enumerate(rows):
                if r["image_id"] != stem:
                    continue
                cy = (int(r["y1"]) + int(r["y2"])) / 2
                if y0 <= cy < y1:
                    used.add(i)
                    paras.append({"text": r["text"].strip(), "x1": int(r["x1"]), "y1": int(r["y1"]) - y0 + off,
                                  "x2": int(r["x2"]), "y2": int(r["y2"]) - y0 + off,
                                  "conf": float(r["confidence"] or 0)})
            off += y1 - y0
        paras.sort(key=lambda p: (p["y1"], p["x1"]))
        out.append({**s, "paragraphs": paras})

    left = len(rows) - len(used)
    dst = base / "step2"
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "section_texts.json").write_text(json.dumps(
        {"product": a.product, "ocr_source": str(OCR), "sections": out}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    (dst / "글자확인.html").write_text(page(a, out, len(rows), left), encoding="utf-8")
    n = sum(len(s["paragraphs"]) for s in out)
    print(f"섹션 {len(out)}개에 문단 {n}개 배정 (OCR 문단 {len(rows)}개 중 빠진 것 {left}개 — 빼낸 빈 띠 등)")
    print(dst / "글자확인.html")


def fresh_ocr(a, base, secs):
    """기존 OCR 이 없는 상품(업로드한 상품): 확정 섹션 그림마다 PaddleOCR 로 새로 읽는다. 진행 내용을 캐시해 이어서 하기 가능."""
    import time
    from ocr_kr import paragraphs, read_lines
    dst = base / "step2"
    dst.mkdir(parents=True, exist_ok=True)
    cache_p = dst / "ocr_cache.json"
    cache = json.loads(cache_p.read_text(encoding="utf-8")) if cache_p.exists() else {}
    t0 = time.time()
    out = []
    for i, s in enumerate(secs, 1):
        crop = s["crop"] if Path(s["crop"]).is_absolute() else str(HERE.parent / s["crop"])
        parts = s.get("parts") or [{"image": s["image"], "range": s["range"]}]
        key = s["sid"] + "|" + ";".join(f"{p['image']}:{p['range'][0]}-{p['range'][1]}" for p in parts)
        if key not in cache:
            cache[key] = paragraphs(read_lines(crop))
            cache_p.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        print(f"  글자 읽기 {i}/{len(secs)} {s['sid']} 문단 {len(cache[key])}개 ({time.time() - t0:.0f}초)", flush=True)
        out.append({**s, "paragraphs": cache[key]})
    (dst / "section_texts.json").write_text(json.dumps(
        {"product": a.product, "ocr_source": "PaddleOCR 새로 읽음 (ocr_kr.py)", "sections": out},
        ensure_ascii=False, indent=1), encoding="utf-8")
    n = sum(len(s["paragraphs"]) for s in out)
    (dst / "글자확인.html").write_text(page(a, out, n, 0), encoding="utf-8")
    print(f"섹션 {len(out)}개 · 문단 {n}개 (새로 읽음)")


CSS = """
:root{--bg:#f4f5f7;--card:#fff;--ink:#1d2127;--sub:#5d6670;--line:#dfe3e8}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 "Malgun Gothic",system-ui,sans-serif}
header{position:sticky;top:0;background:var(--card);border-bottom:1px solid var(--line);padding:12px 16px;z-index:2}
h1{font-size:18px;margin:0}.sum{color:var(--sub)}
main{max-width:1200px;margin:0 auto;padding:12px 16px 60px}
.guide{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 16px;margin:12px 0}
.sec{display:grid;grid-template-columns:260px 1fr;gap:18px;background:var(--card);border:1px solid var(--line);
border-radius:10px;padding:14px;margin-top:14px}
@media (max-width:800px){.sec{grid-template-columns:1fr}}
.th{max-height:520px;overflow:auto;border:1px solid var(--line);border-radius:6px}.th img{display:block;width:100%}
.sid{font-weight:700;font-size:16px}.meta{color:var(--sub);font-size:12.5px;margin-bottom:6px}
ol{margin:0;padding-left:22px}li{margin:2px 0}.low{color:#b45309}.none{color:var(--sub)}
"""


def page(a, secs, total, left):
    e = html.escape
    cards = []
    for s in secs:
        items = "".join(
            f'<li class="{"low" if p["conf"] < 0.8 else ""}">{e(p["text"])}</li>' for p in s["paragraphs"])
        body = f"<ol>{items}</ol>" if items else '<p class="none">읽은 글 없음 (사진·그래프만 있는 섹션)</p>'
        cards.append(f"""<div class="sec"><div class="th"><img src="../step1_final/{e(s['thumb'])}" loading="lazy"></div>
<div><div class="sid">{s['sid']} <span class="meta">{e(s.get('ai_label',''))}</span></div>
<div class="meta">문단 {len(s['paragraphs'])}개</div>{body}</div></div>""")
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>② 글자 확인 {e(a.product)}</title><style>{CSS}</style></head><body>
<header><h1>② 글자 읽기 확인 — {e(a.name)} ({e(a.product)})</h1>
<span class="sum">섹션 {len(secs)}개 · OCR 문단 {total}개 (기존 OCR 재사용: 2026-09-07 표현빈도 작업)</span></header>
<main><div class="guide">왼쪽 섹션 그림, 오른쪽 읽은 글(위→아래 순서). <span class="low">주황색</span>은 OCR 확신도 0.8 미만.
글자를 조금 틀리게 읽은 곳은 다음 단계(라벨)에서 Claude가 그림도 함께 보므로 크게 문제되지 않음.
<b>통째로 빠진 글</b>이나 <b>다른 섹션 글이 섞인 곳</b>이 있으면 알려 주세요.</div>
{''.join(cards)}</main></body></html>"""


if __name__ == "__main__":
    main()
