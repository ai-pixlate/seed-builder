"""④-b 빈 칸 보충 — 7칸 중 빈 칸을 정해진 우선순위로 채워 항상 7장을 만든다 (2026-11-12, 규칙 원문 TODO_빈칸보충규칙.md).

    py -3.12 aplus_auto/step4b_fill_empty.py --product A000000206826 --base v6 --dry-run
    py -3.12 aplus_auto/step4b_fill_empty.py --product A000000206826 --base v6          (빈 칸 있을 때 Claude 1회)
    py -3.12 aplus_auto/step4b_fill_empty.py --product A000000206826 --base v6 --render-only
    py -3.12 aplus_auto/step4b_fill_empty.py --page --base v6      (8개 상품 모아 보기 화면)

입력: work/<상품>/step4/variants/<base>/plan.json (7칸 결과, 고치지 않음)
출력: work/<상품>/step4/variants/<base>_fill/  plan.json · content/ · images/ · renders/
      work/_eval/빈칸보충_<base>.html

규칙 요약
- 없는 내용은 만들지 않는다. 한국 페이지에 실제로 있는 정보로만(규제 검사는 아직 파이프라인에 없음 → 나중에 연결).
- 채우는 순서: 1) 내용 많은 칸 한 장 더(효능→제품 소개→신뢰·증명→옵션·라인업→성분, 다른 템플릿 A↔B)
  2) 제품 디테일(FEATURE) 3) 추천 대상(TARGET) 4) 제형·사용감(TEXTURE) 5) 제품 사진 한 장(1B, 항상 가능)
- 안내·FAQ·로고·리뷰(SOCIAL)는 보충 재료로 쓰지 않는다. FEATURE·TARGET·TEXTURE 는 보충 칸에서만 재료로 허용(엄격 규칙의 예외).
- 실제 내용 칸을 1→7 순서로 앞에 두고 보충 칸은 뒤(7번 쪽)로. 보충 칸은 목록·화면에만 표시(이미지 안에는 안 그림).
- 위치가 정해진 뒤 좌우 번갈아 배치, 같은 뼈대가 연속이면 표시.
"""
import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path

from PIL import Image

import step4_fill as S

HERE = S.HERE
REPO = S.REPO
EDGE = 1000  # 보충 단계는 섹션 그림을 더 작게 보낸다(비용 절감)
BANNED = {"SOCIAL", "FAQ", "LOGO"}
ONE_SIDED = {"1A", "2A", "2B", "3A", "3B", "4A", "6B", "7A"}
SLOT_NAME = S.SLOT_NAME

RULES = """빈 칸 보충 규칙 (사용자 결정 2026-11-11, 이 순서대로 위에서부터 가능한 것으로 채운다)
원칙: 없는 내용은 만들지 않는다. 한국 페이지에 실제로 있는 정보로만 채운다.
1. 내용이 많은 칸을 한 장 더 — 그 칸의 다른 템플릿(A↔B)을 쓴다. 여러 칸이 가능하면 아래 순서.
   1) 효능: 포인트 4개 이상 (한 장에 2~4개씩 나눔 → 원래 효능 칸과 겹치지 않게 나눈다. 필요하면 update_original 로 원래 칸 항목을 줄인다)
   2) 제품 소개: 제품 사진·모델 컷이 2종류 이상
   3) 신뢰·증명: 실제 근거가 2종류 이상(예: 임상 + 인증). 리뷰 인용은 근거로 쓰지 않음
   4) 옵션·라인업: 스와치 13개 이상, 또는 옵션과 라인업이 둘 다 있을 때
   5) 성분: 핵심 성분 4개 이상
2. 제품 디테일 — 용기·구성품·용량 등 사양 정보(FEATURE 섹션)가 있을 때. 템플릿 예: 3B(항목 나열+제품 사진) 또는 7B(키워드 나열)
3. 추천 대상 — 피부 타입·고민 언급(TARGET 섹션)이 있을 때. 템플릿 예: 2A(체크 문구+제품 사진)
4. 제형·사용감 — 제형 설명이나 텍스처 사진(TEXTURE 섹션)이 있을 때. 템플릿 예: 3A(텍스처 사진 크게 + 설명)
5. 제품 사진 중심 한 장 — 1B(제품·무드 사진 + 제품명·한 줄 설명). 항상 가능한 마지막 안전장치.
- 안내·FAQ·로고·리뷰(SOCIAL)는 보충 내용으로 쓰지 않는다.
- 한 상품에서 같은 보충 유형을 두 번 쓰지 않는다(빈 칸이 2개면 다음 순서 것으로).
- 보충 칸은 이미 다른 칸에 나온 문구·사진을 그대로 되풀이하지 않는다(같은 섹션의 '다른' 내용은 됨).
  특히 큰 사진은 '현재 7칸'에 적힌 다른 칸의 큰 사진(섹션·자리)과 **다른 사진**을 쓴다."""

