# -*- coding: utf-8 -*-
"""
to_csv.py
---------
test_scrape.py 가 만든 validation_10_products.json 을 읽어서
엑셀에서 열 수 있는 CSV 4개로 나눠 저장한다.

test_scrape.py 는 전혀 건드리지 않는다. 이 파일만 따로 실행하면 된다.

실행:  python to_csv.py

만들어지는 파일:
  out_products.csv        상품 마스터 (상품당 1행)
  out_text_blocks.csv     텍스트 조각 (조각당 1행)  ← 3종 자산 파이프라인의 입력
  out_images.csv          이미지 (이미지당 1행)     ← OCR 대상 목록
  out_important_info.csv  Important Information + 화장품/OTC 판별 근거
"""

import json
import csv
import re
import os
from datetime import datetime

# ----------------------------------------------------------------------
# 설정
# ----------------------------------------------------------------------
INPUT_JSON = "validation_10_products.json"   # test_scrape.py 결과 파일명
ASIN_LIST_CSV = "asin_list.csv"              # get_asins.py 결과 (수집 카테고리 정보)
ENCODING = "utf-8-sig"   # 엑셀에서 한글이 안 깨지게 하는 인코딩 (중요!)

# 브랜드 국적 룩업 테이블 — 아는 것만 채우고, 나머지는 UNKNOWN으로 나옴
# 나중에 여기에 계속 추가하면 됨
BRAND_ORIGIN = {
    "KAHI": "KR",
    "COSRX": "KR",
    "Beauty of Joseon": "KR",
    "ANUA": "KR",
    "라운드랩": "KR",
    "SKIN1004": "KR",
    "TIRTIR": "KR",
    "MEDICUBE": "KR",
    "NYX PROFESSIONAL MAKEUP": "US",
    "Revlon": "US",
    "REVLON": "US",
    "Kosas": "US",
    "Saie": "US",
    "Glow Recipe": "US",
    "CeraVe": "US",
    "Neutrogena": "US",
    "The Ordinary": "US",
    "Diamond Wipes": "US",
}


# ----------------------------------------------------------------------
# 화장품 / OTC 의약품 구분
# ----------------------------------------------------------------------
# 실제 아마존 리스팅 10건을 확인한 결과, FDA Drug Facts / Active Ingredient 표기가
# 텍스트 필드에 남아있는 상품이 하나도 없었다. 대부분 이미지 안에만 있거나 생략된다.
# 따라서 스크래핑 단계에서는 자동 판별을 하지 않고 '미분류'로 두고,
# 이후 (1) 이미지 OCR 결과로 재시도하거나 (2) 사람이 직접 채운다.
def product_type(product):
    """
    현재는 판별하지 않는다. 항상 '미분류'를 반환한다.
    반환: (product_type, has_drug_facts, has_active_ingredients, 근거)
    """
    return "미분류", "", "", ""


# ----------------------------------------------------------------------
# 유틸
# ----------------------------------------------------------------------
def clean(text):
    """CSV에 넣기 전 줄바꿈/과다공백 정리"""
    if text is None:
        return ""
    t = str(text)
    t = t.replace("\r", " ").replace("\n", " ")
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def get_brand_origin(brand):
    if not brand:
        return "UNKNOWN"
    return BRAND_ORIGIN.get(brand.strip(), "UNKNOWN")


# ----------------------------------------------------------------------
# get_asins.py가 만든 asin_list.csv 를 읽어
# "이 ASIN을 어느 카테고리에서 몇 번째로 가져왔는지" 정보를 붙인다.
# 파일이 없으면 그냥 빈 값으로 두고 진행한다.
# ----------------------------------------------------------------------
def load_asin_categories():
    mapping = {}
    if not os.path.exists(ASIN_LIST_CSV):
        return mapping
    with open(ASIN_LIST_CSV, "r", encoding=ENCODING) as f:
        for row in csv.DictReader(f):
            asin = (row.get("asin") or "").strip()
            if asin:
                mapping[asin] = {
                    "source_category": row.get("category", ""),
                    "rank_in_category": row.get("rank_in_category", ""),
                    "brand_origin_manual": (row.get("brand_origin") or "").strip(),
                }
    return mapping


