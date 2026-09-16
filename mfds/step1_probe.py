"""1단계 — 식약처 API를 딱 한 번 불러서 응답 원문을 그대로 보여준다.

실행:  python step1_probe.py
       python step1_probe.py limits   (numOfRows 100/500/1000 상한 테스트, 3회 호출)
"""
import os
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).parent
BASE = ("https://apis.data.go.kr/1471000/CsmtcsIngdCpntInfoService01"
        "/getCsmtcsIngdCpntInfoService01")


def load_key():
    for line in (HERE / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("MFDS_SERVICE_KEY_ENCODED="):
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
            if key:
                return key
    sys.exit(".env 의 MFDS_SERVICE_KEY_ENCODED 가 비어 있습니다. 인증키(Encoding)를 붙여넣고 저장하세요.")


def build_url(key, page, rows):
    # serviceKey 는 이미 URL 인코딩된 값이라 문자열로 직접 붙인다 (params 로 넘기면 이중 인코딩됨)
    return f"{BASE}?serviceKey={key}&pageNo={page}&numOfRows={rows}&type=json"


def call(key, page, rows):
    r = requests.get(build_url(key, page, rows), timeout=60)
    return r.status_code, r.headers.get("Content-Type", ""), r.text


def main():
    key = load_key()
    if len(sys.argv) > 1 and sys.argv[1] == "limits":
        import json
        for rows in (100, 500, 1000):
            status, ctype, text = call(key, 1, rows)
            try:
                body = json.loads(text)["body"]
                items = body.get("items")
                n = len(items) if isinstance(items, list) else items
                print(f"numOfRows={rows}: HTTP {status}, 받은 건수={n}, totalCount={body.get('totalCount')}")
            except Exception:
                print(f"numOfRows={rows}: HTTP {status} {ctype}\n{text[:500]}")
            time.sleep(0.5)
        return
    status, ctype, text = call(key, 1, 3)
    print(f"HTTP {status}  Content-Type: {ctype}")
    print(text)


if __name__ == "__main__":
    main()
