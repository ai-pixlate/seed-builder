"""⑤ 내용 충실도 점검 (E단계) — 7장의 영어 문구가 한국어 원본 내용을 사실대로 옮겼는지 Claude 가 칸마다 찾아 표시한다.

번역 표현 다듬기는 범위 밖(2026-11-11 결정). 사실만 본다:
  지어냄  원본에 없는 효능·수치·성분·주장
  수치    숫자·단위·시험 조건(대상·기간·기관)이 원본과 다름
  빠짐    그 장 원본 섹션의 핵심 내용(대표 수치·핵심 성분 등)이 빠짐
  섞임    그 장 재료가 아닌 다른 섹션 내용이 글에 들어감

    py -3.12 aplus_auto/step5_fidelity.py --product A000000206826 --base v6_fill --dry-run
    py -3.12 aplus_auto/step5_fidelity.py --product <상품…> --base v6_fill
    py -3.12 aplus_auto/step5_fidelity.py --page --base v6_fill      (8개 상품 검수 화면)

입력: work/<상품>/step4/variants/<base>/plan.json, step2/section_texts.json, step3/labels_final.json (사진 안 보냄 → 저렴)
출력: work/<상품>/step5/<base>/fidelity.json, work/_eval/내용충실도_<base>.html
"""
import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path

import step4_fill as S

HERE = S.HERE
TYPES = ["지어냄", "수치", "빠짐", "섞임"]

SYSTEM = """너는 한국 화장품 상세페이지를 아마존 A+ 모듈(영어)로 옮긴 결과를 검수한다. **사실이 맞는지만** 본다.
영어 표현이 자연스러운지, 직역인지, 규제에 걸리는지는 보지 않는다(범위 밖).

장마다 영어 문구(필드별)와 그 장의 재료 섹션(한국어 OCR 글·요약), 그리고 상품 전체 섹션(요약 + OCR 글 전부)이 주어진다.
다른 섹션에 있는 내용이면 '지어냄'이 아니라 '섞임'이다.
다음 4가지 문제만 찾는다.
- 지어냄: 한국어 원본(상품 전체 어디에도) 없는 효능·수치·성분·주장. 일반적인 설명 표현("for daily use", "gentle")처럼 원본 뜻에서 자연스럽게 나온 말은 문제 아님.
- 수치: 숫자·단위·%·배수·시험 대상 수·기간·기관 이름이 원본과 다르거나, 조건 없이 수치만 써서 뜻이 달라짐.
- 빠짐: 그 장 재료 섹션의 **핵심**(대표 수치, 핵심 성분, 단계 등)이 빠져 그 장이 원본과 다른 이야기가 됨. 칸 크기 때문에 줄인 사소한 내용은 문제 아님.
- 섞임: 그 장 재료 섹션이 아닌 다른 섹션의 내용이 글에 들어감(상품명·브랜드명은 문제 아님). 재료가 [] 인 장(제품 소개 예외)은 상품 전체 기준으로만 본다.
OCR 글에는 오타·끊김이 있을 수 있다. 확실한 것만 적고, 애매하면 severity "낮음".

출력은 JSON 배열 하나, 설명을 붙이지 않는다:
[{"card":1,"issues":[{"type":"수치","field":"body","en":"문제 영어 부분","ko":"원본 근거(없으면 '없음')","note":"무엇이 다른지 한국어 한 문장","severity":"높음"}]}, ...]
문제 없는 장은 "issues":[] 로 둔다. 모든 장을 순서대로 적는다."""


def fields_of(c):
    out = []
    for k in ("label", "headline", "subheadline", "body"):
        if c.get(k):
            out.append((k, c[k]))
    for i, it in enumerate(c.get("items") or []):
        for k in ("title", "body"):
            if it.get(k):
                out.append((f"items[{i}].{k}", it[k]))
    return out


