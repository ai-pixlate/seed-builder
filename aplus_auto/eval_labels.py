"""B단계 — 라벨 정확도 평가: 사람 검수(정답지)와 AI 라벨을 비교해 점수를 낸다.

정답지: work/<상품>/gold/labels.json  ({sid: {label, sub, memo, parts, at}})  — 작업대 '② 라벨' 탭에서 검수하면 저장
AI 라벨: work/<상품>/step3/labels.json (AI 원래 답. labels_final.json 은 사람이 고친 것이 섞일 수 있어 쓰지 않음)
         --variant 이름을 주면 work/<상품>/step3/variants/<이름>/labels.json (개선안 비교용)

점수
    주 라벨 일치율   : 정답 라벨 == AI 라벨
    7칸 일치율       : 정답 라벨의 칸 == AI 라벨의 칸 (7칸 밖끼리도 일치로 셈)
    자주 틀린 짝     : (AI → 정답) 횟수

    py -3.12 aplus_auto/eval_labels.py                 (검수한 상품 전체)
    py -3.12 aplus_auto/eval_labels.py --variant v2    (개선안 점수)
"""
import argparse
import collections
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"
GUIDE = HERE.parent / "Claude outputs" / "A+내용종류_분류가이드_v1.4_2026-11-08.md"
SLOTS = {"HERO": 1, "BENEFIT": 2, "INGREDIENT": 3, "PROOF": 4, "CERT": 4, "COMPARE": 4,  # SOCIAL(리뷰·평판)은 7칸 밖 — 2026-11-11 사용자 결정
         "VARIANT": 5, "LINEUP": 5, "HOWTO": 6, "ROUTINE": 6, "BRAND": 7}
SLOT_NAME = {1: "제품 소개", 2: "효능", 3: "성분", 4: "신뢰·증명", 5: "옵션·라인업", 6: "사용법·루틴", 7: "브랜드", None: "7칸 밖"}


def label_defs():
    """분류가이드 표에서 라벨 코드 → (이름, 정의, 헷갈릴 때)."""
    out = {}
    for line in GUIDE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*([A-Z]+)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]*)\|", line)
        if m and m.group(1) not in ("코드",):
            out[m.group(1)] = {"name": m.group(2).strip(), "def": m.group(3).strip(), "tip": m.group(4).strip()}
    return out


def gold_path(p):
    return WORK / p / "gold" / "labels.json"


def load_gold(p):
    gp = gold_path(p)
    return json.loads(gp.read_text(encoding="utf-8")) if gp.exists() else {}


def save_gold(p, sid, rec):
    g = load_gold(p)
    rec = dict(rec, at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    if rec.get("label"):
        g[sid] = rec
    else:
        g.pop(sid, None)  # 검수 취소
    gold_path(p).parent.mkdir(parents=True, exist_ok=True)
    gold_path(p).write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
    return g


def ai_labels(p, variant=None):
    f = (WORK / p / "step3" / "variants" / variant / "labels.json") if variant else (WORK / p / "step3" / "labels.json")
    if not f.exists():
        return {}
    return {s["sid"]: s for s in json.loads(f.read_text(encoding="utf-8"))["sections"]}


def score_product(p, variant=None):
    gold, ai = load_gold(p), ai_labels(p, variant)
    n = agree = slot_agree = 0
    pairs = collections.Counter()
    for sid, g in gold.items():
        if sid not in ai or not g.get("label"):
            continue
        a = ai[sid]["label"]
        n += 1
        if a == g["label"]:
            agree += 1
        else:
            pairs[(a, g["label"])] += 1
        if SLOTS.get(a) == SLOTS.get(g["label"]):
            slot_agree += 1
    return {"product": p, "reviewed": n, "total": len(ai), "agree": agree, "slot_agree": slot_agree,
            "pairs": [{"ai": k[0], "gold": k[1], "n": v} for k, v in pairs.most_common()]}


def score_all(variant=None):
    rows = [score_product(d.name, variant) for d in sorted(WORK.iterdir()) if gold_path(d.name).exists()]
    rows = [r for r in rows if r["reviewed"]]
    tot = {k: sum(r[k] for r in rows) for k in ("reviewed", "agree", "slot_agree")}
    pairs = collections.Counter()
    for r in rows:
        for x in r["pairs"]:
            pairs[(x["ai"], x["gold"])] += x["n"]
    tot["pairs"] = [{"ai": k[0], "gold": k[1], "n": v} for k, v in pairs.most_common()]
    return {"variant": variant or "기본(v1.4)", "products": rows, "total": tot}


def pct(a, b):
    return f"{a / b * 100:.0f}%" if b else "-"


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default=None)
    a = ap.parse_args()
    s = score_all(a.variant)
    print(f"[라벨 평가 · {s['variant']}]")
    for r in s["products"]:
        print(f"  {r['product']}  검수 {r['reviewed']}/{r['total']}  주 라벨 {pct(r['agree'], r['reviewed'])}  "
              f"7칸 {pct(r['slot_agree'], r['reviewed'])}")
    t = s["total"]
    print(f"  전체  검수 {t['reviewed']}  주 라벨 {pct(t['agree'], t['reviewed'])}  7칸 {pct(t['slot_agree'], t['reviewed'])}")
    for x in t["pairs"][:10]:
        print(f"    AI {x['ai']} → 정답 {x['gold']}  {x['n']}회")


if __name__ == "__main__":
    main()
