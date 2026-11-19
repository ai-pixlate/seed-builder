"""D단계 — 7칸 구성 평가: 사람 검수(정답지)와 AI 7칸 구성(템플릿·재료)을 비교해 점수를 낸다.

규칙(2026-11-11 사용자 결정 '엄격'): 칸 재료는 그 칸 라벨의 섹션만 (1=HERO, 2=BENEFIT, 3=INGREDIENT,
4=PROOF·CERT·COMPARE, 5=VARIANT·LINEUP, 6=HOWTO·ROUTINE, 7=BRAND). 다른 라벨 섹션은 재료가 될 수 없다.

정답지: work/<상품>/gold/slots.json   {"1": {verdict, template, sources, memo, at}, ...}
    verdict: ok(템플릿 맞음) · swap(A↔B 바꿔야 함) · empty(빈 칸이어야 함) · fill(빈 칸인데 채워야 함, template 에 A/B)
AI 구성: work/<상품>/step4/plan_ai.json (작업대에서 고치기 전 원본) — 없으면 plan.json
         --variant 이름 → work/<상품>/step4/variants/<이름>/plan.json

점수
    템플릿 일치    : AI 템플릿(빈 칸 포함) == 정답 템플릿
    빈 칸 판단 일치 : (AI 빈 칸 여부) == (정답 빈 칸 여부)
    재료 정밀도    : AI 가 고른 재료 중 정답에 있는 비율
    재료 재현율    : 정답 재료 중 AI 가 고른 비율
    규칙 위반      : AI 재료 중 그 칸 라벨이 아닌 섹션 수

    py -3.12 aplus_auto/eval_slots.py [--variant 이름]
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from eval_labels import SLOTS, WORK

TPL_OTHER = {"A": "B", "B": "A"}


def gold_path(p):
    return WORK / p / "gold" / "slots.json"


def load_gold(p):
    gp = gold_path(p)
    return json.loads(gp.read_text(encoding="utf-8")) if gp.exists() else {}


def save_gold(p, slot, rec):
    g = load_gold(p)
    if rec.get("verdict"):
        g[str(slot)] = dict(rec, at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    else:
        g.pop(str(slot), None)
    gold_path(p).parent.mkdir(parents=True, exist_ok=True)
    gold_path(p).write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
    return g


def ai_plan(p, variant=None):
    d = WORK / p / "step4"
    f = d / "variants" / variant / "plan.json" if variant else (d / "plan_ai.json" if (d / "plan_ai.json").exists() else d / "plan.json")
    if not f.exists():
        return {}
    return {x["slot"]: x for x in json.loads(f.read_text(encoding="utf-8"))["slots"]}


def labels(p):
    f = WORK / p / "step3" / "labels_final.json"
    return {s["sid"]: s for s in json.loads(f.read_text(encoding="utf-8"))["sections"]} if f.exists() else {}


def candidates(p):
    """칸별 재료 후보(엄격 규칙): 그 칸 라벨 섹션."""
    out = {n: [] for n in range(1, 8)}
    for sid, s in labels(p).items():
        n = SLOTS.get(s["label"])
        if n:
            out[n].append(sid)
    return out


def gold_template(n, g, ai_tpl):
    v = g.get("verdict")
    if v == "ok":
        return ai_tpl
    if v == "swap" and ai_tpl:
        return f"{n}{TPL_OTHER[ai_tpl[-1]]}"
    if v == "empty":
        return None
    if v == "fill":
        return g.get("template")
    return ai_tpl


def score_product(p, variant=None):
    gold, ai, lab = load_gold(p), ai_plan(p, variant), labels(p)
    r = {"product": p, "reviewed": 0, "tpl_agree": 0, "empty_agree": 0, "src_ai": 0, "src_gold": 0, "src_hit": 0,
         "rule_break": 0, "rows": []}
    base = ai_plan(p)  # 정답의 '맞음/바꿈'은 검수 당시 원본 AI 기준
    for k, g in gold.items():
        n = int(k)
        x = ai.get(n, {})
        gt = gold_template(n, g, (base.get(n) or {}).get("template"))
        at = x.get("template")
        src = set(x.get("sources") or []) if at else set()
        gs = set(g.get("sources") or []) if gt else set()
        r["reviewed"] += 1
        r["tpl_agree"] += at == gt or (at is not None and at in (g.get("also_ok") or []))  # also_ok: 이것도 괜찮다고 한 템플릿
        r["empty_agree"] += (at is None) == (gt is None)
        r["src_ai"] += len(src)
        r["src_gold"] += len(gs)
        r["src_hit"] += len(src & gs)
        r["rule_break"] += sum(1 for s in src if SLOTS.get((lab.get(s) or {}).get("label")) != n)
        r["rows"].append({"slot": n, "ai": at, "gold": gt, "ai_src": sorted(src), "gold_src": sorted(gs)})
    return r


def score_all(variant=None):
    rows = [score_product(d.name, variant) for d in sorted(WORK.iterdir()) if gold_path(d.name).exists()
            and (not variant or (d / "step4" / "variants" / variant / "plan.json").exists())]
    rows = [r for r in rows if r["reviewed"]]
    keys = ("reviewed", "tpl_agree", "empty_agree", "src_ai", "src_gold", "src_hit", "rule_break")
    return {"variant": variant or "기본", "products": rows, "total": {k: sum(r[k] for r in rows) for k in keys}}


def pct(a, b):
    return f"{a / b * 100:.0f}%" if b else "-"


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default=None)
    a = ap.parse_args()
    s = score_all(a.variant)
    print(f"[7칸 구성 평가 · {s['variant']}]")
    for r in s["products"] + [dict(s["total"], product="전체")]:
        print(f"  {r['product']}  검수 {r['reviewed']}칸  템플릿 {pct(r['tpl_agree'], r['reviewed'])}  "
              f"빈칸판단 {pct(r['empty_agree'], r['reviewed'])}  재료 정밀도 {pct(r['src_hit'], r['src_ai'])}  "
              f"재현율 {pct(r['src_hit'], r['src_gold'])}  규칙위반 {r['rule_break']}")


if __name__ == "__main__":
    main()