ASIN_CATEGORY_MAP = {}   # main()에서 채워짐


def get_source_category(asin):
    return ASIN_CATEGORY_MAP.get(asin, {}).get("source_category", "")


def get_rank_in_category(asin):
    return ASIN_CATEGORY_MAP.get(asin, {}).get("rank_in_category", "")


def write_csv(filename, header, rows):
    with open(filename, "w", newline="", encoding=ENCODING) as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  {filename}  ({len(rows)}행)")


# ----------------------------------------------------------------------
# Important Information 항목 이름 -> asset_type 자동 분류
# 항목 종류를 미리 정해두지 않고, 이름에 들어간 단어로 판단한다.
# 처음 보는 항목은 other_info 로 들어가며, 나중에 확인 후 규칙을 추가하면 된다.
# ----------------------------------------------------------------------
def classify_info_asset_type(info_key):
    k = (info_key or "").lower()

    # 성분 계열 -> 번역하지 않고 보존할 목록
    if "ingredient" in k:
        return "preserve_list"

    # 사용법/절차 계열
    if "direction" in k or "instruction" in k or "how_to" in k or "usage" in k:
        return "procedure_corpus"

    # 법적 고지 / 경고 / 안전 계열 -> 빈도분석에서 제외할 상용구
    if any(w in k for w in ["disclaimer", "safety", "warning", "caution",
                            "legal", "statement", "precaution"]):
        return "excluded_boilerplate"

    # 그 외 (indications, uses, country_of_origin, storage 등)
    return "other_info"


# ----------------------------------------------------------------------
# 시트 1: products (상품 마스터)
# ----------------------------------------------------------------------
def build_products(all_results, scraped_at):
    header = [
        "asin", "product_name", "brand_name", "brand_origin",
        "source_category", "rank_in_category",
        "product_type", "type_evidence",
        "breadcrumb_full", "category_leaf",
        "country", "channel", "url",
        "thumbnail_count", "aplus_module_count",
        "has_product_description", "scraped_at",
    ]
    rows = []
    for p in all_results:
        if p.get("error"):
            continue
        breadcrumb = p.get("breadcrumb") or []
        ptype, _, _, evidence = product_type(p)

        fm = p.get("from_manufacturer")
        module_count = len(fm.get("modules", [])) if isinstance(fm, dict) else 0

        pd = p.get("product_description")
        has_pd = "Y" if isinstance(pd, dict) else "N"

        rows.append([
            p.get("asin"),
            clean(p.get("product_name")),
            clean(p.get("brand_name")),
            get_brand_origin(p.get("brand_name")),
            get_source_category(p.get("asin")),
            get_rank_in_category(p.get("asin")),
            ptype,
            evidence,
            " > ".join(breadcrumb),
            breadcrumb[-1] if breadcrumb else "",
            p.get("country", "usa"),
            p.get("channel", "amazon"),
            f"https://www.amazon.com/dp/{p.get('asin')}",
            len(p.get("thumbnail_images") or []),
            module_count,
            has_pd,
            scraped_at,
        ])
    return header, rows