def load(p, base):
    w = HERE / "work" / p
    plan = json.loads((w / "step4" / "variants" / base / "plan.json").read_text(encoding="utf-8"))
    labels = {s["sid"]: s for s in json.loads((w / "step3" / "labels_final.json").read_text(encoding="utf-8"))["sections"]}
    texts = {sid: s.get("texts") or [] for sid, s in labels.items()}  # OCR 글은 labels_final 의 texts (section_texts 는 paragraphs)
    meta = w / "meta.json"
    name = json.loads(meta.read_text(encoding="utf-8")).get("name", "") if meta.exists() else ""
    return w, plan, labels, texts, name


def request(plan, labels, texts, name):
    lines = [f"상품: {S.clean_name(name)}", "", "[상품 전체 섹션 — 요약과 OCR 글 전부. '지어냄'은 여기 어디에도 없을 때만]"]
    for sid, s in labels.items():
        lines.append(f"  {sid} {s['label']}: {s.get('summary', '')}")
        lines += [f"     {t}" for t in texts.get(sid, [])]
    for x in plan["slots"]:
        if not x.get("template"):
            continue
        tag = f"보충 칸({x.get('fill_type')})" if x.get("fill") else f"원래 칸 {x.get('orig_slot', x['slot'])} {S.SLOT_NAME[x.get('orig_slot', x['slot'])]}"
        lines += ["", f"=== {x['slot']}장 · {tag} · 템플릿 {x['template']} · 재료 {x.get('sources') or []}", "[영어 문구]"]
        lines += [f"  {k}: {v}" for k, v in fields_of(x.get("content") or {})]
        lines.append("[재료 섹션 원본]")
        for sid in x.get("sources") or []:
            lines.append(f"  -- {sid} {labels.get(sid, {}).get('label', '')} · 요약: {labels.get(sid, {}).get('summary', '')}")
            lines += [f"     {t}" for t in texts.get(sid, [])]
        if not x.get("sources"):
            lines.append("  (재료 없음 — 상품 전체 요약 기준)")
    return "\n".join(lines)