SYSTEM = f"""너는 한국 화장품 상세페이지로 만든 아마존 A+ 모듈(970×300) 7장 중 비어 있는 칸을 채우는 편집자다.
이미 채워진 칸과 섹션 정보가 주어진다. 빈 칸 수만큼 보충 모듈을 만든다.

{RULES}

아래는 7칸을 만들 때 사람 검수로 정한 기준이다. **보충 칸도 똑같이 지킨다**(엄격 재료 규칙만 보충 칸에서 예외).
특히 신뢰·증명 보충은 근거를 작게 여러 개 나열(4B)하지 말고, 남은 근거 중 **가장 중요한 하나를 4A 로 크게**
(그래프·전후 사진을 통째로) 또는 같은 근거의 전/후 사진 2장을 4B before_after 로 쓴다.
{S.SELECT}

{S.SPECS}

문구 규칙: 미국 아마존 화장품 상세페이지의 자연스러운 영어. 한국 페이지에 있는 사실·수치만. 리뷰·순위 표현 금지.
기획·증정·용량 구성 같은 패키지 문구 금지. 의약품처럼 보이는 표현 금지. 규제 표시(flags)는 달지 않는다.
사진 규칙: 섹션 그림 가장자리 눈금(0~100%)을 보고 box=[왼쪽,위,오른쪽,아래](0~1 비율). 근거 그래프·전후 사진은 통째로(contain).
1B 는 제품이 잘 보이는 사진(모델·손과 제품이 함께 있으면 좋음), headline 은 제품명.

출력은 JSON 하나, 설명을 붙이지 않는다:
{{"checks":[{{"step":"1-1 효능 한 장 더","ok":false,"why":"효능 포인트 3개뿐"}}, ... 위 순서의 각 단계(1-1~1-5, 2, 3, 4, 5)를 모두 판단],
 "fills":[{{"fill_type":"제형·사용감","step":"4","template":"3A","why":"고른 이유(한국어 한 문장)","sources":["S12"],
           "content":{{"headline":"...","body":"...","items":[...],"layout":null,"mode":null}},
           "ko":{{"headline":"한국어 뜻","body":"","items":[]}},
           "images":{{"main":{{"section":"S12","box":[0,0,1,1],"fit":"cover"}},"mark":null,"items":[]}},
           "update_original":null}}]}}
- fills 개수 = 빈 칸 수. 위 checks 에서 ok 인 단계 중 앞 순서부터 고른다.
- update_original(효능 나누기 등 필요할 때만): {{"slot":2,"content":{{...원래 칸 새 내용...}},"images":{{...}}}}"""


def plan_path(w, base):
    """base='main' 이면 작업대가 쓰는 step4/plan.json(업로드 자동 실행 결과), 아니면 개선안 variants/<base>."""
    return w / "step4" / "plan.json" if base == "main" else w / "step4" / "variants" / base / "plan.json"


def out_dir(w, base):
    return w / "step4" / "final" if base == "main" else w / "step4" / "variants" / f"{base}_fill"


def load(p, base):
    w = HERE / "work" / p
    plan = json.loads(plan_path(w, base).read_text(encoding="utf-8"))
    labels = json.loads((w / "step3" / "labels_final.json").read_text(encoding="utf-8"))["sections"]
    crops = {s["sid"]: s for s in json.loads((w / "step2" / "section_texts.json").read_text(encoding="utf-8"))["sections"]}
    absp = lambda c: c if Path(c).is_absolute() else str(REPO / c)  # noqa: E731
    secs = [dict(l, crop=absp(crops[l["sid"]]["crop"])) for l in labels if l["sid"] in crops]
    meta = w / "meta.json"
    name = json.loads(meta.read_text(encoding="utf-8")).get("name", "") if meta.exists() else ""
    return w, plan, secs, name


