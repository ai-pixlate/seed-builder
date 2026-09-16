# -*- coding: utf-8 -*-
"""
download_images.py
------------------
to_csv.py가 만든 out_images.csv 를 읽어서
OCR 대상 이미지(ocr_target=Y)를 images/ 폴더에 자동으로 내려받는다.

- 파일명은 image_id 를 쓴다 (예: images/I00002.jpg)
  → 나중에 OCR 결과를 CSV의 어느 행에 넣을지 바로 알 수 있다.
- 이미 받은 파일은 건너뛴다 → 중간에 멈춰도 다시 실행하면 이어서 받는다.
- 실패한 것은 download_failed.csv 에 따로 기록한다.

실행:  python download_images.py
"""

import csv
import os
import time
import requests

INPUT_CSV = "out_images.csv"
OUTPUT_DIR = "images"
FAILED_CSV = "download_failed.csv"
ENCODING = "utf-8-sig"

# 아마존이 봇 요청을 막지 않도록 일반 브라우저처럼 보이게 한다
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/122.0 Safari/537.36"),
}

SLEEP_SEC = 0.2        # 요청 사이 간격 (너무 빠르면 차단될 수 있음)
TIMEOUT = 30
MAX_RETRY = 2


def guess_extension(url, content_type):
    """URL이나 응답 헤더로 확장자를 정한다. 기본은 .jpg"""
    lower = url.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if ext in lower:
            return ".jpg" if ext == ".jpeg" else ext
    if content_type:
        if "png" in content_type:
            return ".png"
        if "webp" in content_type:
            return ".webp"
        if "gif" in content_type:
            return ".gif"
    return ".jpg"


def already_downloaded(image_id):
    """확장자가 뭐든 이미 받아둔 파일이 있으면 True"""
    for ext in (".jpg", ".png", ".webp", ".gif"):
        if os.path.exists(os.path.join(OUTPUT_DIR, image_id + ext)):
            return True
    return False


def download_one(url, image_id):
    """성공하면 저장한 파일명, 실패하면 None"""
    for attempt in range(MAX_RETRY + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                raise Exception(f"HTTP {r.status_code}")
            if len(r.content) < 1000:
                raise Exception(f"파일이 너무 작음 ({len(r.content)} bytes)")

            ext = guess_extension(url, r.headers.get("content-type", ""))
            filename = image_id + ext
            path = os.path.join(OUTPUT_DIR, filename)
            with open(path, "wb") as f:
                f.write(r.content)
            return filename

        except Exception as e:
            if attempt < MAX_RETRY:
                time.sleep(1.5)
                continue
            return None


def main():
    if not os.path.exists(INPUT_CSV):
        print(f"[에러] {INPUT_CSV} 가 없습니다. to_csv.py 를 먼저 실행하세요.")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(INPUT_CSV, "r", encoding=ENCODING) as f:
        rows = list(csv.DictReader(f))

    targets = [r for r in rows if (r.get("ocr_target") or "").strip().upper() == "Y"]
    skipped = len(rows) - len(targets)

    print(f"전체 이미지 {len(rows)}장")
    print(f"  OCR 대상    {len(targets)}장")
    print(f"  대표이미지 제외 {skipped}장\n")

    done = 0
    newly = 0
    failed = []
    start = time.time()

    for i, row in enumerate(targets, start=1):
        image_id = row["image_id"]
        url = row["url"]

        if already_downloaded(image_id):
            done += 1
            continue

        filename = download_one(url, image_id)
        if filename:
            done += 1
            newly += 1
        else:
            failed.append(row)

        # 진행 상황 표시
        if i % 25 == 0 or i == len(targets):
            elapsed = time.time() - start
            speed = newly / elapsed if elapsed > 0 else 0
            remain = len(targets) - i
            eta = remain / speed / 60 if speed > 0 else 0
            print(f"  {i}/{len(targets)}  (새로받음 {newly} / 실패 {len(failed)})"
                  f"  남은시간 약 {eta:.0f}분")

        time.sleep(SLEEP_SEC)

    print(f"\n{'='*50}")
    print(f"완료: {done}장 확보 (이번에 새로 받은 것 {newly}장)")
    print(f"저장 위치: {os.path.abspath(OUTPUT_DIR)}")

    if failed:
        print(f"\n실패 {len(failed)}장 → {FAILED_CSV} 에 기록")
        with open(FAILED_CSV, "w", newline="", encoding=ENCODING) as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(failed)
        print("  (이 파일을 확인하고, 다시 실행하면 실패분만 재시도합니다)")
    else:
        print("\n실패 없음")

    # 용량 확인
    total_size = sum(
        os.path.getsize(os.path.join(OUTPUT_DIR, f))
        for f in os.listdir(OUTPUT_DIR)
    )
    print(f"총 용량: {total_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
