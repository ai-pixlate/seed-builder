"""샘플 전체를 렌더링하고 미리보기 갤러리(preview/gallery.html)를 만든다.

    py -3.12 make_gallery.py            (기본: 2배 선명도 1940×600 로 찍음)
    py -3.12 make_gallery.py --scale 1

- preview/renders/<이름>.png  : 갤러리용 이미지
- preview/html/<이름>.html    : 채워진 HTML (브라우저로 바로 열어 볼 수 있음)
- preview/report.json         : 전체 보고서
- preview/gallery.html        : 미리보기 화면 (구역 선 보기 켜고 끄기)
"""
import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from batch import run  # noqa: E402

PREVIEW = ROOT / "preview"
VARIANT_LABEL = {
    "items2": "칸 2개", "items4": "칸 4개", "mirror": "좌우 반전", "long": "긴 문구 테스트",
    "theme": "브랜드 색", "before_after": "전후 모드", "swatch12": "스와치 12개", "title2": "제목 2줄",
}
KIND_LABEL = {"image": "이미지", "text": "글 칸", "extra": "추가 요소", "zone": "배경·구역", "note": "참고 구역"}


def variant_label(name):
    if "_" not in name:
        return "기본 (칸 3개)" if name[:2] in ("2A", "2B", "3B", "4B", "5B", "6A", "6B", "7B") else \
               ("기본 (스와치 6개)" if name == "5A" else "기본")
    return VARIANT_LABEL.get(name.split("_", 1)[1], name.split("_", 1)[1])


# 사진 처리·장식·배치 옵션을 한국어로 (카드에 '옵션:' 줄로 보여 줌)
OPT_KO = {
    "photo_shape": ("사진 모양", {"rounded": "둥근 모서리", "circle": "원", "arch": "아치"}),
    "photo_backdrop": ("뒤 배경 도형", {"circle": "원", "blob": "블롭", "arch": "아치", "gradient": "옅은 그라데이션"}),
    "photo_border": ("테두리", {"thin": "얇은 선"}),
    "item_image_shape": ("칸 이미지 모양", {"rounded": "둥근 모서리", "circle": "원"}),
    "headline_underline": ("제목 밑줄", {"bar": "짧은 막대", "line": "가는 선"}),
    "label": ("라벨", {"pill": "알약"}),
    "step_number": ("단계 번호", {"outline": "테두리 원", "square": "사각", "big": "큰 숫자"}),
    "step_connector": ("단계 연결", {"line": "선", "dotted": "점선", "none": "없음"}),
    "margin_deco": ("여백 장식", {"dots": "점", "corner": "모서리 선", "circle": "옅은 원"}),
    "card": ("카드", {True: "있음"}),
}
LAYOUT_KO = {"zigzag": "지그재그", "cards": "카드형 가로", "chips": "칩", "timeline": "타임라인",
             "vcenter": "세로 가운데", "center": "가운데 정렬"}


def options_line(rep):
    parts = []
    if rep.get("layout") and rep["layout"] != "default":
        parts.append(f"배치: {LAYOUT_KO.get(rep['layout'], rep['layout'])}")
    for k, v in (rep.get("style") or {}).items():
        nm, vals = OPT_KO.get(k, (k, {}))
        parts.append(f"{nm}: {vals.get(v, v)}")
    return " · ".join(parts)


def font_summary(texts):
    """items[0].title, items[1].title … 를 items.title 하나로 묶어 '기본→최종' 크기를 보여 준다."""
    groups = {}
    for t in texts:
        if t.get("flow"):
            continue
        key = t["name"]
        if key.startswith("items["):
            key = "items." + key.split("].", 1)[1]
        g = groups.setdefault(key, {"base": t["base"], "finals": []})
        g["finals"].append(t["final"])
    out = []
    for k, g in groups.items():
        lo, hi = min(g["finals"]), max(g["finals"])
        if lo == hi == g["base"]:
            out.append(f"{k} {g['base']}px")
        elif lo == hi:
            out.append(f"{k} {g['base']}→{lo}px")
        else:
            out.append(f"{k} {g['base']}→{lo}~{hi}px")
    return out


