
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

def get_raw_html(asin):
    payload = {"target": "amazon", "url": f"https://www.amazon.com/dp/{asin}", "parse": False}
    r = requests.post(API_URL, json=payload, headers=HEADERS)
    return r.json()["results"][0]["content"]

ASIN_LIST = [
    "B08GSTPT8Y", "B08XDX1LT9", "B0CZ5HLDK9", "B0H8XV8K92", "B0H8HKZPJ3",
    "B09NZJYSPK", "B0BHFBBH25", "B07YT6F4ZK", "B0GMT9NL6S", "B0BB6B581W"
]

lines = []

for asin in ASIN_LIST:
    print(f"확인 중: {asin}")
    html = get_raw_html(asin)

    aplus_ids = re.findall(r'id="([\w\-]*aplus[\w\-]*)"', html, re.IGNORECASE)

    seen = set()
    unique_ids = []
    for i in aplus_ids:
        if i not in seen:
            seen.add(i)
            unique_ids.append(i)

    lines.append(f"\n{'='*60}")
    lines.append(f"ASIN: {asin}")
    lines.append(f"{'='*60}")
    if unique_ids:
        for i in unique_ids:
            lines.append(f"  - {i}")
    else:
        lines.append("  (aplus 관련 id 없음)")

report = "\n".join(lines)

with open("aplus_id_list.txt", "w", encoding="utf-8") as f:
    f.write(report)

print("\n완료! aplus_id_list.txt 파일을 확인하세요.")