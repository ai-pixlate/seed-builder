"""2단계 — 식약처 성분 전량 수집.

실행:  python step2_collect.py
- 500건씩(API 상한) pageNo 1부터 totalCount까지
- 응답 항목을 가공 없이 raw/mfds_raw.jsonl 에 한 줄 1건으로 이어 붙임 (덮어쓰지 않음)
- raw/checkpoint.json 에 마지막으로 끝난 페이지를 기록 → 끊겨도 다시 실행하면 이어서 받음
"""
import json
import time
from pathlib import Path

import requests

from step1_probe import build_url, load_key

HERE = Path(__file__).parent
RAW = HERE / "raw" / "mfds_raw.jsonl"
CKPT = HERE / "raw" / "checkpoint.json"
ROWS = 500
SLEEP = 0.4
RETRIES = 3
# 다시 시도해도 소용없는 오류: 인증키 문제, 일일 한도 초과
FATAL_CODES = {"22", "30", "31", "32", "33"}


class FatalError(Exception):
    pass


def fetch(key, page):
    last = None
    for attempt in range(RETRIES + 1):
        try:
            r = requests.get(build_url(key, page, ROWS), timeout=90)
            text = r.text
            try:
                data = json.loads(text)
            except ValueError:
                # data.go.kr 은 인증 오류 등에서 XML 을 돌려준다
                if any(c in text for c in ("SERVICE_KEY", "LIMITED_NUMBER")):
                    raise FatalError(text[:300])
                raise RuntimeError(f"JSON 아님 (HTTP {r.status_code}): {text[:200]}")
            code = data.get("header", {}).get("resultCode")
            if code in FATAL_CODES:
                raise FatalError(json.dumps(data["header"], ensure_ascii=False))
            if code != "00":
                raise RuntimeError(json.dumps(data.get("header"), ensure_ascii=False))
            return data["body"]
        except FatalError:
            raise
        except Exception as e:
            last = e
            if attempt < RETRIES:
                wait = 2 ** (attempt + 1)
                print(f"  page {page} 실패 ({e}) → {wait}초 뒤 재시도 {attempt + 1}/{RETRIES}")
                time.sleep(wait)
    raise RuntimeError(f"page {page} 재시도 {RETRIES}회 모두 실패: {last}")


def count_lines(path):
    if not path.exists():
        return 0
    with path.open("rb") as f:
        return sum(1 for _ in f)


def main():
    key = load_key()
    ckpt = json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else {
        "last_page": 0, "lines": 0, "totalCount": None, "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pages": {}}

    have = count_lines(RAW)
    if have != ckpt["lines"]:
        raise SystemExit(
            f"raw 파일 줄 수({have})가 체크포인트 기록({ckpt['lines']})과 다릅니다. "
            "원본을 덮어쓰지 않기 위해 멈춥니다. 확인이 필요합니다.")

    t0 = time.time()
    page = ckpt["last_page"] + 1
    while True:
        body = fetch(key, page)
        total = int(body["totalCount"])
        if ckpt["totalCount"] is None:
            ckpt["totalCount"] = total
        elif ckpt["totalCount"] != total:
            print(f"  주의: totalCount 가 바뀜 {ckpt['totalCount']} → {total}")
            ckpt.setdefault("totalCount_changes", []).append([page, total])
        last_page = -(-ckpt["totalCount"] // ROWS)
        if page > last_page:
            break
        items = body.get("items") or []
        if isinstance(items, dict):  # 1건일 때 dict 로 오는 API 대비
            items = [items]
        with RAW.open("a", encoding="utf-8", newline="\n") as f:
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
        ckpt["last_page"] = page
        ckpt["lines"] += len(items)
        ckpt["pages"][str(page)] = len(items)
        CKPT.write_text(json.dumps(ckpt, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"page {page}/{last_page}: {len(items)}건 (누적 {ckpt['lines']})")
        if page >= last_page:
            break
        page += 1
        time.sleep(SLEEP)

    ckpt["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    ckpt["elapsed_sec_this_run"] = round(time.time() - t0, 1)
    CKPT.write_text(json.dumps(ckpt, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"완료: 수집 {ckpt['lines']}건 / totalCount {ckpt['totalCount']} / 이번 실행 {ckpt['elapsed_sec_this_run']}초")


if __name__ == "__main__":
    try:
        main()
    except FatalError as e:
        raise SystemExit(f"중단 (재시도해도 안 되는 오류): {e}\n체크포인트까지는 저장돼 있으니 원인 해결 후 다시 실행하면 이어서 받습니다.")