def overlay_svg(boxes):
    parts = []
    for b in boxes:
        k = b["kind"]
        parts.append(
            f'<g class="k-{k}"><rect x="{b["x"]}" y="{b["y"]}" width="{b["w"]}" height="{b["h"]}"/>'
            f'<text x="{b["x"] + 3}" y="{b["y"] + 10}">{html.escape(b["name"])}</text></g>')
    return ('<svg class="ov" viewBox="0 0 970 300" preserveAspectRatio="none" aria-hidden="true">'
            + "".join(parts) + "</svg>")


def card(rep, title=None):
    name = rep["name"]
    png = rep.get("png_rel") or f"renders/{name}.png"
    e = html.escape
    if "error" in rep:
        return (f'<article class="card bad"><h3>{e(name)}</h3>'
                f'<p class="err">입력 오류: {e(rep["error"])}</p></article>')
    warn = "".join(f"<li>{e(w)}</li>" for w in rep["warnings"])
    info = "".join(f"<li>{e(i)}</li>" for i in rep.get("info", []))
    notes = "".join(f"<li>{e(n)}</li>" for n in rep.get("notes", []))
    fonts = " · ".join(e(f) for f in font_summary(rep["texts"]))
    status = '<span class="tag red">넘침</span>' if rep["overflow"] else (
        '<span class="tag amber">경고</span>' if rep["warnings"] else '<span class="tag ok">OK</span>')
    return f"""
<article class="card{' warn' if rep['warnings'] else ''}" id="{e(name)}">
  <div class="shot">
    <img src="{e(png)}" alt="{e(name)}" loading="lazy">
    {overlay_svg(rep['spec_boxes'])}
  </div>
  <div class="meta">
    <h3><b>{e(rep['template'])}</b> {e(title or variant_label(name))} {status}</h3>
    <p class="sub">{e(rep['slot'])} · {e(rep['frame'])} · <span class="mod">{e(rep['module'])}</span></p>
    {f'<p class="opts">옵션: {e(options_line(rep))}</p>' if options_line(rep) else ''}
    {f'<p class="opts">페이지 리듬: {e(rep["rhythm"])}</p>' if rep.get("rhythm") else ''}
    <p class="fonts">글자 크기: {fonts}</p>
    {f'<ul class="warns">{warn}</ul>' if warn else ''}
    {f'<ul class="infos">{info}</ul>' if info else ''}
    {f'<details><summary>처리 메모</summary><ul class="notes">{notes}</ul></details>' if notes else ''}
    <p class="files"><a href="{e(png)}">PNG</a> · 입력 <code>{e(Path(rep['input']).name)}</code></p>
  </div>
</article>"""


SLOTS = [("1", "제품 소개"), ("2", "효능"), ("3", "성분"), ("4", "신뢰·증명"),
         ("5", "옵션 · 라인업"), ("6", "사용법"), ("7", "브랜드")]

