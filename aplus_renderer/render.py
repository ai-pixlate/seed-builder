"""JSON 하나 → 970×300 PNG 한 장.

    py -3.12 render.py samples/content/2A.json -o out.png
    py -3.12 render.py samples/content/2A.json -o out.png --scale 2     (1940×600, 검토용)
    py -3.12 render.py samples/content/2A.json -o out.png --html out.html (채워진 HTML도 저장)

결과: out.png 와 out_report.json (글 넘침·위치 경고).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from renderer import ContentError, Renderer  # noqa: E402


def print_report(rep):
    print(f"완료: {rep['output']}  ({rep['size'][0]}×{rep['size'][1]})  템플릿 {rep['template']}")
    for i in rep.get("info", []):
        print("  참고 " + i)
    for w in rep["warnings"]:
        print("  경고 " + w)
    if not rep["warnings"]:
        print("  경고 없음")


def main():
    ap = argparse.ArgumentParser(description="A+ 템플릿 렌더러: JSON → PNG")
    ap.add_argument("input", help="내용 JSON 파일")
    ap.add_argument("-o", "--out", required=True, help="저장할 PNG 경로")
    ap.add_argument("--scale", type=int, default=1, choices=[1, 2, 3], help="1=970×300(기본), 2=1940×600")
    ap.add_argument("--html", help="채워진 HTML 을 저장할 경로(선택)")
    a = ap.parse_args()

    out = Path(a.out)
    try:
        with Renderer(scale=a.scale) as r:
            rep = r.render_file(a.input, out, html_out=a.html)
    except ContentError as e:
        print("입력 내용 오류:\n  " + str(e).replace("\n", "\n  "))
        sys.exit(2)
    rep_path = out.with_name(out.stem + "_report.json")
    rep_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print_report(rep)
    print(f"보고서: {rep_path}")


if __name__ == "__main__":
    main()
