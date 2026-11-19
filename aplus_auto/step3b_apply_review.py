"""③ 확정 — 라벨 확인 화면에서 사람이 고친 라벨(CSV)을 반영한다.

    py -3.12 aplus_auto/step3b_apply_review.py --product A000000206826 --csv "C:/Users/인공지능사관학교/Downloads/라벨확인_결과.csv"

출력: aplus_auto/work/<상품>/step3/labels_final.json  (④ 칸 채우기 입력)
"""
import argparse
import csv
import json
from pathlib import Path

from step3_label import SLOTS

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--csv", default="", help="없으면 AI 라벨 그대로 확정(업로드 자동 실행)")
    a = ap.parse_args()
    p = HERE / "work" / a.product / "step3"
    data = json.loads((p / "labels.json").read_text(encoding="utf-8"))
    rv = {}
    if a.csv:
        with open(a.csv, encoding="utf-8-sig", newline="") as f:
            rv = {r["섹션"].strip(): r for r in csv.DictReader(f)}
    for s in data["sections"]:
        r = rv.get(s["sid"], {})
        new = (r.get("고친라벨") or "").strip()
        s["ai_label"] = s["label"]
        s["human_memo"] = (r.get("메모") or "").strip()
        if new and new != s["label"]:
            s["label"], s["slot"] = new, SLOTS.get(new)
            print(f"{s['sid']}: {s['ai_label']} → {new} (칸 {s['slot']})")
    data["reviewed_by_human"] = a.csv or None
    (p / "labels_final.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(p / "labels_final.json")


if __name__ == "__main__":
    main()