# ----------------------------------------------------------------------
# 시트 2: text_blocks (텍스트 조각) ← 가장 중요
# ----------------------------------------------------------------------
def build_text_blocks(all_results):
    header = [
        "block_id", "asin", "brand_origin", "source_category", "category_leaf",
        "source_field", "asset_type", "extraction_method",
        "ocr_confidence", "text_length", "text",
    ]
    rows = []
    counter = 1

    for p in all_results:
        if p.get("error"):
            continue
        asin = p.get("asin")
        origin = get_brand_origin(p.get("brand_name"))
        breadcrumb = p.get("breadcrumb") or []
        leaf = breadcrumb[-1] if breadcrumb else ""

        def add(source_field, asset_type, text):
            nonlocal counter
            t = clean(text)
            if not t:
                return
            rows.append([
                f"B{counter:05d}", asin, origin, get_source_category(asin), leaf,
                source_field, asset_type, "text_field",
                "", len(t), t,
            ])
            counter += 1

        # --- 자산① 통제어휘: 정형 표들 ---
        highlights = p.get("top_highlights") or {}
        for row in highlights.get("overview_table", []):
            add("top_highlights_table", "controlled_vocab",
                f"{row['label']}: {row['value']}")

        for row in (p.get("features_specs") or []):
            add("features_specs", "controlled_vocab",
                f"{row['label']}: {row['value']}")

        # --- 자산② 효능/클레임: 자유문장 ---
        for bullet in highlights.get("about_this_item", []):
            add("about_this_item", "claim_corpus", bullet)

        pd = p.get("product_description")
        if isinstance(pd, dict) and pd.get("text"):
            add("product_description", "claim_corpus", pd["text"])

        fm = p.get("from_manufacturer")
        if isinstance(fm, dict) and fm.get("text"):
            add("aplus_caption", "claim_corpus", fm["text"])

        # --- Important Information: 항목 종류를 미리 정하지 않고 전부 처리 ---
        # 항목 이름에 따라 asset_type만 자동으로 분류한다.
        info = p.get("important_information") or {}
        for info_key, info_text in info.items():
            add(info_key, classify_info_asset_type(info_key), info_text)

    return header, rows


# ----------------------------------------------------------------------
# 시트 3: images (이미지 목록 = OCR 대상 큐)
# ----------------------------------------------------------------------
def build_images(all_results):
    header = [
        "image_id", "asin", "source_category", "image_type", "image_position",
        "module_id", "module_type", "url",
        "ocr_target", "ocr_done", "ocr_text",
    ]
    rows = []
    counter = 1

    for p in all_results:
        if p.get("error"):
            continue
        asin = p.get("asin")

        # 썸네일: 1번=대표(OCR 제외), 2번부터=부가(OCR 대상)
        for t in (p.get("thumbnail_images") or []):
            order = t.get("order")
            position = "main" if order == 1 else f"secondary_{order}"
            rows.append([
                f"I{counter:05d}", asin, get_source_category(asin), "thumbnail", position,
                "", "", t.get("url_original"),
                "N" if order == 1 else "Y", "N", "",
            ])
            counter += 1

        # Product Description 안 이미지
        pd = p.get("product_description")
        if isinstance(pd, dict):
            for i, url in enumerate(pd.get("images", []), start=1):
                rows.append([
                    f"I{counter:05d}", asin, get_source_category(asin), "description", f"desc_{i}",
                    "", "", url, "Y", "N", "",
                ])
                counter += 1

        # A+ 콘텐츠 이미지
        fm = p.get("from_manufacturer")
        if isinstance(fm, dict):
            for module in fm.get("modules", []):
                for img in module.get("images", []):
                    rows.append([
                        f"I{counter:05d}", asin, get_source_category(asin), "aplus",
                        f"module{module['order']}_img{img.get('order','')}",
                        module.get("module_id", ""), module.get("module_type", ""),
                        img.get("url_original"), "Y", "N", "",
                    ])
                    counter += 1

    return header, rows


# ----------------------------------------------------------------------
# 시트 4: important_info
# 컬럼을 미리 정하지 않고, 수집된 데이터에 실제로 나온 항목을 모두 컬럼으로 만든다.
# ----------------------------------------------------------------------
def build_important_info(all_results):
    # 1) 전체 상품을 훑어 등장한 항목 이름을 모은다 (자주 나오는 순서대로 정렬)
    key_counts = {}
    for p in all_results:
        if p.get("error"):
            continue
        for k, v in (p.get("important_information") or {}).items():
            if v:
                key_counts[k] = key_counts.get(k, 0) + 1

    # 흔한 항목을 앞쪽에 두고, 나머지는 등장 빈도순
    preferred = ["safety_information", "ingredients", "directions",
                 "legal_disclaimer", "disclaimer"]
    ordered_keys = [k for k in preferred if k in key_counts]
    rest = sorted([k for k in key_counts if k not in ordered_keys],
                  key=lambda k: (-key_counts[k], k))
    ordered_keys += rest

    header = ["asin", "product_type", "info_item_count"] + ordered_keys

    rows = []
    for p in all_results:
        if p.get("error"):
            continue
        info = p.get("important_information") or {}
        ptype, _, _, _ = product_type(p)
        row = [p.get("asin"), ptype, len([v for v in info.values() if v])]
        for k in ordered_keys:
            row.append(clean(info.get(k)))
        rows.append(row)

    return header, rows, key_counts


