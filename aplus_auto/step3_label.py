"""③ 라벨 붙이기 — 섹션마다 A+ 내용 종류 라벨(v1.4, 19개)을 붙이고 7칸에 연결한다.

라벨 정의: Claude outputs/A+내용종류_분류가이드_v1.4_2026-11-08.md (아마존 A+ 2,054장 분류에 쓴 것과 같음)
7칸 연결:  Claude outputs/A+템플릿_3_확정7칸_2026-11-09.png
    1 제품 소개 HERO · 2 효능 BENEFIT · 3 성분 INGREDIENT · 4 신뢰·증명 PROOF·CERT·COMPARE (SOCIAL 은 7칸 밖, 11-11 결정)
    5 옵션·라인업 VARIANT·LINEUP · 6 사용법·루틴 HOWTO·ROUTINE · 7 브랜드 BRAND
    그 밖(SOCIAL·TEXTURE·FEATURE·TARGET·PROBLEM·LOGO·FAQ·OTHER) → 7칸에 직접 안 들어감(보조 재료로만)

Claude 에 섹션 그림 + OCR 글을 한 번에 보낸다(호출 1회). 응답은 캐시해 다시 돌려도 비용 0.

    py -3.12 aplus_auto/step3_label.py --product A000000206826 --dry-run
    py -3.12 aplus_auto/step3_label.py --product A000000206826

출력: aplus_auto/work/<상품>/step3/labels.json, 라벨확인.html
"""
import argparse
import base64
import hashlib
import html
import io
import json
import os
import re
import sys
from pathlib import Path

from PIL import Image

Image.MAX_IMAGE_PIXELS = None
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
MODEL = "claude-opus-5-5"
PRICE_IN, PRICE_OUT = 4.00, 20.00
MAX_EDGE = 1568

SLOTS = {"HERO": 1, "BENEFIT": 2, "INGREDIENT": 3, "PROOF": 4, "CERT": 4, "COMPARE": 4,  # SOCIAL(리뷰·평판)은 7칸 밖 — 2026-11-11 사용자 결정
         "VARIANT": 5, "LINEUP": 5, "HOWTO": 6, "ROUTINE": 6, "BRAND": 7}
SLOT_NAME = {1: "제품 소개", 2: "효능", 3: "성분", 4: "신뢰·증명", 5: "옵션·라인업", 6: "사용법·루틴", 7: "브랜드"}

# 분류가이드 v1.4 본문을 그대로 쓰되, 대상이 '아마존 A+ 가로 배너'가 아니라 '한국 상세페이지 섹션'인 점만 바꿈
GUIDE = (REPO / "Claude outputs" / "A+내용종류_분류가이드_v1.4_2026-11-08.md").read_text(encoding="utf-8")
SYSTEM = f"""너는 한국 화장품 상세페이지의 섹션을 아마존 A+ 내용 종류 라벨로 분류한다.
아래 가이드는 원래 아마존 A+ 이미지용이다. 이번에는 **한국 올리브영 상세페이지를 내용 단위로 자른 섹션**에 같은 라벨을 붙인다.
섹션은 세로로 길 수 있고, 섹션마다 그림과 그 안에서 읽은 한국어 글(OCR, 오타 있을 수 있음)을 함께 준다.
가이드의 '이미지 위 노란 글자 ID' 대신 섹션 ID(S01 등)를 쓴다.

=== 가이드 시작 ===
{GUIDE}
=== 가이드 끝 ===

추가 출력 칸
- "reason": 이 라벨로 본 이유 한 문장(한국어)
- "summary": 이 섹션이 말하는 핵심을 한국어 한두 문장으로
출력은 JSON 배열 하나만. 섹션 순서대로, 설명을 붙이지 않는다."""


def fingerprint():
    return hashlib.sha256(json.dumps({"s": SYSTEM, "m": MODEL, "e": MAX_EDGE}).encode()).hexdigest()[:10]


def shrink(path):
    im = Image.open(path).convert("RGB")
    s = min(1.0, MAX_EDGE / max(im.size))
    if s < 1:
        im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    return im


def b64(im):
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode()


