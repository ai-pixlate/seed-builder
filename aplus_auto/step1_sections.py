"""① 섹션 나누기 결과를 눈으로 확인하는 화면을 만든다.

섹션 나누기 자체는 ai-poc 코드를 **고치지 않고 그대로** 실행한 결과를 읽기만 한다.
    ai-poc/poc/section_split/run_color.py   → results/color_snap_ws/  (무료, 배경색 전환 + 여백)
나중에 Gemini 버전(color_snap_vlm2)을 쓰려면 --variant color_snap_vlm2 로 바꾸면 된다(파일 형식 같음).

    py -3.12 aplus_auto/step1_sections.py
    py -3.12 aplus_auto/step1_sections.py --product A000000250199 --variant color_snap_ws

출력: aplus_auto/work/<상품>/step1/
    섹션확인.html     확인 화면 (섹션별 판단·메모 → CSV 내려받기)
    sections.json     전체 섹션 목록(페이지 순서 번호 S01~) — 다음 단계 입력
    annotated/        원본에 자른 선·번호를 그린 그림
    thumbs/           섹션 미리보기 그림
"""
import argparse
import html
import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

Image.MAX_IMAGE_PIXELS = None

HERE = Path(__file__).resolve().parent
AIPOC = Path(r"C:\Users\인공지능사관학교\Desktop\ai-poc")
SPLIT = AIPOC / "poc" / "section_split" / "results"
SRC = AIPOC / "data" / "golden_sample"
FONT = Path(r"C:\Windows\Fonts\malgun.ttf")

ANN_W = 360      # 원본 축소 폭(선 그린 그림)
THUMB_W = 420    # 섹션 미리보기 폭
SOURCE_LABEL = {"시작": "그림 시작", "color": "배경색 전환", "aux_ws": "여백(긴 구간 보조)",
                "aux_vlm": "AI 선택(Gemini)", "edge": "색 경계선",
                "claude": "Claude 선택(여백)", "claude_color": "Claude 선택(배경색 전환)"}
COLORS = [(230, 57, 70), (29, 120, 220), (34, 150, 90), (200, 120, 0), (130, 70, 200)]


def font(size):
    try:
        return ImageFont.truetype(str(FONT), size)
    except OSError:
        return ImageFont.load_default()


def annotate(img, secs, out):
    """원본을 줄이고 섹션마다 왼쪽 색 띠·번호·자른 선을 그린다."""
    s = ANN_W / img.width
    im = img.resize((ANN_W, max(1, round(img.height * s))), Image.BILINEAR).convert("RGB")
    d = ImageDraw.Draw(im, "RGBA")
    f = font(15)
    for k, sec in enumerate(secs):
        y0, y1 = (round(v * s) for v in sec["range"])
        c = COLORS[k % len(COLORS)]
        d.rectangle([0, y0, 7, y1 - 1], fill=c + (255,))
        if y0 > 0:
            d.line([(0, y0), (ANN_W, y0)], fill=(230, 20, 20, 255), width=3)
        label = sec["sid"]
        tw = d.textlength(label, font=f) + 12
        d.rectangle([10, y0 + 4, 10 + tw, y0 + 26], fill=c + (235,))
        d.text((16, y0 + 5), label, font=f, fill=(255, 255, 255))
    im.save(out, quality=88)


