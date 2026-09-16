# -*- coding: utf-8 -*-
"""
get_asins.py
------------
Skin care 세부 카테고리별 아마존 검색 URL을 돌면서
ASIN + 상품명 + 브랜드(추정) 을 뽑아 asin_list.csv 로 저장한다.

이 파일이 만든 asin_list.csv 를 test_scrape.py 가 읽어서 상세 스크래핑을 한다.

실행:  python get_asins.py
"""

import requests
import json
import re
import csv
import time
from bs4 import BeautifulSoup

from env_loader import load_token  # 토큰은 .env 에서 읽어온다 (코드에 직접 적지 않는다)

MY_TOKEN = load_token()

API_URL = "https://scraper-api.decodo.com/v2/scrape"
HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
    "authorization": f"Basic {MY_TOKEN}",
}

OUTPUT_CSV = "asin_list.csv"
ENCODING = "utf-8-sig"          # 엑셀 한글 깨짐 방지

# 한 페이지에 보통 16~24개가 나온다. 목표 개수를 못 채우면 다음 페이지까지 간다.
MAX_PAGES = 3

# ----------------------------------------------------------------------
# 수집 대상: (카테고리명, 목표개수, 검색URL)
# ----------------------------------------------------------------------
CATEGORIES = [
    ("Face", 20,
     "https://www.amazon.com/s?k=beauty+and+personal+care&i=beauty&rh=n%3A3760911%2Cn%3A11060451%2Cn%3A11060711&s=exact-aware-popularity-rank&dc&_encoding=UTF8&qid=1787641254&rnid=11060451&ref=sr_st_exact-aware-popularity-rank"),

    ("Body", 15,
     "https://www.amazon.com/s?k=beauty+and+personal+care&i=beauty&rh=n%3A3760911%2Cn%3A11060451%2Cn%3A11060521&s=exact-aware-popularity-rank&dc&_encoding=UTF8&qid=1787641330&rnid=11060451&ref=sr_nr_n_1"),

    ("Sunscreens & Tanning", 20,
     "https://www.amazon.com/s?k=beauty+and+personal+care&i=beauty&rh=n%3A3760911%2Cn%3A11060451%2Cn%3A11062591&s=exact-aware-popularity-rank&dc&_encoding=UTF8&qid=1787641349&rnid=11060451&ref=sr_nr_n_7"),

    ("Eyes", 10,
     "https://www.amazon.com/s?k=beauty+and+personal+care&i=beauty&rh=n%3A3760911%2Cn%3A11060451%2Cn%3A11061941&s=exact-aware-popularity-rank&dc&_encoding=UTF8&qid=1787641445&rnid=11060451&ref=sr_nr_n_2"),

    ("Lip Care", 10,
     "https://www.amazon.com/s?k=beauty+and+personal+care&i=beauty&rh=n%3A3760911%2Cn%3A11060451%2Cn%3A3761351&s=exact-aware-popularity-rank&dc&_encoding=UTF8&qid=1787641472&rnid=11060451&ref=sr_nr_n_4"),

    ("Sets, Kits", 5,
     "https://www.amazon.com/s?k=beauty+and+personal+care&i=beauty&rh=n%3A3760911%2Cn%3A11060451%2Cn%3A11062581&s=exact-aware-popularity-rank&dc&_encoding=UTF8&qid=1787641472&rnid=11060451&ref=sr_nr_n_6"),

    ("Maternity", 5,
     "https://www.amazon.com/s?k=beauty+and+personal+care&i=beauty&rh=n%3A3760911%2Cn%3A11060451%2Cn%3A11062371&s=exact-aware-popularity-rank&dc&_encoding=UTF8&qid=1787641472&rnid=11060451&ref=sr_nr_n_5"),
]


# ----------------------------------------------------------------------
def add_page_param(url, page):
    """URL에 &page=N 을 붙인다 (1페이지는 그대로)."""
    if page <= 1:
        return url
    if "page=" in url:
        return re.sub(r"page=\d+", f"page={page}", url)
    return url + f"&page={page}"


def fetch_html(url):
    payload = {"target": "amazon", "url": url, "parse": False}
    r = requests.post(API_URL, json=payload, headers=HEADERS, timeout=120)
    data = r.json()
    if "results" not in data:
        raise Exception(f"응답 이상: {json.dumps(data, ensure_ascii=False)[:300]}")
    return data["results"][0]["content"]