# ----------------------------------------------------------------------
# 메인
# ----------------------------------------------------------------------
def main():
    if not os.path.exists(INPUT_JSON):
        print(f"[에러] {INPUT_JSON} 파일이 없습니다.")
        print("       test_scrape.py 를 먼저 실행했는지, 같은 폴더에 있는지 확인하세요.")
        return

    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        all_results = json.load(f)

    # get_asins.py가 만든 카테고리 정보를 ASIN 기준으로 연결
    global ASIN_CATEGORY_MAP
    ASIN_CATEGORY_MAP = load_asin_categories()
    if ASIN_CATEGORY_MAP:
        print(f"카테고리 정보 연결: {ASIN_LIST_CSV} 에서 {len(ASIN_CATEGORY_MAP)}개 ASIN 읽음")
    else:
        print(f"[안내] {ASIN_LIST_CSV} 가 없어 source_category 는 빈 값으로 둡니다.")

    scraped_at = datetime.now().strftime("%Y-%m-%d")
    ok = [p for p in all_results if not p.get("error")]
    fail = [p for p in all_results if p.get("error")]

    print(f"\n읽음: 총 {len(all_results)}개 (정상 {len(ok)} / 실패 {len(fail)})")
    if fail:
        for p in fail:
            print(f"  실패: {p.get('asin')}")

    print("\nCSV 저장 중...")
    h, r = build_products(all_results, scraped_at)
    write_csv("out_products.csv", h, r)

    h, r = build_text_blocks(all_results)
    write_csv("out_text_blocks.csv", h, r)

    h, r = build_images(all_results)
    write_csv("out_images.csv", h, r)

    h, r, info_key_counts = build_important_info(all_results)
    write_csv("out_important_info.csv", h, r)

    # 요약 통계
    print("\n--- 요약 ---")
    prod_header, prod_rows = build_products(all_results, scraped_at)
    i_type = prod_header.index("product_type")
    i_origin = prod_header.index("brand_origin")
    types = {}
    origins = {}
    for row in prod_rows:
        types[row[i_type]] = types.get(row[i_type], 0) + 1
        origins[row[i_origin]] = origins.get(row[i_origin], 0) + 1
    print(f"product_type: {types}  (스크래핑 단계에서는 판별하지 않음)")
    print(f"브랜드 국적:     {origins}")
    if origins.get("UNKNOWN"):
        print(f"  → UNKNOWN {origins['UNKNOWN']}개는 to_csv.py 의 BRAND_ORIGIN 에 추가하세요")

    # Important Information 에 어떤 항목이 실제로 나왔는지
    if info_key_counts:
        print(f"\nImportant Information 항목 ({len(info_key_counts)}종):")
        for k, c in sorted(info_key_counts.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {k:28} {c}개 상품  [{classify_info_asset_type(k)}]")
        unknown = [k for k in info_key_counts if classify_info_asset_type(k) == "other_info"]
        if unknown:
            print(f"  → other_info 로 분류된 항목: {', '.join(unknown)}")
            print(f"     (분류 규칙을 바꾸려면 to_csv.py 의 classify_info_asset_type 수정)")

    # 수집 카테고리별 상품 수
    if ASIN_CATEGORY_MAP:
        cat_counts = {}
        for p in all_results:
            if p.get("error"):
                continue
            c = get_source_category(p.get("asin")) or "(미상)"
            cat_counts[c] = cat_counts.get(c, 0) + 1
        print("\n수집 카테고리별 상품 수:")
        for c, n in sorted(cat_counts.items(), key=lambda x: -x[1]):
            print(f"  {c:24} {n}개")

    print("\n완료! 엑셀에서 out_*.csv 4개를 열어보세요.")


if __name__ == "__main__":
    main()