CSS = """
:root{--bg:#f4f5f7;--card:#fff;--ink:#1d2127;--sub:#5d6670;--line:#dfe3e8;--red:#c62828;--redbg:#fdecec;
--amber:#9a6200;--amberbg:#fff4dc;--ok:#2e7d4f;--okbg:#e6f4ec;
--c-image:#2f6fd6;--c-text:#c47f00;--c-extra:#d0342c;--c-zone:#8a96a3;--c-note:#7b4fc9}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#15181c;--card:#1f2328;--ink:#e8eaed;--sub:#a3abb5;
--line:#343a41;--redbg:#3a1d1d;--amberbg:#3a2e14;--okbg:#17321f;--red:#ff8a80;--amber:#ffcc66;--ok:#7fd49c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.5 "Noto Sans KR","Malgun Gothic",system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);padding:12px 16px}
.bar{max-width:2000px;margin:0 auto;display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center}
h1{font-size:18px;margin:0}.sum{color:var(--sub)}
button{font:inherit;padding:6px 14px;border-radius:6px;border:1px solid var(--line);background:var(--bg);color:var(--ink);cursor:pointer}
button[aria-pressed=true]{background:#2f6fd6;color:#fff;border-color:#2f6fd6}
.legend{display:flex;gap:12px;flex-wrap:wrap;color:var(--sub);font-size:12px}
.legend i{display:inline-block;width:14px;height:10px;border:2px dashed;margin-right:4px;vertical-align:-1px}
main{max-width:2000px;margin:0 auto;padding:8px 16px 60px}
section{margin-top:28px}h2{font-size:17px;margin:0 0 10px;padding-bottom:6px;border-bottom:2px solid var(--line)}
h2 small{color:var(--sub);font-weight:400;margin-left:8px}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
.vtitle{margin:18px 0 8px;font-size:13px;color:var(--sub);font-weight:600}
@media (max-width:1100px){.grid{grid-template-columns:minmax(0,1fr)}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.card.warn{border-color:var(--amber)}
.shot{position:relative;aspect-ratio:970/300;background:repeating-conic-gradient(#e9ecef 0 25%,#fff 0 50%) 0 0/16px 16px}
.shot img{position:absolute;inset:0;width:100%;height:100%;display:block}
.ov{position:absolute;inset:0;width:100%;height:100%;display:none;pointer-events:none}
body.lines .ov{display:block}
.ov rect{fill:none;stroke-width:1.4;stroke-dasharray:5 3;vector-effect:non-scaling-stroke}
.ov text{font:8px sans-serif;paint-order:stroke;stroke:#fff;stroke-width:2.5px}
.ov .k-image rect{stroke:var(--c-image)}.ov .k-image text{fill:var(--c-image)}
.ov .k-text rect{stroke:var(--c-text)}.ov .k-text text{fill:var(--c-text)}
.ov .k-extra rect{stroke:var(--c-extra)}.ov .k-extra text{fill:var(--c-extra)}
.ov .k-zone rect{stroke:var(--c-zone)}.ov .k-zone text{fill:var(--c-zone)}
.ov .k-note rect{stroke:var(--c-note)}.ov .k-note text{fill:var(--c-note)}
.meta{padding:10px 14px 12px}.meta h3{margin:0;font-size:15px;font-weight:500}
.meta p{margin:4px 0}.sub,.fonts,.files{color:var(--sub);font-size:12.5px}.mod{font-weight:600;color:var(--ink)}
.tag{font-size:11px;padding:1px 8px;border-radius:10px;margin-left:6px;vertical-align:1px;font-weight:700}
.tag.red{background:var(--redbg);color:var(--red)}.tag.amber{background:var(--amberbg);color:var(--amber)}
.tag.ok{background:var(--okbg);color:var(--ok)}
ul{margin:6px 0;padding-left:18px;font-size:12.5px}.warns{color:var(--red);background:var(--redbg);border-radius:6px;padding:6px 8px 6px 24px}
.infos{color:var(--amber)}.notes{color:var(--sub)}details summary{cursor:pointer;color:var(--sub);font-size:12.5px}
a{color:#2f6fd6}code{font-size:12px}
.opts{font-size:12.5px;color:#2f6fd6}
.setcol{display:grid;grid-template-columns:minmax(0,980px);gap:10px}
"""

JS = """
const b=document.getElementById('lines');
function set(on){document.body.classList.toggle('lines',on);b.setAttribute('aria-pressed',on);
 try{localStorage.setItem('aplus_lines',on?'1':'0')}catch(e){}}
let init=false;try{init=localStorage.getItem('aplus_lines')==='1'}catch(e){}
set(init);b.onclick=()=>set(!document.body.classList.contains('lines'));
"""


