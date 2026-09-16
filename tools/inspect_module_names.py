
# ── 실행 위치와 상관없이 저장소 최상위 폴더를 기준으로 동작하게 만든다 ──────────
#    이 파일은 하위 폴더에 있지만, 읽고 쓰는 CSV 등은 모두 최상위 폴더에 있다.
#    sys.path : 최상위의 env_loader.py 를 import 할 수 있게 한다
#    os.chdir : "out_images.csv" 같은 파일명이 항상 최상위를 가리키게 한다
import os as _os, sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parent.parent
_sys.path.insert(0, str(_ROOT))
_os.chdir(_ROOT)
# ──────────────────────────────────────────────────────────────────────────
import requests
import re

from env_loader import load_token  # 토큰은 .env 에서 읽어온다 (코드에 직접 적지 않는다)

MY_TOKEN = load_token()

API_URL = "https://scraper-api.decodo.com/v2/scrape"
HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
    "authorization": f"Basic {MY_TOKEN}"
}

STOP_PATTERNS = [
    r'id="[^"]*comparison-table[^"]*"',
    r'id="aplusBrandStory_feature_div"',
]

def get_raw_html(asin):
    payload = {"target": "amazon", "url": f"https://www.amazon.com/dp/{asin}", "parse": False}
    r = requests.post(API_URL, json=payload, headers=HEADERS)
    return r.json()["results"][0]["content"]

def get_relevant_section(html):
    """Product Description ~ From the Manufacturer 구간만, 비교테이블/브랜드스토리 이전까지"""
    # 시작점: productDescription 또는 aplus 관련 콘텐츠 중 더 먼저 나오는 지점
    start_candidates = []
    m1 = re.search(r'id="productDescription_feature_div"', html)
    if m1:
        start_candidates.append(m1.start())
    m2 = re.search(r'id="aplus_feature_div"', html)
    if m2:
        start_candidates.append(m2.start())
    m3 = re.search(r'id="aplus-(?:premium-)?module-\d+', html)
    if m3:
        start_candidates.append(m3.start())

    if not start_candidates:
        return None
    start_idx = min(start_candidates)

    # 끝점: 비교테이블 또는 From the Brand, 둘 중 먼저 나오는 지점
    end_candidates = []
    for pat in STOP_PATTERNS:
        m = re.search(pat, html[start_idx:])
        if m:
            end_candidates.append(start_idx + m.start())

    end_idx = min(end_candidates) if end_candidates else len(html)
    return html[start_idx:end_idx]


ASIN_LIST = [
    "B08GSTPT8Y", "B08XDX1LT9", "B0CZ5HLDK9", "B0H8XV8K92", "B0H8HKZPJ3",
    "B09NZJYSPK", "B0BHFBBH25", "B07YT6F4ZK", "B0GMT9NL6S", "B0BB6B581W"
]

lines = []

for asin in ASIN_LIST:
    print(f"확인 중: {asin}")
    html = get_raw_html(asin)
    section = get_relevant_section(html)

    lines.append(f"\n{'='*60}")
    lines.append(f"ASIN: {asin}")
    lines.append(f"{'='*60}")

    if section is None:
        lines.append("  (Product Description / From the Manufacturer 관련 구간을 못 찾음)")
        continue

    all_ids = re.findall(r'id="([\w\-]+)"', section)
    seen = set()
    unique_ids = []
    for i in all_ids:
        if i not in seen:
            seen.add(i)
            unique_ids.append(i)

    if unique_ids:
        for i in unique_ids:
            lines.append(f"  - {i}")
    else:
        lines.append("  (id 없음)")

report = "\n".join(lines)

with open("module_name_comparison.txt", "w", encoding="utf-8") as f:
    f.write(report)

print("\n완료! module_name_comparison.txt 파일을 확인하세요.")