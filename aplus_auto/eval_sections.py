"""C단계 섹션 분해 평가 — 사람이 검수한 '자른 선' 정답과 AI 섹션 분해를 비교한다.

정답지: work/<상품>/gold/sections.json
    {"base_cuts": [...검수 당시 AI 선...], "marks": {"<그림>@<y>": "ok"|"remove"}, "added": [{"image","y"}],
     "done": true/false, "memo": "", "at": "..."}
    - ok: 맞게 자른 선 · remove: 자르면 안 되는 선(합쳐야 함) · added: AI 가 놓친 선(나눠야 함)

    py -3.12 aplus_auto/eval_sections.py                  전체 점수
    py -3.12 aplus_auto/eval_sections.py --sections <다른 섹션 파일 이름>   개선안 비교(선 위치 ±40px 안이면 같은 선)
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"
AIPOC_IMG = Path(r"C:\Users\인공지능사관학교\Desktop\ai-poc\data\golden_sample")
TOL = 40  # 원본 픽셀. 개선안 선이 정답 선에서 이만큼 안이면 같은 선으로 본다


def img_dir(p):
    d = AIPOC_IMG / f"images_{p}"
    return d if d.exists() else WORK / p / "input"


def sections(p, path=None):
    f = Path(path) if path else WORK / p / "step2" / "section_texts.json"
    out = []
    for s in json.loads(f.read_text(encoding="utf-8"))["sections"]:
        parts = s.get("parts") or [{"image": s["image"], "range": s["range"]}]
        out.append({"sid": s["sid"], "parts": [{"image": x["image"], "range": [int(x["range"][0]), int(x["range"][1])]} for x in parts]})
    return out


def cuts_of(secs):
    """이웃한 두 섹션 사이 = 자른 선 하나. 위치는 앞 섹션이 끝나는 (그림, y)."""
    out = []
    for a, b in zip(secs, secs[1:]):
        end = a["parts"][-1]
        nxt = b["parts"][0]
        out.append({"id": f"{end['image']}@{end['range'][1]}", "image": end["image"], "y": end["range"][1],
                    "between": [a["sid"], b["sid"]], "join": end["image"] != nxt["image"]})
    return out


def page(p):
    d = img_dir(p)
    order = sorted(x.name for x in d.iterdir() if x.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif"))
    imgs = []
    for n in order:
        with Image.open(d / n) as im:
            imgs.append({"name": n, "w": im.width, "h": im.height})
    secs = sections(p)
    used = {}
    for s in secs:
        for x in s["parts"]:
            used.setdefault(x["image"], []).append(x["range"] + [s["sid"]])
    lab = {}
    lf = WORK / p / "step3" / "labels_final.json"
    if lf.exists():
        lab = {s["sid"]: s["label"] for s in json.loads(lf.read_text(encoding="utf-8"))["sections"]}
    starts = [{"sid": s["sid"], "image": s["parts"][0]["image"], "y": s["parts"][0]["range"][0], "label": lab.get(s["sid"], "")}
              for s in secs]
    return {"images": imgs, "used": used, "cuts": cuts_of(secs), "starts": starts}


def gold_path(p):
    return WORK / p / "gold" / "sections.json"


def load_gold(p):
    f = gold_path(p)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def save_gold(p, g):
    f = gold_path(p)
    f.parent.mkdir(parents=True, exist_ok=True)
    g = dict(g, at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    if not g.get("base_cuts"):
        g["base_cuts"] = cuts_of(sections(p))
    f.write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
    return g


def gold_cuts(g):
    keep = [c for c in g.get("base_cuts", []) if g.get("marks", {}).get(c["id"]) == "ok"]
    return [{"image": c["image"], "y": c["y"]} for c in keep] + [{"image": a["image"], "y": int(a["y"])} for a in g.get("added", [])]


def score_product(p, sec_file=None):
    g = load_gold(p)
    marks = g.get("marks", {})
    r = {"product": p, "done": bool(g.get("done")), "base": len(g.get("base_cuts") or cuts_of(sections(p))),
         "reviewed": len(marks), "ok": sum(v == "ok" for v in marks.values()),
         "remove": sum(v == "remove" for v in marks.values()), "added": len(g.get("added", []))}
    if sec_file:  # 개선안 선과 정답 선 맞추기
        gc = gold_cuts(g)
        vc = cuts_of(sections(p, sec_file))
        hit, used = 0, set()
        for c in vc:
            m = next((i for i, x in enumerate(gc) if i not in used and x["image"] == c["image"] and abs(x["y"] - c["y"]) <= TOL), None)
            if m is not None:
                used.add(m)
                hit += 1
        r.update({"var_cuts": len(vc), "gold_cuts": len(gc), "hit": hit})
    return r


def content_score(p, snap=False):
    """검수한 선만 놓고, AI 선과 정답 선 사이가 빈 여백뿐이면(±15px 포함) 같은 선으로 본다.
    snap=True 면 AI 선을 cut_snap 으로 옮긴 뒤 비교(그림 경계 선은 그대로).
    돌려줌: {ai: 검수한 AI 선 수, gold: 정답 선 수, hit: 같은 선, hit_pos: ±40px 안 같은 선}"""
    import cut_snap
    g = load_gold(p)
    if not g:
        return None
    marks = g.get("marks", {})
    gc = gold_cuts(g)
    ai = [c for c in g["base_cuts"] if c["id"] in marks]
    d, cache = img_dir(p), {}

    def r_of(name):
        if name not in cache:
            with Image.open(d / name) as im:
                cache[name] = cut_snap.rows(im)
        return cache[name]
    if snap:
        ai = [c if c["join"] else dict(c, y=cut_snap.snap_y(r_of(c["image"]), c["y"])) for c in ai]
    out = {"ai": len(ai), "gold": len(gc), "hit": 0, "hit_pos": 0}
    for key, same in (("hit_pos", lambda c, x: abs(x["y"] - c["y"]) <= TOL),
                      ("hit", lambda c, x: abs(x["y"] - c["y"]) <= 15 or cut_snap.same_content(r_of(c["image"]), c["y"], x["y"]))):
        used = set()
        for c in ai:
            m = next((i for i, x in enumerate(gc) if i not in used and x["image"] == c["image"] and same(c, x)), None)
            if m is not None:
                used.add(m)
                out[key] += 1
    return out


def pct(a, b):
    return f"{round(a / b * 100)}%" if b else "-"


def score_all(sec_name=None):
    rows = []
    for d in sorted(WORK.iterdir()):
        if gold_path(d.name).exists():
            f = None
            if sec_name:
                f = d / sec_name
                if not f.exists():
                    continue
            rows.append(score_product(d.name, f))
    tot = {k: sum(r.get(k, 0) for r in rows) for k in ("base", "reviewed", "ok", "remove", "added", "var_cuts", "gold_cuts", "hit")}
    return {"products": rows, "total": tot}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sections", default=None, help="상품 폴더 기준 개선안 섹션 파일(예: step1_v2/section_texts.json)")
    ap.add_argument("--content", action="store_true", help="내용 기준 점수와 색 경계 옮기기 효과도 계산")
    a = ap.parse_args()
    r = score_all(a.sections)
    print("[섹션 분해 평가]  정밀도 = 맞게 자른 선 / AI 가 자른 선 · 재현율 = 맞게 자른 선 / 정답 선(맞음 + 놓친 선)")
    for x in r["products"] + [dict(r["total"], product="전체", done=None)]:
        line = (f"  {x['product']}  선 {x['base']}개 중 검수 {x['reviewed']} · 정밀도 {pct(x['ok'], x['ok'] + x['remove'])} "
                f"({x['remove']}개 지워야 함) · 재현율 {pct(x['ok'], x['ok'] + x['added'])} ({x['added']}개 놓침)")
        if a.sections:
            line += f"  | 개선안: 정밀도 {pct(x['hit'], x['var_cuts'])} 재현율 {pct(x['hit'], x['gold_cuts'])}"
        print(line + ("" if x["done"] in (None, True) else "  (검수 중)"))
    if a.content:
        print("\n[내용 기준] 검수한 선만 · 두 선 사이가 빈 여백뿐이면 같은 선 · (위치 ±40px 기준)")
        for snap in (False, True):
            T = {"ai": 0, "gold": 0, "hit": 0, "hit_pos": 0}
            for x in r["products"]:
                c = content_score(x["product"], snap)
                if c:
                    for k in T:
                        T[k] += c[k]
            print(f"  {'색 경계로 옮긴 뒤' if snap else '지금 AI 선      '}  정밀도 {pct(T['hit'], T['ai'])} 재현율 {pct(T['hit'], T['gold'])}"
                  f"   (위치 기준 {pct(T['hit_pos'], T['ai'])} / {pct(T['hit_pos'], T['gold'])})")


if __name__ == "__main__":
    main()