def load_key():
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--name", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    base = HERE / "work" / a.product
    secs = json.loads((base / "step2" / "section_texts.json").read_text(encoding="utf-8"))["sections"]
    content, img_tok, txt_chars = [], 0, 0
    for s in secs:
        im = shrink(s["crop"])
        img_tok += im.width * im.height / 750
        text = "\n".join(p["text"] for p in s["paragraphs"]) or "(읽은 글 없음)"
        txt_chars += len(text)
        content.append({"type": "text", "text": f"[{s['sid']}] 읽은 글:\n{text}"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64(im)}})
    content.append({"type": "text", "text": f"섹션 {len(secs)}개를 분류해 JSON 배열로 답하라. 항목 형식: "
                    '{"tid":"S01","label":"HERO","sub":[],"opt":"","conf":"high","note":"","reason":"","summary":""}'})

    est_in = img_tok + txt_chars * 1.2 + len(SYSTEM) * 1.2
    est_out = 150 * len(secs) + 3000
    if a.dry_run:
        print(f"섹션 {len(secs)}개 · 이미지 토큰 약 {img_tok:,.0f} · 글 {txt_chars:,}자")
        print(f"입력 약 {est_in:,.0f} 토큰 · 출력 약 {est_out:,} 토큰 → 예상 ${est_in/1e6*PRICE_IN + est_out/1e6*PRICE_OUT:.2f}. 호출 없음")
        return

    out = base / "step3"
    cache = out / "cache" / fingerprint()
    cache.mkdir(parents=True, exist_ok=True)
    cp = cache / "answer.json"
    if cp.exists():
        c = json.loads(cp.read_text(encoding="utf-8"))
        ans, usage = c["answer"], c["usage"]
        print("캐시 사용 (비용 0)")
    else:
        load_key()
        import anthropic
        client = anthropic.Anthropic()
        with client.messages.stream(model=MODEL, max_tokens=32000, system=SYSTEM,
                                    output_config={"effort": "medium"},
                                    messages=[{"role": "user", "content": content}]) as st:
            res = st.get_final_message()
        if res.stop_reason == "refusal":
            raise SystemExit("Claude 가 거절함")
        text = "".join(b.text for b in res.content if b.type == "text")
        m = re.search(r"\[.*\]", text, re.S)
        ans = json.loads(m.group(0))
        usage = {"in": res.usage.input_tokens, "out": res.usage.output_tokens}
        cp.write_text(json.dumps({"answer": ans, "usage": usage}, ensure_ascii=False, indent=1), encoding="utf-8")
    cost = usage["in"] / 1e6 * PRICE_IN + usage["out"] / 1e6 * PRICE_OUT
    print(f"in {usage['in']} out {usage['out']} · ${cost:.4f}")

    by = {x["tid"]: x for x in ans}
    rows = []
    for s in secs:
        x = by.get(s["sid"], {})
        lab = x.get("label", "OTHER")
        rows.append({"sid": s["sid"], "thumb": s["thumb"], "ai_split_name": s.get("ai_label", ""),
                     "label": lab, "sub": x.get("sub", []), "opt": x.get("opt", ""), "conf": x.get("conf", ""),
                     "note": x.get("note", ""), "reason": x.get("reason", ""), "summary": x.get("summary", ""),
                     "slot": SLOTS.get(lab), "texts": [p["text"] for p in s["paragraphs"]]})
    (out / "labels.json").write_text(json.dumps({"product": a.product, "model": MODEL, "usage": usage,
                                                 "cost_usd": round(cost, 4), "sections": rows},
                                                ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "라벨확인.html").write_text(page(a, rows), encoding="utf-8")
    print(out / "라벨확인.html")


LABELS = ["HERO", "BENEFIT", "INGREDIENT", "PROOF", "COMPARE", "HOWTO", "ROUTINE", "LINEUP", "VARIANT", "TEXTURE",
          "FEATURE", "TARGET", "PROBLEM", "CERT", "SOCIAL", "BRAND", "LOGO", "FAQ", "OTHER"]
KO = {"HERO": "제품 소개", "BENEFIT": "핵심 효능·특징", "INGREDIENT": "성분·기술", "PROOF": "효과 증명",
      "COMPARE": "비교", "HOWTO": "사용법", "ROUTINE": "루틴", "LINEUP": "라인업", "VARIANT": "색상·옵션",
      "TEXTURE": "제형·사용감", "FEATURE": "제품 디테일", "TARGET": "추천 대상", "PROBLEM": "고민 제시",
      "CERT": "인증·검증", "SOCIAL": "신뢰·평판", "BRAND": "브랜드 이야기", "LOGO": "로고 띠", "FAQ": "질문·안내",
      "OTHER": "기타"}

CSS = """
:root{--bg:#f4f5f7;--card:#fff;--ink:#1d2127;--sub:#5d6670;--line:#dfe3e8;--acc:#2f6fd6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 "Malgun Gothic",system-ui,sans-serif}
header{position:sticky;top:0;background:var(--card);border-bottom:1px solid var(--line);padding:12px 16px;z-index:2;
display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center}
h1{font-size:18px;margin:0}.sum{color:var(--sub)}
button{font:inherit;padding:6px 14px;border-radius:6px;border:1px solid var(--acc);background:var(--acc);color:#fff;cursor:pointer}
main{max-width:1250px;margin:0 auto;padding:12px 16px 60px}
.guide,.slots{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 16px;margin:12px 0}
.slots table{border-collapse:collapse;width:100%}.slots td,.slots th{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left}
.sec{display:grid;grid-template-columns:240px 1fr;gap:18px;background:var(--card);border:1px solid var(--line);
border-radius:10px;padding:14px;margin-top:14px}
@media (max-width:800px){.sec{grid-template-columns:1fr}}
.th{max-height:480px;overflow:auto;border:1px solid var(--line);border-radius:6px}.th img{display:block;width:100%}
.tag{display:inline-block;padding:2px 10px;border-radius:12px;font-weight:700;font-size:13px;margin-right:6px}
.s1{background:#fde2e2}.s2{background:#e3f1e5}.s3{background:#e2ecfb}.s4{background:#fff1d6}.s5{background:#efe4fb}
.s6{background:#dff4f4}.s7{background:#f1e9df}.s0{background:#eceff2;color:#5d6670}
.low{color:#b45309;font-weight:700}.meta{color:var(--sub);font-size:12.5px}
details{margin-top:6px}summary{cursor:pointer;color:var(--sub);font-size:12.5px}
select,textarea{font:inherit}textarea{width:100%;min-height:40px;border:1px solid var(--line);border-radius:6px;padding:6px}
.fix{display:flex;gap:8px;align-items:center;margin-top:8px;flex-wrap:wrap}
"""

JS = """
const KEY='step3_review_'+document.body.dataset.product;
let st={};try{st=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}
function save(){try{localStorage.setItem(KEY,JSON.stringify(st))}catch(e){}}
document.querySelectorAll('.sec').forEach(el=>{const id=el.dataset.sid,v=st[id]||{};
 const s=el.querySelector('select'),t=el.querySelector('textarea');
 if(v.l)s.value=v.l; t.value=v.m||'';
 s.onchange=()=>{st[id]={...(st[id]||{}),l:s.value};save()}; t.oninput=()=>{st[id]={...(st[id]||{}),m:t.value};save()}});
document.getElementById('csv').onclick=()=>{const rows=[['섹션','AI라벨','고친라벨','메모']];
 document.querySelectorAll('.sec').forEach(el=>{const v=st[el.dataset.sid]||{};rows.push([el.dataset.sid,el.dataset.label,v.l||'',v.m||''])});
 const csv='\\ufeff'+rows.map(r=>r.map(x=>'"'+String(x).replace(/"/g,'""')+'"').join(',')).join('\\r\\n');
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download='라벨확인_결과.csv';a.click()};
"""


def page(a, rows):
    e = html.escape
    opts = '<option value="">(맞음 — 그대로)</option>' + "".join(
        f'<option value="{l}">{l} {KO[l]}</option>' for l in LABELS)
    slot_rows = []
    for n in range(1, 8):
        hits = [r["sid"] for r in rows if r["slot"] == n]
        slot_rows.append(f"<tr><td><span class='tag s{n}'>{n} {SLOT_NAME[n]}</span></td>"
                         f"<td>{', '.join(hits) if hits else '<b style=color:#c62828>없음 (빈 칸)</b>'}</td></tr>")
    rest = [r["sid"] + " " + r["label"] for r in rows if not r["slot"]]
    slot_rows.append(f"<tr><td><span class='tag s0'>7칸 밖</span></td><td>{', '.join(rest) or '-'}</td></tr>")
    cards = []
    for r in rows:
        n = r["slot"] or 0
        subs = " ".join(f"<span class='tag s0'>보조 {e(x)}</span>" for x in r["sub"])
        cards.append(f"""<div class="sec" data-sid="{r['sid']}" data-label="{r['label']}">
<div class="th"><img src="../step1_final/{e(r['thumb'])}" loading="lazy"></div>
<div><div><b style="font-size:16px">{r['sid']}</b> &nbsp;
<span class="tag s{n}">{r['label']} {KO.get(r['label'], '')}</span>{subs}
<span class="meta">→ {('칸 ' + str(n) + ' ' + SLOT_NAME[n]) if n else '7칸 밖'}</span>
{'<span class="low">애매함</span>' if r['conf'] == 'low' else ''}</div>
<p><b>핵심:</b> {e(r['summary'])}</p><p class="meta"><b>이유:</b> {e(r['reason'])} {e(r['note'])}</p>
<details><summary>읽은 글 {len(r['texts'])}개 보기</summary><ol>{''.join('<li>' + e(t) + '</li>' for t in r['texts'])}</ol></details>
<div class="fix">라벨이 틀렸으면 고르기: <select>{opts}</select></div>
<textarea placeholder="메모 (예: 이건 효능보다 성분 설명에 가까움)"></textarea></div></div>""")
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>③ 라벨 확인 {e(a.product)}</title><style>{CSS}</style></head><body data-product="{e(a.product)}">
<header><h1>③ 라벨 확인 — {e(a.name)} ({e(a.product)})</h1><span class="sum">섹션 {len(rows)}개 · 라벨 기준 v1.4 (아마존 A+ 분류와 같음)</span>
<button id="csv">판단 결과 CSV 내려받기</button></header>
<main><div class="slots"><b>7칸에 들어갈 재료</b> (라벨 → 칸 연결은 확정 7칸 기준)<table>{''.join(slot_rows)}</table></div>
<div class="guide">섹션마다 AI가 붙인 라벨과 이유를 확인하고, 틀렸으면 아래 목록에서 맞는 라벨을 고르고 메모. 끝나면 CSV 내려받기.</div>
{''.join(cards)}</main><script>{JS}</script></body></html>"""


if __name__ == "__main__":
    main()
