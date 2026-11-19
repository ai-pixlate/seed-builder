"""① 확정 — 사람이 섹션 확인 화면에서 고른 판단(CSV)을 반영해 섹션을 확정한다.

    py -3.12 aplus_auto/step1c_apply_review.py --product A000000206826 \
        --sections aplus_auto/work/A000000206826/step1_claude/sections.json \
        --csv "C:/Users/인공지능사관학교/Downloads/섹션확인_결과 (1).csv" --exclude S03

판단 처리
    좋음 / 빈칸        그대로
    위 섹션과 합치기    바로 위 섹션과 합침 (같은 원본 그림 안에서만. 그림이 다르면 합치지 않고 경고)
    더 나눠야 함 / 기타 그대로 두고 목록에 남김(사람이 자를 위치를 알려 줘야 함)
    --exclude          섹션을 뺌(예: 내용 없는 빈 띠)

출력: aplus_auto/work/<상품>/step1_final_src/  sections/<그림>.json, crops/<그림>/<i>.jpg (ai-poc 형식)
      → step1_sections.py --source 로 확인 화면을 만든다
"""
import argparse
import csv
import json
import shutil
from pathlib import Path

from PIL import Image

Image.MAX_IMAGE_PIXELS = None
HERE = Path(__file__).resolve().parent
SRC = Path(r"C:\Users\인공지능사관학교\Desktop\ai-poc") / "data" / "golden_sample"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--sections", required=True)
    ap.add_argument("--csv", default="", help="사람 검토 CSV. 없으면 판단 없이 그대로(업로드 자동 실행)")
    ap.add_argument("--exclude", nargs="*", default=[])
    ap.add_argument("--min-height", type=int, default=120, help="이보다 낮은 섹션은 빈 띠로 보고 뺌")
    ap.add_argument("--no-snap", action="store_true", help="선을 배경색 바뀌는 줄로 옮기지 않음")
    a = ap.parse_args()

    secs = json.loads(Path(a.sections).read_text(encoding="utf-8"))["sections"]
    review = {}
    if a.csv:
        with open(a.csv, encoding="utf-8-sig", newline="") as f:
            review = {r["섹션"].strip(): r for r in csv.DictReader(f)}
    for s in secs:  # 2026-11-10 검토: 43px 빈 띠는 쓸모없음 → 낮은 섹션은 자동으로 뺌
        if s["height"] < a.min_height and s["sid"] not in a.exclude:
            a.exclude.append(s["sid"])
            review.setdefault(s["sid"], {"메모": f"높이 {s['height']}px — 빈 띠로 보고 자동 제외"})

    merged, notes = [], []
    for s in secs:
        sid = s["sid"]
        r = review.get(sid, {})
        d = (r.get("판단") or "").strip()
        memo = (r.get("메모") or "").strip()
        if sid in a.exclude:
            notes.append(f"{sid} 제외 ({memo or '지정'})")
            continue
        if d == "위 섹션과 합치기" and merged and merged[-1]["image"] == s["image"] \
                and merged[-1]["range"][1] == s["range"][0]:
            m = merged[-1]
            m["range"] = [m["range"][0], s["range"][1]]
            m["from"].append(sid)
            m["ai_label"] = " + ".join(x for x in (m["ai_label"], s.get("ai_label", "")) if x)
            notes.append(f"{sid} → {m['from'][0]} 에 합침")
            continue
        if d == "위 섹션과 합치기":
            notes.append(f"[확인 필요] {sid} 합치기 못 함 — 바로 위 섹션과 원본 그림이 다름")
        if d in ("더 나눠야 함", "기타"):
            notes.append(f"[확인 필요] {sid} {d}: {memo}")
        merged.append({"image": s["image"], "range": list(s["range"]), "from": [sid],
                       "ai_label": s.get("ai_label", ""), "cut_source": s["cut_source"]})

    out = HERE / "work" / a.product / "step1_final_src"
    if out.exists():
        shutil.rmtree(out)
    by_img = {}
    for m in merged:
        by_img.setdefault(m["image"], []).append(m)
    for name, items in by_img.items():
        stem = Path(name).stem
        img = Image.open(next(SRC.rglob(name))).convert("RGB")
        if not a.no_snap:  # 이웃 섹션 사이 선을 빈 여백 안의 배경색 바뀌는 줄로 옮김 (11-12, cut_snap.py)
            import cut_snap
            r = cut_snap.rows(img)
            for m1, m2 in zip(items, items[1:]):
                if m1["range"][1] == m2["range"][0]:
                    y = cut_snap.snap_y(r, m1["range"][1])
                    if y != m1["range"][1] and m1["range"][0] < y < m2["range"][1]:
                        notes.append(f"{name} 선 {m1['range'][1]} → {y} (배경색 바뀌는 줄로)")
                        m1["range"][1] = m2["range"][0] = y
        (out / "crops" / stem).mkdir(parents=True, exist_ok=True)
        rows = []
        for i, m in enumerate(items, 1):
            y0, y1 = m["range"]
            img.crop((0, y0, img.width, y1)).save(out / "crops" / stem / f"{i:03d}.jpg", quality=92)
            rows.append({"index": i, "top_offset": y0, "range": [y0, y1], "height": y1 - y0,
                         "cut_source": m["cut_source"], "ai_label": m["ai_label"],
                         "merged_from": m["from"], "crop": f"crops/{stem}/{i:03d}.jpg"})
        (out / "sections").mkdir(parents=True, exist_ok=True)
        (out / "sections" / f"{stem}.json").write_text(json.dumps(
            {"image": name, "variant": "확정(사람 검토 반영)", "size": [img.width, img.height],
             "snap_failed": [], "sections": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "review_notes.json").write_text(json.dumps(
        {"csv": a.csv, "exclude": a.exclude, "notes": notes}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"섹션 {len(secs)}개 → 확정 {len(merged)}개")
    for n in notes:
        print("  " + n)


if __name__ == "__main__":
    main()