def run_product(p, base, dry=False):
    w, plan, labels, texts, name = load(p, base)
    text = request(plan, labels, texts, name)
    out = w / "step5" / base
    out.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(json.dumps([SYSTEM, S.MODEL, text], ensure_ascii=False).encode()).hexdigest()[:10]
    cp = out / "cache" / key / "answer.json"
    if dry:
        tin = (len(SYSTEM) + len(text)) * 1.1
        tout = 4000
        print(f"{p}: 장 {sum(1 for x in plan['slots'] if x.get('template'))} · 입력 약 {tin:,.0f} 토큰 → 예상 ${tin / 1e6 * S.PRICE_IN + tout / 1e6 * S.PRICE_OUT:.2f}")
        return tin / 1e6 * S.PRICE_IN + tout / 1e6 * S.PRICE_OUT
    if cp.exists():
        c = json.loads(cp.read_text(encoding="utf-8"))
        ans, usage = c["answer"], c["usage"]
    else:
        S.load_key()
        import anthropic
        res = anthropic.Anthropic().messages.create(model=S.MODEL, max_tokens=16000, system=SYSTEM,
                                                    output_config={"effort": "medium"},
                                                    messages=[{"role": "user", "content": text}])
        raw = "".join(b.text for b in res.content if b.type == "text")
        ans = json.loads(re.search(r"\[.*\]", raw, re.S).group(0))
        usage = {"in": res.usage.input_tokens, "out": res.usage.output_tokens}
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps({"answer": ans, "usage": usage, "raw": raw, "request": text}, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    cost = usage["in"] / 1e6 * S.PRICE_IN + usage["out"] / 1e6 * S.PRICE_OUT
    by = {int(a["card"]): a.get("issues") or [] for a in ans}
    cards = []
    for x in plan["slots"]:
        if not x.get("template"):
            continue
        cards.append({"slot": x["slot"], "orig_slot": x.get("orig_slot"), "fill": bool(x.get("fill")),
                      "fill_type": x.get("fill_type"), "template": x["template"], "sources": x.get("sources") or [],
                      "png": (x.get("render") or {}).get("png"), "fields": fields_of(x.get("content") or {}),
                      "issues": by.get(x["slot"], [])})
    res = {"product": p, "name": name, "base": base, "usage": usage, "cost_usd": round(cost, 4), "cards": cards}
    (out / "fidelity.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    n = sum(len(c["issues"]) for c in cards)
    print(f"{p}: 문제 {n}개 (" + ", ".join(f"{t} {sum(1 for c in cards for i in c['issues'] if i.get('type') == t)}" for t in TYPES)
          + f") · ${cost:.4f}")
    return cost


CSS = """:root{--bg:#f4f5f7;--card:#fff;--ink:#1d2127;--sub:#5d6670;--line:#dfe3e8;--hi:#c62828;--lo:#b45309}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 "Malgun Gothic",system-ui,sans-serif}
header{position:sticky;top:0;z-index:3;background:var(--card);border-bottom:1px solid var(--line);padding:10px 16px}
h1{font-size:18px;margin:0}main{max-width:1500px;margin:0 auto;padding:12px 16px 80px}.sub{color:var(--sub)}
.prod{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin-top:16px}.prod h2{margin:0 0 6px;font-size:17px}
.card{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px;border-top:1px solid var(--line);padding:12px 0}
@media (max-width:1000px){.card{grid-template-columns:1fr}}
.card img{width:100%;border:1px solid var(--line)}.tag{display:inline-block;border-radius:10px;padding:0 8px;font-size:12px;background:#eef2f7;margin-right:6px}
.tag.fill{background:#7c3aed;color:#fff}table{border-collapse:collapse;width:100%;font-size:13px}td{border-bottom:1px solid var(--line);padding:3px 6px;vertical-align:top}
td.k{color:var(--sub);width:110px}.iss{border:1px solid var(--line);border-radius:8px;padding:6px 10px;margin-top:6px}
.iss.높음{border-left:4px solid var(--hi)}.iss.낮음{border-left:4px solid var(--lo)}.ok{color:#15803d}
details{margin-top:6px}pre{white-space:pre-wrap;font:12.5px/1.5 "Malgun Gothic",sans-serif;background:#f6f8fb;padding:8px;border-radius:6px;max-height:320px;overflow:auto}
textarea{width:100%;min-height:40px;font:inherit;border:1px solid var(--line);border-radius:6px;padding:6px;margin-top:6px}
button{font:inherit;padding:6px 14px;border-radius:6px;border:1px solid #2f6fd6;background:#2f6fd6;color:#fff;cursor:pointer}select{font:inherit}"""
JS = """const KEY='fid_review_'+document.body.dataset.base;let st={};try{st=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}
function save(){try{localStorage.setItem(KEY,JSON.stringify(st))}catch(e){}}
document.querySelectorAll('[data-k]').forEach(el=>{const k=el.dataset.k;if(st[k]!==undefined)el.value=st[k];el.oninput=el.onchange=()=>{st[k]=el.value;save()}});
document.getElementById('csv').onclick=()=>{const rows=[['상품','장','종류','문제번호','유형','필드','Claude 설명','판단','메모']];
 document.querySelectorAll('.iss').forEach(el=>{rows.push([el.dataset.p,el.dataset.slot,'Claude 문제',el.dataset.i,el.dataset.type,el.dataset.field,el.dataset.note,st[el.dataset.key+'_v']||'',''])});
 document.querySelectorAll('textarea[data-k]').forEach(el=>{const v=st[el.dataset.k]||'';if(v)rows.push([el.dataset.p,el.dataset.slot,'놓친 문제(메모)','','','','','',v])});
 const csv='\\ufeff'+rows.map(r=>r.map(x=>'"'+String(x).replace(/"/g,'""')+'"').join(',')).join('\\r\\n');
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download='내용충실도_검수.csv';a.click()};"""


def page(base):
    e = html.escape
    blocks, total, n_iss = [], 0.0, 0
    for d in sorted((HERE / "work").iterdir()):
        fj = d / "step5" / base / "fidelity.json"
        if not fj.exists():
            continue
        r = json.loads(fj.read_text(encoding="utf-8"))
        total += r.get("cost_usd", 0)
        _, plan, labels, texts, _ = load(d.name, base)
        rel = f"../{d.name}/step4/variants/{base}/"
        cards = []
        for c in r["cards"]:
            o = c.get("orig_slot") or c["slot"]
            head = (f'<span class="tag fill">보충 칸 · {e(c.get("fill_type") or "")}</span>' if c["fill"]
                    else f'<span class="tag">칸 {o} {S.SLOT_NAME.get(o, "")}</span>') + f'<span class="sub">{e(c["template"])} · 재료 {", ".join(c["sources"]) or "없음"}</span>'
            rows = "".join(f'<tr><td class="k">{e(k)}</td><td>{e(v)}</td></tr>' for k, v in c["fields"])
            src = "\n\n".join(f"[{sid} {labels.get(sid, {}).get('label', '')}] {labels.get(sid, {}).get('summary', '')}\n" + "\n".join(texts.get(sid, []))
                              for sid in c["sources"]) or "(재료 섹션 없음)"
            iss = ""
            for i, it in enumerate(c["issues"]):
                n_iss += 1
                key = f"{r['product']}_{c['slot']}_{i}"
                iss += (f'<div class="iss {e(it.get("severity", ""))}" data-key="{key}" data-p="{e(r["product"])}" data-slot="{c["slot"]}" data-i="{i}" '
                        f'data-type="{e(it.get("type", ""))}" data-field="{e(it.get("field", ""))}" data-note="{e(it.get("note", ""))}">'
                        f'<b>{e(it.get("type", ""))}</b> <span class="sub">{e(it.get("severity", ""))} · {e(it.get("field", ""))}</span><br>'
                        f'영어: {e(it.get("en", ""))}<br>원본: {e(it.get("ko", ""))}<br>{e(it.get("note", ""))}<br>'
                        f'<label>판단 <select data-k="{key}_v"><option value="">-</option><option>맞음(진짜 문제)</option><option>문제 아님</option></select></label></div>')
            if not c["issues"]:
                iss = '<div class="ok">Claude: 문제 없음</div>'
            cards.append(f'<div class="card"><div><div><b>{c["slot"]}장</b> {head}</div>'
                         + (f'<img src="{e(rel + c["png"])}" loading="lazy">' if c.get("png") else "")
                         + f'<table>{rows}</table></div><div>{iss}<details><summary class="sub">한국어 원본(재료 섹션 OCR)</summary><pre>{e(src)}</pre></details>'
                         f'<textarea data-k="{r["product"]}_{c["slot"]}_m" data-p="{e(r["product"])}" data-slot="{c["slot"]}" placeholder="Claude 가 놓친 문제가 있으면 적기"></textarea></div></div>')
        blocks.append(f'<section class="prod"><h2>{e(S.clean_name(r.get("name", "")) or r["product"])} <span class="sub">{e(r["product"])} · ${r.get("cost_usd", 0)}</span></h2>{"".join(cards)}</section>')
    outp = HERE / "work" / "_eval" / f"내용충실도_{base}.html"
    outp.write_text(f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>내용 충실도 {e(base)}</title><style>{CSS}</style></head><body data-base="{e(base)}">
<header><h1>내용 충실도 검수 — {e(base)} <span class="sub">(Claude 가 찾은 문제 {n_iss}개 · 합계 ${total:.2f})</span></h1>
<div class="sub">사실만 봅니다(번역 표현은 범위 밖). 빨강 = 심각, 주황 = 가벼움. 문제마다 판단을 고르고, 놓친 문제는 그 장 메모에 → CSV.</div>
<button id="csv">판단 CSV 내려받기</button></header><main>{''.join(blocks)}</main><script>{JS}</script></body></html>""", encoding="utf-8")
    print(outp)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", nargs="*", default=[])
    ap.add_argument("--base", default="v6_fill")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--page", action="store_true")
    a = ap.parse_args()
    total = sum(run_product(p, a.base, a.dry_run) or 0 for p in a.product)
    if a.product:
        print(f"합계 {'예상 ' if a.dry_run else ''}${total:.2f}")
    if a.page:
        page(a.base)


if __name__ == "__main__":
    main()