def thumb(src, out):
    im = Image.open(src).convert("RGB")
    s = THUMB_W / im.width
    im.resize((THUMB_W, max(1, round(im.height * s))), Image.BILINEAR).save(out, quality=85)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", default="A000000250199")
    ap.add_argument("--variant", default="color_snap_ws")
    ap.add_argument("--name", default="", help="화면 제목에 쓸 상품 이름")
    ap.add_argument("--source", default="", help="섹션 결과 폴더(sections/ crops/ 가 있는 곳). 비우면 ai-poc 결과")
    ap.add_argument("--out-name", default="step1", help="결과 폴더 이름 (work/<상품>/<이름>)")
    a = ap.parse_args()

    vdir = Path(a.source) if a.source else SPLIT / a.variant
    if a.source:
        a.variant = "claude_split (보충 코드, 임시)"
    out = HERE / "work" / a.product / a.out_name
    if out.exists():
        shutil.rmtree(out)
    (out / "annotated").mkdir(parents=True)
    (out / "thumbs").mkdir()

    if (vdir / "sections_all.json").exists():
        return list_mode(a, vdir, out)

    files = sorted(vdir.glob(f"sections/{a.product}_*.json"))
    if not files:
        raise SystemExit(f"섹션 결과 없음: {vdir}/sections/{a.product}_*.json — ai-poc run_color.py 를 먼저 실행")

    pages, all_secs, n = [], [], 0
    for fp in files:
        data = json.loads(fp.read_text(encoding="utf-8"))
        stem = Path(data["image"]).stem
        src = next(SRC.rglob(data["image"]))
        img = Image.open(src)
        secs = []
        for s in data["sections"]:
            n += 1
            sid = f"S{n:02d}"
            crop = vdir / s["crop"]
            thumb(crop, out / "thumbs" / f"{sid}.jpg")
            rec = {"sid": sid, "image": data["image"], "index_in_image": s["index"],
                   "range": s["range"], "height": s["height"], "width": data["size"][0],
                   "cut_source": s["cut_source"], "ai_label": s.get("ai_label", ""), "crop": str(crop),
                   "thumb": f"thumbs/{sid}.jpg"}
            secs.append(rec)
            all_secs.append(rec)
        annotate(img, secs, out / "annotated" / f"{stem}.jpg")
        pages.append({"image": data["image"], "stem": stem, "size": data["size"],
                      "snap_failed": data.get("snap_failed", []), "secs": secs})

    (out / "sections.json").write_text(json.dumps(
        {"product": a.product, "variant": a.variant, "source": str(vdir), "sections": all_secs},
        ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "섹션확인.html").write_text(build_html(a, pages, len(all_secs)), encoding="utf-8")
    print(f"섹션 {len(all_secs)}개 · 원본 {len(pages)}장 → {out / '섹션확인.html'}")


def list_mode(a, vdir, out):
    """그림 경계 합치기(step1d) 결과: 섹션이 여러 그림에 걸칠 수 있다. 섹션은 처음 시작하는 그림 아래에 한 번만 보여 준다."""
    data = json.loads((vdir / "sections_all.json").read_text(encoding="utf-8"))
    secs = []
    for n, s in enumerate(data["sections"], 1):
        sid = f"S{n:02d}"
        thumb(s["crop"], out / "thumbs" / f"{sid}.jpg")
        p0 = s["parts"][0]
        secs.append({"sid": sid, "image": p0["image"], "range": p0["range"], "parts": s["parts"],
                     "height": sum(p["range"][1] - p["range"][0] for p in s["parts"]),
                     "cut_source": s["cut_source"], "ai_label": s.get("ai_label", ""), "crop": s["crop"],
                     "merge_reasons": s.get("merge_reasons", []), "thumb": f"thumbs/{sid}.jpg"})
    images = list(dict.fromkeys(p["image"] for s in secs for p in s["parts"]))
    pages = []
    for name in images:
        src = next(SRC.rglob(name))
        img = Image.open(src)
        here = [dict(s, range=p["range"]) for s in secs for p in s["parts"] if p["image"] == name]
        annotate(img, here, out / "annotated" / f"{Path(name).stem}.jpg")
        pages.append({"image": name, "stem": Path(name).stem, "size": list(img.size), "snap_failed": [],
                      "secs": [s for s in secs if s["image"] == name],
                      "cont": [s["sid"] for s in secs if s["image"] != name and any(p["image"] == name for p in s["parts"])]})
    (out / "sections.json").write_text(json.dumps(
        {"product": a.product, "variant": "그림 경계 합치기 반영", "source": str(vdir), "sections": secs},
        ensure_ascii=False, indent=1), encoding="utf-8")
    a.variant = f"그림 {len(images)}장 · 경계 {data.get('boundaries', 0)}곳 중 {data.get('merged_boundaries', 0)}곳 합침"
    (out / "섹션확인.html").write_text(build_html(a, pages, len(secs)), encoding="utf-8")
    print(f"섹션 {len(secs)}개 · 원본 {len(pages)}장 → {out / '섹션확인.html'}")


# ------------------------------------------------------------------ 화면
CSS = """
:root{--bg:#f4f5f7;--card:#fff;--ink:#1d2127;--sub:#5d6670;--line:#dfe3e8;--acc:#2f6fd6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.55 "Malgun Gothic","Noto Sans KR",system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--card);border-bottom:1px solid var(--line);padding:12px 16px}
.bar{max-width:1300px;margin:0 auto;display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center}
h1{font-size:18px;margin:0}.sum{color:var(--sub)}
button{font:inherit;padding:6px 14px;border-radius:6px;border:1px solid var(--acc);background:var(--acc);color:#fff;cursor:pointer}
main{max-width:1300px;margin:0 auto;padding:12px 16px 80px}
.guide{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin:12px 0}
.guide ul{margin:6px 0;padding-left:20px}
.page{display:grid;grid-template-columns:380px 1fr;gap:20px;background:var(--card);border:1px solid var(--line);
border-radius:10px;padding:16px;margin-top:18px}
@media (max-width:900px){.page{grid-template-columns:1fr}}
.page h2{grid-column:1/-1;margin:0;font-size:16px}.page h2 small{color:var(--sub);font-weight:400}
.ann{position:sticky;top:70px;align-self:start;max-height:calc(100vh - 90px);overflow:auto;border:1px solid var(--line)}
.ann img{display:block;width:360px}
.sec{display:grid;grid-template-columns:200px 1fr;gap:14px;padding:12px 0;border-top:1px solid var(--line)}
.sec:first-child{border-top:0}
.sec .th{max-height:420px;overflow:auto;border:1px solid var(--line);border-radius:6px}
.sec .th img{display:block;width:100%}
.sid{font-weight:700;font-size:16px}.meta{color:var(--sub);font-size:12.5px}
.opts{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.opts label{border:1px solid var(--line);border-radius:16px;padding:3px 10px;cursor:pointer;font-size:13px}
.opts input{margin-right:4px}
.opts label:has(input:checked){background:#e8f0fd;border-color:var(--acc)}
textarea{width:100%;min-height:44px;font:inherit;border:1px solid var(--line);border-radius:6px;padding:6px}
.warn{color:#b45309;font-size:12.5px}
.span{color:#2f6fd6;font-size:12.5px;background:#eef4ff;border-radius:6px;padding:4px 8px;margin:4px 0}
"""

JS = """
const KEY='step1_review_'+document.body.dataset.product;
let st={};try{st=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}
function save(){try{localStorage.setItem(KEY,JSON.stringify(st))}catch(e){};count()}
function count(){const done=Object.values(st).filter(v=>v.d).length;
 document.getElementById('cnt').textContent=done+' / '+document.querySelectorAll('.sec').length+' 판단함'}
document.querySelectorAll('.sec').forEach(el=>{
  const id=el.dataset.sid; const v=st[id]||{};
  el.querySelectorAll('input[type=radio]').forEach(r=>{r.checked=(r.value===v.d);
    r.onchange=()=>{st[id]={...(st[id]||{}),d:r.value};save()}});
  const t=el.querySelector('textarea');t.value=v.m||'';t.oninput=()=>{st[id]={...(st[id]||{}),m:t.value};save()};
});
count();
document.getElementById('csv').onclick=()=>{
  const rows=[['섹션','원본그림','원본_y시작','원본_y끝','판단','메모']];
  document.querySelectorAll('.sec').forEach(el=>{const v=st[el.dataset.sid]||{};
    rows.push([el.dataset.sid,el.dataset.image,el.dataset.y0,el.dataset.y1,v.d||'',v.m||''])});
  const csv='\\ufeff'+rows.map(r=>r.map(x=>'"'+String(x).replace(/"/g,'""')+'"').join(',')).join('\\r\\n');
  const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));
  a.download='섹션확인_결과.csv';a.click()};
"""

DECISIONS = ["좋음", "위 섹션과 합치기", "더 나눠야 함", "기타"]


def build_html(a, pages, total):
    e = html.escape
    blocks = []
    for p in pages:
        cards = []
        for s in p["secs"]:
            opts = "".join(f'<label><input type="radio" name="{s["sid"]}" value="{d}">{d}</label>'
                           for d in DECISIONS)
            cards.append(f"""
<div class="sec" data-sid="{s['sid']}" data-image="{e(s['image'])}" data-y0="{s['range'][0]}" data-y1="{s['range'][1]}">
  <div class="th"><img src="{s['thumb']}" alt="{s['sid']}" loading="lazy"></div>
  <div>
    <div class="sid">{s['sid']}</div>
    {('<div class="span">그림 ' + str(len(s['parts'])) + '장에 걸침: ' + ' → '.join(e(Path(p['image']).stem.rsplit('_', 1)[-1]) + ' (y ' + format(p['range'][0], ',') + '~' + format(p['range'][1], ',') + ')' for p in s['parts']) + ('<br>합친 이유: ' + e(' / '.join(s.get('merge_reasons') or [])) if s.get('merge_reasons') else '') + '</div>') if len(s.get('parts') or []) > 1 else ''}
    <div class="meta">원본 y {s['range'][0]:,} ~ {s['range'][1]:,} · 높이 {s['height']:,}px ·
      자른 이유: {e(SOURCE_LABEL.get(s['cut_source'], s['cut_source']))}
      {('· AI가 붙인 이름: <b>' + e(s['ai_label']) + '</b>') if s.get('ai_label') else ''}</div>
    <div class="opts">{opts}</div>
    <textarea placeholder="메모 (예: S12 아래쪽 성분 설명은 따로 나눠야 함)"></textarea>
  </div>
</div>""")
        warn = (f'<p class="warn">이 그림에서 자르려다 못 자른 곳 {len(p["snap_failed"])}군데 — '
                '사진 배경이라 억지로 자르지 않고 남겨 둠</p>') if p["snap_failed"] else ""
        if p.get("cont"):
            warn += f'<p class="span">이 그림 위쪽은 앞 그림에서 이어진 섹션 {", ".join(p["cont"])} 의 일부</p>'
        blocks.append(f"""
<section class="page">
  <h2>{e(p['stem'])} <small>{p['size'][0]}×{p['size'][1]:,}px · 섹션 {len(p['secs'])}개</small></h2>
  <div class="ann"><img src="annotated/{e(p['stem'])}.jpg" alt="{e(p['stem'])}"></div>
  <div>{warn}{''.join(cards)}</div>
</section>""")
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>① 섹션 확인 {e(a.product)}</title>
<style>{CSS}</style></head><body data-product="{e(a.product)}_{e(a.out_name)}">
<header><div class="bar"><h1>① 섹션 나누기 확인 — {e(a.name) + ' ' if a.name else ''}({e(a.product)})</h1>
<span class="sum">원본 {len(pages)}장 → 섹션 {total}개 · 방식 <b>{e(a.variant)}</b> (ai-poc 코드 그대로)</span>
<span class="sum" id="cnt"></span><button id="csv">판단 결과 CSV 내려받기</button></div></header>
<main>
<div class="guide"><b>보는 법</b>
<ul>
<li>왼쪽: 원본 그림을 줄인 것. <b>빨간 가로선</b>이 자른 자리, 색 띠와 번호(S01…)가 섹션</li>
<li>오른쪽: 섹션마다 미리보기와 정보. 미리보기는 스크롤해서 끝까지 볼 수 있음</li>
<li>섹션마다 <b>좋음 / 위 섹션과 합치기 / 더 나눠야 함 / 기타</b> 중 하나를 고르고, 필요하면 메모</li>
<li>고른 값은 이 브라우저에 자동 저장됨. 끝나면 위쪽 <b>CSV 내려받기</b> → 채팅에 알려 주시면 반영</li>
<li>판단 기준: 한 섹션에 <b>내용 하나</b>(예: 성분 설명, 사용법)만 들어 있으면 좋음. 다음 단계에서 섹션마다 라벨(효능·사용법 등)을 하나씩 붙임</li>
</ul></div>
{''.join(blocks)}
</main><script>{JS}</script></body></html>"""


if __name__ == "__main__":
    main()
