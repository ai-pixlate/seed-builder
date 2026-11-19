"""폴더 안 JSON 여러 개를 한 번에 PNG 로.

    py -3.12 batch.py samples/content -o out_folder
    py -3.12 batch.py samples/content -o out_folder --recursive --scale 2 --html
    py -3.12 batch.py samples/sets/lumera -o out_folder --set [--start left]   (한 세트: 좌우 번갈아)

결과: out_folder/<이름>.png 와 out_folder/report.json (전체 경고 모음).
입력 오류가 있는 파일은 건너뛰고 report.json 에 이유를 적는다.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from renderer import ContentError, Renderer  # noqa: E402


def run(inputs, out_dir, scale=1, html=False, quiet=False, rhythm=None):
    """rhythm 에 'right'/'left' 를 주면 inputs 를 한 세트(위→아래 순서)로 보고 좌우 반전을 번갈아 둔다(규칙 1)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    raws = [json.loads(Path(p).read_text(encoding="utf-8")) for p in inputs]
    notes = [None] * len(raws)
    if rhythm:
        from renderer.rhythm import apply_rhythm
        raws, notes = apply_rhythm(raws, start=rhythm)
    with Renderer(scale=scale) as r:
        for p, raw, note in zip(inputs, raws, notes):
            p = Path(p)
            name = p.stem
            try:
                rep = r.render(raw, out_dir / f"{name}.png", base_dir=p.parent,
                               html_out=(out_dir / f"{name}.html") if html else None)
                rep["input"] = str(p)
                rep["name"] = name
                if note:
                    rep["rhythm"] = note
            except ContentError as e:
                rep = {"name": name, "input": str(p), "error": str(e), "warnings": [f"[입력 오류] {e}"]}
            reports.append(rep)
            if not quiet:
                mark = "오류" if "error" in rep else ("경고 %d" % len(rep["warnings"]) if rep["warnings"] else "OK")
                print(f"{name:20s} {mark}{'  · ' + note if note else ''}")
                for w in rep["warnings"]:
                    print("    " + w)
    (out_dir / "report.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    return reports


def main():
    ap = argparse.ArgumentParser(description="A+ 템플릿 렌더러: 폴더 일괄 처리")
    ap.add_argument("folder")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--scale", type=int, default=1, choices=[1, 2, 3])
    ap.add_argument("--recursive", action="store_true", help="하위 폴더 JSON 도 포함")
    ap.add_argument("--html", action="store_true", help="채워진 HTML 도 저장")
    ap.add_argument("--set", action="store_true",
                    help="폴더의 JSON 을 파일 이름 순서로 한 세트로 보고 좌우 반전을 번갈아 둠(페이지 리듬)")
    ap.add_argument("--start", default="right", choices=["right", "left"], help="--set 일 때 첫 장 사진 위치")
    a = ap.parse_args()
    folder = Path(a.folder)
    inputs = sorted(folder.rglob("*.json") if a.recursive else folder.glob("*.json"))
    inputs = [p for p in inputs if not p.name.endswith("report.json")]
    if not inputs:
        print("JSON 파일이 없음:", folder)
        sys.exit(1)
    reps = run(inputs, a.out, a.scale, a.html, rhythm=a.start if a.set else None)
    n_err = sum("error" in r for r in reps)
    n_warn = sum(bool(r["warnings"]) for r in reps if "error" not in r)
    print(f"\n{len(reps)}개 처리 — 오류 {n_err}, 경고 있는 것 {n_warn}. 보고서: {Path(a.out) / 'report.json'}")


if __name__ == "__main__":
    main()