def build_gallery(reports, scale, sets=None):
    by_slot = {s: {"base": [], "var": [], "opt": []} for s, _ in SLOTS}
    for r in reports:
        tid = r.get("template") or r["name"][:2]
        bucket = "opt" if r.get("kind") == "styled" else ("base" if "_" not in r["name"] else "var")
        by_slot.setdefault(tid[0], {"base": [], "var": [], "opt": []})[bucket].append(r)
    secs = []
    for sname, reps in (sets or {}).items():
        secs.append(f'<section><h2>페이지 리듬 세트 · {html.escape(sname)}<small>한쪽 사진 템플릿은 오른쪽→왼쪽 번갈아 · '
                    f'통짜·대칭은 건너뜀 · 직접 지정한 장은 그 값, 다음 장은 그 반대</small></h2>'
                    f'<div class="setcol">{"".join(card(r, title=r["name"]) for r in reps)}</div></section>')
    for s, title in SLOTS:
        d = by_slot[s]
        base = sorted(d["base"], key=lambda r: r["name"])
        var = sorted(d["var"], key=lambda r: r["name"])
        opt = sorted(d["opt"], key=lambda r: r["name"])
        secs.append(f'<section><h2>칸 {s} · {html.escape(title)}<small>A · B</small></h2>'
                    f'<div class="grid">{"".join(card(r) for r in base)}</div>'
                    + (f'<div class="vtitle">변형</div><div class="grid">{"".join(card(r) for r in var)}</div>' if var else "")
                    + (f'<div class="vtitle">사진 처리 · 장식 · 배치 옵션</div><div class="grid">'
                       f'{"".join(card(r, title=options_line(r)) for r in opt)}</div>' if opt else "")
                    + "</section>")
    n = len(reports)
    n_over = sum(1 for r in reports if r.get("overflow"))
    n_warn = sum(1 for r in reports if r.get("warnings"))
    size_ok = all(r.get("size_ok", False) for r in reports if "error" not in r)
    legend = "".join(f'<span><i style="border-color:var(--c-{k})"></i>{v}</span>' for k, v in KIND_LABEL.items())
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>A+ 템플릿 미리보기</title><style>{CSS}</style></head><body>
<header><div class="bar"><h1>A+ 템플릿 14개 미리보기</h1>
<span class="sum">{n}장 · 넘침 {n_over} · 경고 있는 것 {n_warn} · 크기 {'모두 정상' if size_ok else '확인 필요'} ({970 * scale}×{300 * scale}로 찍음) · {stamp}</span>
<button id="lines" aria-pressed="false">구역 선 보기</button><div class="legend">{legend}</div></div></header>
<main>{''.join(secs)}</main><script>{JS}</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=int, default=2, choices=[1, 2])
    a = ap.parse_args()
    content = ROOT / "samples" / "content"
    inputs = sorted(content.glob("*.json")) + sorted((content / "variants").glob("*.json"))
    styled = sorted((content / "styled").glob("*.json"))
    renders = PREVIEW / "renders"
    reps = run(inputs + styled, renders, scale=a.scale, html=True, quiet=True)
    sty = {p.stem for p in styled}
    for r in reps:
        if r["name"] in sty:
            r["kind"] = "styled"
    # 페이지 리듬 세트 (규칙 1): samples/sets/<이름>/ 을 한 세트로
    sets = {}
    for sd in sorted((ROOT / "samples" / "sets").glob("*")) if (ROOT / "samples" / "sets").exists() else []:
        files = sorted(sd.glob("*.json"))
        if not files:
            continue
        srep = run(files, renders / f"set_{sd.name}", scale=a.scale, quiet=True, rhythm="right")
        for r in srep:
            r["png_rel"] = f"renders/set_{sd.name}/{r['name']}.png"
        sets[sd.name] = srep
    # HTML 은 preview/html 로 옮긴다
    hdir = PREVIEW / "html"
    hdir.mkdir(parents=True, exist_ok=True)
    for r in reps:
        src = renders / f"{r['name']}.html"
        if src.exists():
            src.replace(hdir / src.name)
    (renders / "report.json").replace(PREVIEW / "report.json")
    (PREVIEW / "gallery.html").write_text(build_gallery(reps, a.scale, sets), encoding="utf-8")
    n_warn = sum(bool(r.get("warnings")) for r in reps)
    print(f"{len(reps)}장 렌더링, 경고 있는 것 {n_warn}장")
    for r in reps:
        for w in r.get("warnings", []):
            print(f"  {r['name']}: {w}")
    print("갤러리:", PREVIEW / "gallery.html")


if __name__ == "__main__":
    main()