def ruler_small(path):
    old = S.MAX_EDGE
    S.MAX_EDGE = EDGE
    try:
        return S.with_ruler(path)
    finally:
        S.MAX_EDGE = old


def request(plan, secs, name):
    used = {}
    for x in plan["slots"]:
        for s in x.get("sources") or []:
            used.setdefault(s, x["slot"])
    empties = [x["slot"] for x in plan["slots"] if not x.get("template")]
    lines = []
    for x in plan["slots"]:
        c = x.get("content") or {}
        if x.get("template"):
            items = " / ".join(i.get("title", "") for i in c.get("items") or [])
            lines.append(f"  칸 {x['slot']} {SLOT_NAME[x['slot']]}: {x['template']} · 재료 {x.get('sources')} · "
                         f"제목 {c.get('headline') or ''} · 항목 {items} · 큰 사진 {photo_str((x.get('images') or {}).get('main'))}")
        else:
            lines.append(f"  칸 {x['slot']} {SLOT_NAME[x['slot']]}: 빈 칸")
    content, tok = [{"type": "text", "text": f"상품 이름: {S.clean_name(name)}\n현재 7칸:\n" + "\n".join(lines)
                     + f"\n빈 칸 수: {len(empties)}"}], 0
    for s in secs:
        if s["label"] in BANNED:
            continue
        im = ruler_small(s["crop"])
        tok += im.width * im.height / 750
        u = f"칸 {used[s['sid']]} 에서 사용함" if s["sid"] in used else "아직 안 씀"
        text = "\n".join(s["texts"]) if "texts" in s else ""
        content.append({"type": "text", "text": f"[{s['sid']}] 라벨 {s['label']} {s.get('sub') or ''} · {u}\n요약: {s['summary']}\n"
                                                 f"읽은 글(OCR):\n{text or '(없음)'}"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": S.b64(im)}})
    content.append({"type": "text", "text": f"빈 칸 {len(empties)}개를 보충 규칙대로 채워 JSON 으로 답하라."})
    return content, tok, empties


def with_texts(p, secs):
    st = json.loads((HERE / "work" / p / "step2" / "section_texts.json").read_text(encoding="utf-8"))["sections"]
    tx = {s["sid"]: s.get("texts") or [p["text"] for p in s.get("paragraphs", [])] for s in st}  # section_texts 는 paragraphs 에 글이 있음
    for s in secs:
        s["texts"] = tx.get(s["sid"], [])
    return secs


def photo_str(im):
    return f"{im['section']} {[round(float(v), 2) for v in im['box']]}" if im else "없음"


def same_photo(a, b):
    """같은 섹션에서 자른 자리가 절반 넘게 겹치면 같은 사진으로 본다."""
    if not a or not b or a.get("section") != b.get("section"):
        return False
    ax0, ay0, ax1, ay1 = [float(v) for v in a["box"]]
    bx0, by0, bx1, by1 = [float(v) for v in b["box"]]
    iw, ih = max(0, min(ax1, bx1) - max(ax0, bx0)), max(0, min(ay1, by1) - max(ay0, by0))
    small = min((ax1 - ax0) * (ay1 - ay0), (bx1 - bx0) * (by1 - by0)) or 1
    return iw * ih / small > 0.5


def alternate(slots):
    """좌우 번갈아 — 11-12 부터 aplus_auto/zigzag.py 규칙(1B 글 상자 쪽도 셈). 같은 뼈대 연속이면 표시."""
    import zigzag
    zigzag.alternate(slots)
    return slots


def run_product(p, base, dry=False, render_only=False):
    w, plan, secs, name = load(p, base)
    secs = with_texts(p, secs)
    by_sid = {s["sid"]: s for s in secs}
    out = out_dir(w, base)
    out.mkdir(parents=True, exist_ok=True)
    content, tok, empties = request(plan, secs, name)
    if not empties:
        ans, usage = {"checks": [], "fills": []}, {"in": 0, "out": 0}
        print(f"{p}: 빈 칸 없음")
    else:
        key = S.hashlib.sha256(json.dumps([SYSTEM, S.MODEL, EDGE, plan["slots"]], ensure_ascii=False, default=str)
                               .encode()).hexdigest()[:10]
        cp = out / "cache" / key / "answer.json"
        if dry:
            tin = tok + sum(len("\n".join(s["texts"])) for s in secs) * 1.2 + len(SYSTEM) * 1.2
            print(f"{p}: 빈 칸 {empties} · 입력 약 {tin:,.0f} 토큰 → 예상 ${tin / 1e6 * S.PRICE_IN + 6000 / 1e6 * S.PRICE_OUT:.2f}")
            return 0.0
        if cp.exists():
            c = json.loads(cp.read_text(encoding="utf-8"))
            ans, usage = c["answer"], c["usage"]
        elif render_only:
            olds = sorted((out / "cache").glob("*/answer.json"), key=lambda q: q.stat().st_mtime)
            if not olds:
                raise SystemExit("캐시가 없어 --render-only 불가")
            c = json.loads(olds[-1].read_text(encoding="utf-8"))
            ans, usage = c["answer"], c["usage"]
        else:
            S.load_key()
            import anthropic
            client = anthropic.Anthropic()
            with client.messages.stream(model=S.MODEL, max_tokens=32000, system=SYSTEM, output_config={"effort": "medium"},
                                        messages=[{"role": "user", "content": content}]) as st:
                res = st.get_final_message()
            text = "".join(b.text for b in res.content if b.type == "text")
            ans = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
            usage = {"in": res.usage.input_tokens, "out": res.usage.output_tokens}
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps({"answer": ans, "usage": usage, "raw": text}, ensure_ascii=False, indent=1), encoding="utf-8")
    cost = usage["in"] / 1e6 * S.PRICE_IN + usage["out"] / 1e6 * S.PRICE_OUT

    # ---- 순서 정하기: 실제 내용 칸(1→7) 앞, 보충 칸 뒤
    import copy
    real = [copy.deepcopy(x) for x in plan["slots"] if x.get("template")]
    for x in real:
        x["orig_slot"] = x["slot"]
        x["flags"] = [f for f in x.get("flags") or [] if "1B 제품" not in f]
    fills = []
    for f in (ans.get("fills") or [])[:len(empties)]:
        f = dict(f, fill=True, flags=[])
        bad = [s for s in f.get("sources") or [] if by_sid.get(s, {}).get("label") in BANNED]
        if bad:
            f["sources"] = [s for s in f["sources"] if s not in bad]
            f["flags"].append(f"[규칙] 보충에 못 쓰는 섹션 뺌: {bad}")
        uo = f.get("update_original")
        if uo:
            for x in real:
                if x["orig_slot"] == uo.get("slot"):
                    x["content"] = uo.get("content") or x["content"]
                    if uo.get("images"):
                        x["images"] = uo["images"]
                    x["flags"].append("[보충] 효능 나누기로 원래 칸 내용을 바꿈")
        if f.get("template") == "4B" and (f.get("content") or {}).get("mode") != "before_after":
            f["flags"].append("[보충] 근거를 작게 나열한 4B — 사람 검수 기준(근거 하나 크게)과 다름, 확인 필요")
        fm = (f.get("images") or {}).get("main")
        for x in real:
            if same_photo(fm, (x.get("images") or {}).get("main")):
                f["flags"].append(f"[보충] 큰 사진이 원래 칸 {x['orig_slot']} 사진과 거의 같음 — 확인 필요")
        fills.append(f)
    final = real + fills
    for i, x in enumerate(final, 1):
        x["slot"] = i
        x.pop("mirror", None)
    S.fill_missing_photos(final)
    S.tip_newline(final)
    for x in final:  # 근거 그림 통째로
        if x.get("template") in ("4A", "4B"):
            imgs = x.get("images") or {}
            for im in [imgs.get("main")] + list(imgs.get("items") or []):
                if im:
                    im["fit"] = "contain"

    theme = plan.get("theme")
    for d in ("content", "images", "renders"):
        if (out / d).exists():
            shutil.rmtree(out / d)
    built = [S.build_slot(x, theme, by_sid, out) for x in final]
    cost += S.side_1b(built, out, by_sid)
    for x in built:
        x.pop("_side", None)
    alternate(built)
    import bg_rules
    bg_rules.assign(built)  # 배경 번갈아 뒤집기(11-12 ②) — 보충 칸까지 넣은 최종 순서 기준
    built = [S.build_slot(x, theme, by_sid, out) for x in built]
    S.mark_sources(built, by_sid, out)

    sys.path.insert(0, str(S.RENDERER))
    from batch import run as render_batch  # noqa: E402
    files = sorted((out / "content").glob("*.json"))
    reps = render_batch(files, out / "renders", scale=1, html=False, quiet=True) if files else []
    rep_by = {r["name"]: r for r in reps}
    for x in built:
        if x.get("content_file"):
            r = rep_by.get(Path(x["content_file"]).stem, {})
            x["render"] = {"png": f"renders/{Path(x['content_file']).stem}.png" if "error" not in r else None,
                           "warnings": r.get("warnings", []), "error": r.get("error")}
    res = {"product": p, "name": name, "base": base, "empties": empties, "checks": ans.get("checks", []),
           "usage": usage, "cost_usd": round(cost, 4), "theme": theme, "slots": built}
    (out / "plan.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{p}: 빈 칸 {empties} → " + ", ".join(f"{x.get('fill_type')}({x.get('template')})" for x in fills)
          + f" · ${cost:.4f}" + "".join(f"\n   오류 칸 {x['slot']}: {x['render'].get('error')}" for x in built
                                       if (x.get('render') or {}).get('error')))
    return cost


CSS = """:root{--bg:#f4f5f7;--card:#fff;--ink:#1d2127;--sub:#5d6670;--line:#dfe3e8;--fill:#7c3aed}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 "Malgun Gothic",system-ui,sans-serif}
header{position:sticky;top:0;z-index:3;background:var(--card);border-bottom:1px solid var(--line);padding:10px 16px}
h1{font-size:18px;margin:0}main{max-width:1100px;margin:0 auto;padding:12px 16px 80px}
.prod{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin-top:16px}
.prod h2{margin:0 0 6px;font-size:17px}.sub{color:var(--sub)}
.card{margin-top:12px}.card img{width:100%;max-width:970px;display:block;border:1px solid var(--line)}
.tag{display:inline-block;border-radius:10px;padding:0 8px;font-size:12px;background:#eef2f7;margin-right:6px}
.tag.fill{background:var(--fill);color:#fff}.why{background:#f6f8fb;border-radius:6px;padding:4px 10px;margin-top:4px}
.flag{color:#b45309}.warn{color:#c62828}details{margin-top:6px}table{border-collapse:collapse}
td{padding:2px 8px;border-bottom:1px solid var(--line)}.ok{color:#15803d}.no{color:#9ca3af}
.srcs{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}.srcs img{height:120px;border:1px solid var(--line)}
textarea{width:100%;min-height:40px;font:inherit;border:1px solid var(--line);border-radius:6px;padding:6px;margin-top:6px}
select{font:inherit}button{font:inherit;padding:6px 14px;border-radius:6px;border:1px solid #2f6fd6;background:#2f6fd6;color:#fff;cursor:pointer}"""
JS = """const KEY='fill_review_'+document.body.dataset.base;let st={};try{st=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}
function save(){try{localStorage.setItem(KEY,JSON.stringify(st))}catch(e){}}
document.querySelectorAll('.card.isfill').forEach(el=>{const id=el.dataset.id,v=st[id]||{};const s=el.querySelector('select'),t=el.querySelector('textarea');
 if(v.v)s.value=v.v;if(v.m)t.value=v.m;s.onchange=()=>{st[id]={...(st[id]||{}),v:s.value};save()};t.oninput=()=>{st[id]={...(st[id]||{}),m:t.value};save()}});
document.getElementById('csv').onclick=()=>{const rows=[['상품','위치','보충유형','템플릿','판단','메모']];
 document.querySelectorAll('.card.isfill').forEach(el=>{const v=st[el.dataset.id]||{};rows.push([el.dataset.p,el.dataset.pos,el.dataset.type,el.dataset.tid,v.v||'',v.m||''])});
 const csv='\\ufeff'+rows.map(r=>r.map(x=>'"'+String(x).replace(/"/g,'""')+'"').join(',')).join('\\r\\n');
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download='빈칸보충_검수.csv';a.click()};"""


def page(base, only=None):
    """only=상품 코드 → 그 상품 하나만 step4/final/최종7장.html 로 (업로드 자동 실행 결과 보기)."""
    e = html.escape
    blocks, total = [], 0.0
    for d in sorted((HERE / "work").iterdir()):
        if only and d.name != only:
            continue
        pj = out_dir(d, base) / "plan.json"
        if not pj.exists():
            continue
        r = json.loads(pj.read_text(encoding="utf-8"))
        total += r.get("cost_usd", 0)
        rel = "" if only else f"../{d.name}/{out_dir(d, base).relative_to(d).as_posix()}/"
        checks = "".join(f"<tr><td>{e(c.get('step', ''))}</td><td class='{'ok' if c.get('ok') else 'no'}'>{'가능' if c.get('ok') else '안 됨'}</td>"
                         f"<td>{e(c.get('why', ''))}</td></tr>" for c in r.get("checks", []))
        cards = []
        for x in r["slots"]:
            rr = x.get("render") or {}
            img = f'<img src="{e(rel + rr["png"])}" loading="lazy">' if rr.get("png") else f'<p class="warn">렌더링 실패: {e(str(rr.get("error")))}</p>'
            if x.get("fill"):
                head = f'<span class="tag fill">보충 칸 · {e(x.get("fill_type", ""))}</span>'
            else:
                head = f'<span class="tag">원래 칸 {x["orig_slot"]} {SLOT_NAME[x["orig_slot"]]}</span>'
            fl = "".join(f"<div class='flag'>{e(f)}</div>" for f in x.get("flags") or [] if f.startswith("[보충]") or f.startswith("[배치]") or x.get("fill"))
            wr = "".join(f"<div class='warn'>{e(w)}</div>" for w in rr.get("warnings", []))
            extra = ""
            if x.get("fill"):
                srcs = "".join(f'<figure style="margin:0"><img src="{e(rel + m["file"])}"><br><small>{e(m["sid"])} {e(m["label"])}</small></figure>'
                               for m in x.get("src_marked", []))
                extra = (f'<div class="why"><b>고른 이유:</b> {e(x.get("why", ""))}</div><div class="srcs">{srcs}</div>'
                         f'<label>판단 <select><option value="">-</option><option>좋음</option><option>다른 보충이 나음</option>'
                         f'<option>고칠 곳 있음</option></select></label><textarea placeholder="메모"></textarea>')
            cards.append(f'<div class="card{" isfill" if x.get("fill") else ""}" data-id="{e(r["product"])}_{x["slot"]}" data-p="{e(r["product"])}" '
                         f'data-pos="{x["slot"]}" data-type="{e(x.get("fill_type", ""))}" data-tid="{e(x.get("template") or "")}">'
                         f'<div><b>{x["slot"]}장</b> {head}<span class="sub">{e(x.get("template") or "")}</span></div>{img}{fl}{wr}{extra}</div>')
        blocks.append(f'<section class="prod"><h2>{e(S.clean_name(r.get("name", "")) or r["product"])} <span class="sub">{e(r["product"])} · 빈 칸 {r["empties"] or "없음"} · ${r.get("cost_usd", 0)}</span></h2>'
                      f'{"<details><summary>보충 순서 판단(Claude)</summary><table>" + checks + "</table></details>" if checks else ""}'
                      f'{"".join(cards)}</section>')
    outp = out_dir(HERE / "work" / only, base) / "최종7장.html" if only else HERE / "work" / "_eval" / f"빈칸보충_{base}.html"
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{"최종 7장" if only else "빈 칸 보충 " + e(base)}</title><style>{CSS}</style></head><body data-base="{e(base)}">
<header><h1>빈 칸 보충 확인 — {e(base)} 기준 <span class="sub">(합계 ${total:.2f})</span></h1>
<div class="sub">상품마다 최종 7장을 순서대로. <span class="tag fill">보충 칸</span>은 빈 칸을 채운 장(이미지 안에는 표시 안 함). 보충 칸마다 판단·메모 → CSV.</div>
<button id="csv">판단 CSV 내려받기</button></header><main>{''.join(blocks)}</main><script>{JS}</script></body></html>""", encoding="utf-8")
    print(outp)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", nargs="*", default=[])
    ap.add_argument("--base", default="v6")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--render-only", action="store_true")
    ap.add_argument("--page", action="store_true")
    a = ap.parse_args()
    total = 0.0
    for p in a.product:
        total += run_product(p, a.base, a.dry_run, a.render_only) or 0
    if a.product and not a.dry_run:
        print(f"빈 칸 보충 완료 ${total:.4f}")  # '완료 $' 줄은 자동 실행 진행 화면이 비용으로 셈
    if a.page:
        page(a.base)
    if a.base == "main" and not a.dry_run:
        for p in a.product:
            page(a.base, only=p)


if __name__ == "__main__":
    main()