def parse_search_results(html):
    """
    검색 결과 페이지에서 상품 카드를 찾아 ASIN / 상품명 / 브랜드 추정값을 뽑는다.
    스폰서(광고) 상품은 제외한다.
    """
    soup = BeautifulSoup(html, "lxml")
    items = []

    # 아마존 검색 결과 카드는 data-asin 속성을 가진다
    for card in soup.select("div[data-asin]"):
        asin = (card.get("data-asin") or "").strip()
        if not asin or len(asin) != 10:
            continue

        card_text = card.get_text(" ", strip=True)

        # 스폰서 광고 제외
        if re.search(r"\bSponsored\b", card_text[:200], re.IGNORECASE):
            continue

        # 상품명: h2 안의 텍스트가 일반적
        title_el = card.select_one("h2")
        title = title_el.get_text(" ", strip=True) if title_el else ""

        # 브랜드: 상품명 첫 단어들로 추정 (정확한 브랜드는 상세 스크래핑에서 확정됨)
        brand_guess = ""
        if title:
            # 대문자로 시작하는 앞쪽 1~2단어를 브랜드 후보로
            words = title.split()
            brand_guess = " ".join(words[:2]) if len(words) >= 2 else title

        items.append({
            "asin": asin,
            "title": title,
            "brand_guess": brand_guess,
        })

    # 중복 제거 (같은 ASIN이 여러 번 잡히는 경우 있음)
    seen = set()
    unique = []
    for it in items:
        if it["asin"] not in seen:
            seen.add(it["asin"])
            unique.append(it)
    return unique


def collect_category(name, target_count, base_url):
    """한 카테고리에서 target_count 개가 모일 때까지 페이지를 넘기며 수집"""
    collected = []
    seen = set()

    for page in range(1, MAX_PAGES + 1):
        if len(collected) >= target_count:
            break

        url = add_page_param(base_url, page)
        print(f"    페이지 {page} 요청 중...", end=" ")
        try:
            html = fetch_html(url)
        except Exception as e:
            print(f"실패: {e}")
            break

        items = parse_search_results(html)
        new_count = 0
        for it in items:
            if it["asin"] in seen:
                continue
            seen.add(it["asin"])
            collected.append(it)
            new_count += 1
            if len(collected) >= target_count:
                break

        print(f"{new_count}개 확보 (누적 {len(collected)}/{target_count})")

        if new_count == 0:
            print("      더 이상 새 상품 없음 → 중단")
            break

        time.sleep(1)

    return collected[:target_count]


# ----------------------------------------------------------------------
def main():
    all_rows = []

    for name, target_count, url in CATEGORIES:
        print(f"\n[{name}] 목표 {target_count}개")
        items = collect_category(name, target_count, url)

        for i, it in enumerate(items, start=1):
            all_rows.append([
                it["asin"],
                name,
                i,                      # 카테고리 내 순위
                it["brand_guess"],
                "",                     # brand_origin — 나중에 직접 채울 칸
                it["title"],
            ])

        print(f"  → {name}: {len(items)}개 수집 완료")

    # CSV 저장
    with open(OUTPUT_CSV, "w", newline="", encoding=ENCODING) as f:
        w = csv.writer(f)
        w.writerow(["asin", "category", "rank_in_category",
                    "brand_guess", "brand_origin", "product_title"])
        w.writerows(all_rows)

    print(f"\n{'='*55}")
    print(f"완료: {OUTPUT_CSV} ({len(all_rows)}개)")
    print(f"{'='*55}")

    # 카테고리별 요약
    from collections import Counter
    counts = Counter(r[1] for r in all_rows)
    for name, target_count, _ in CATEGORIES:
        got = counts.get(name, 0)
        mark = "OK" if got >= target_count else "부족"
        print(f"  {name:22} {got:3}/{target_count:3}  {mark}")

    # ASIN_LIST 형태로도 출력 (test_scrape.py에 붙여넣기 편하게)
    asins = [r[0] for r in all_rows]
    with open("asin_list_python.txt", "w", encoding="utf-8") as f:
        f.write("ASIN_LIST = [\n")
        for i in range(0, len(asins), 5):
            chunk = ", ".join(f'"{a}"' for a in asins[i:i+5])
            f.write(f"    {chunk},\n")
        f.write("]\n")
    print(f"\n  asin_list_python.txt 도 저장했습니다 (test_scrape.py에 붙여넣기용)")


if __name__ == "__main__":
    main()
