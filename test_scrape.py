import requests
import json
import re
import time
from bs4 import BeautifulSoup

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

MODULE_PATTERN = r'id="(aplus-(?:premium-|3p-)?module[\w\-]*)"'
MODULE_START_PATTERN = r'id="aplus-(?:premium-|3p-)?module[\w\-]*"'

COUNTRY = "usa"
CHANNEL = "amazon"

# ----------------------------------------------------------------------
# Important Information 관련 설정
# ----------------------------------------------------------------------
IMPORTANT_INFO_SECTION_IDS = [
    "important-information",
    "importantInformation_feature_div",
    "importantInformation",
]

# 표준 항목을 미리 정하지 않는다.
# 페이지에 있는 소제목을 그대로 찾아서 키로 쓰고, 그 아래 텍스트를 값으로 담는다.
# 단수/복수 표기만 통일해 나중에 다루기 쉽게 한다.
KEY_ALIASES = {
    "ingredient": "ingredients",
    "direction": "directions",
    "warning": "warnings",
    "indication": "indications",
    "statement": "statements",
}


def to_high_res(url):
    if not url or '/' not in url:
        return url
    prefix, filename = url.rsplit('/', 1)
    parts = filename.split('.')
    if len(parts) >= 3:
        return f"{prefix}/{parts[0]}.{parts[-1]}"
    return url


def dedupe_preserve_order(lst):
    seen = set()
    result = []
    for x in lst:
        if x not in seen:
            seen.add(x)
            result.append(x)
    return result


def get_product_fields(asin):
    payload = {"target": "amazon_product", "query": asin, "domain": "com", "parse": True}
    r = requests.post(API_URL, json=payload, headers=HEADERS)
    data = r.json()
    if "results" not in data:
        raise Exception(f"get_product_fields 응답 이상함: {json.dumps(data, ensure_ascii=False)[:300]}")
    product = data["results"][0]["content"]["results"]

    breadcrumb = []
    if product.get("category"):
        breadcrumb = [s["name"] for s in product["category"][0].get("ladder", [])]

    # API가 준 항목을 종류 제한 없이 전부 담는다 (소제목 -> 텍스트)
    important_information = {}
    for item in product.get("important_information", []):
        title = item.get("title", "")
        desc = item.get("description")
        key = _normalize_info_key(title)
        if key and desc:
            important_information[key] = desc

    thumbnails = [
        {"order": i + 1, "url_original": to_high_res(u)}
        for i, u in enumerate(product.get("images", []))
    ]

    return {
        "country": COUNTRY,
        "channel": CHANNEL,
        "asin": product.get("asin"),
        "product_name": product.get("product_name"),
        "brand_name": product.get("brand"),
        "breadcrumb": breadcrumb,
        "thumbnail_images": thumbnails,
        "important_information": important_information,
    }


def get_raw_html(asin):
    payload = {"target": "amazon", "url": f"https://www.amazon.com/dp/{asin}", "parse": False}
    r = requests.post(API_URL, json=payload, headers=HEADERS)
    data = r.json()
    if "results" not in data:
        raise Exception(f"get_raw_html 응답 이상함: {json.dumps(data, ensure_ascii=False)[:300]}")
    return data["results"][0]["content"]


def get_best_section(soup, id_name):
    matches = soup.find_all(id=id_name)
    best, best_score = None, -1
    for m in matches:
        score = len(m.get_text(strip=True)) + len(m.find_all("img")) * 50
        if score > best_score:
            best_score, best = score, m
    return best


def extract_table_rows(section):
    rows = []
    for tr in section.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True)
            value = cells[1].get_text(" ", strip=True)
            if label:
                rows.append({"label": label, "value": value})
    return rows


def extract_table_after_heading_text(html, heading_pattern):
    m = re.search(heading_pattern, html, re.IGNORECASE)
    if not m:
        return None
    after_html = html[m.end(): m.end() + 20000]
    table_match = re.search(r'<table.*?</table>', after_html, re.DOTALL)
    if not table_match:
        return None
    table_soup = BeautifulSoup(table_match.group(0), "lxml")
    rows = extract_table_rows(table_soup)
    return rows if rows else None


def extract_top_highlights(soup, html):
    result = {"overview_table": [], "about_this_item": []}

    overview_rows = extract_table_after_heading_text(html, r'Top\s*highlights')
    if overview_rows:
        result["overview_table"] = overview_rows

    bullets = soup.find(id="feature-bullets")
    if bullets:
        for li in bullets.find_all("li"):
            text = li.get_text(" ", strip=True)
            if text:
                result["about_this_item"].append(text)

    if not result["overview_table"] and not result["about_this_item"]:
        return None
    return result


def extract_features_specs(soup):
    """
    'Features & Specs' 섹션은 id="features_and_specs"로 고정되어 있음
    """
    section = get_best_section(soup, "features_and_specs")
    if section is None:
        return None
    rows = extract_table_rows(section)
    return rows if rows else None


def extract_product_description(soup):
    section = get_best_section(soup, "productDescription_feature_div")
    if section is None:
        return "없음"
    text = section.get_text(" ", strip=True)
    imgs = dedupe_preserve_order([to_high_res(img.get("src")) for img in section.find_all("img") if img.get("src")])
    if not text and not imgs:
        return "없음"
    return {"text": text if text else None, "images": imgs}


def extract_disclaimer_fallback(soup):
    candidates = soup.find_all(string=re.compile(r'we work to ensure', re.IGNORECASE))
    for c in candidates:
        parent = c.find_parent(["p", "div", "span"])
        if parent:
            text = parent.get_text(" ", strip=True)
            if len(text) > 50:
                return text
    return None


# ----------------------------------------------------------------------
# Important Information : HTML에서 '있는 항목 전부' 뽑아내기
# ----------------------------------------------------------------------
def _normalize_info_key(title):
    """페이지 소제목을 저장용 키로 변환. (예: 'Safety Information' -> safety_information)"""
    t = title.strip().rstrip(":").lower()
    key = re.sub(r'[^a-z0-9]+', '_', t).strip('_')
    if not key:
        return None
    return KEY_ALIASES.get(key, key)


def _find_important_section(soup):
    for sid in IMPORTANT_INFO_SECTION_IDS:
        found = soup.find(id=sid)
        if found:
            return found
    heading = soup.find(string=re.compile(r'^\s*Important\s+information\s*$', re.IGNORECASE))
    if heading:
        return heading.find_parent(["div", "section"])
    return None


def extract_important_information_from_html(soup):
    """
    parse=True API가 important_information을 비워두는 경우가 있어
    raw HTML의 'Important information' 섹션에서 직접 뽑는다.

    표준 5개 항목만 찾는 것이 아니라, 섹션 안에 있는 소제목을 전부 찾아
    (Warnings, Indications, Statements 등 무엇이든) 해당 텍스트를 가져온다.
    """
    section = _find_important_section(soup)
    if section is None:
        return {}

    # 1) 섹션 안에서 '소제목처럼 생긴' 요소들의 텍스트를 모은다
    heading_texts = set()
    for el in section.find_all(["h1", "h2", "h3", "h4", "h5", "h6",
                                "strong", "b", "span", "div"]):
        classes = el.get("class") or []
        is_bold_span = any("a-text-bold" in c for c in classes)
        if el.name in ("h1", "h2", "h3", "h4", "h5", "h6", "strong", "b") or is_bold_span:
            t = el.get_text(" ", strip=True)
            if t and len(t) <= 50 and not re.match(r'^important\s+information$', t, re.IGNORECASE):
                heading_texts.add(t.strip())

    # 2) 줄 단위로 펼쳐서 '소제목 -> 본문' 순서로 읽는다
    raw_lines = section.get_text("\n").split("\n")
    lines = [l.strip() for l in raw_lines if l.strip()]

    result = {}
    current_key = None
    buffer = []

    def flush():
        if current_key and buffer:
            text = re.sub(r'\s+', ' ', " ".join(buffer)).strip()
            if text and current_key not in result:
                result[current_key] = text

    def is_heading(line):
        if re.match(r'^important\s+information$', line, re.IGNORECASE):
            return False
        if line in heading_texts:
            return True
        return False

    for line in lines:
        if re.match(r'^important\s+information$', line, re.IGNORECASE):
            continue
        if is_heading(line):
            flush()
            current_key = _normalize_info_key(line)
            buffer = []
            continue
        if current_key:
            buffer.append(line)

    flush()
    return result


def collect_aplus_related_ids(html):
    ids = re.findall(r'id="([\w\-]*aplus[\w\-]*)"', html, re.IGNORECASE)
    seen = set()
    unique_ids = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            unique_ids.append(i)
    return unique_ids


def classify_module_type(mod_id):
    lower_id = mod_id.lower()
    if "video" in lower_id:
        return "video"
    if "carousel" in lower_id:
        return "carousel"
    if "faq" in lower_id:
        return "faq"
    if "hotspot" in lower_id:
        return "hotspot"
    if "comparison" in lower_id:
        return "comparison_table"
    return "single"


def extract_from_manufacturer(html):
    start_match = re.search(MODULE_START_PATTERN, html)
    if not start_match:
        return "없음", None

    end_offsets = []
    for pat in STOP_PATTERNS:
        m = re.search(pat, html[start_match.start():])
        if m:
            end_offsets.append(start_match.start() + m.start())
    end_idx = min(end_offsets) if end_offsets else len(html)
    section_html = html[start_match.start():end_idx]

    has_video = bool(re.search(r'<video|\.mp4|videoBlock|video-block', section_html, re.IGNORECASE))

    module_occurrences = [
        {"start_pos": m.start(), "module_id": m.group(1), "images": []}
        for m in re.finditer(MODULE_PATTERN, section_html)
    ]

    img_positions = [(m.start(), m.group(1)) for m in re.finditer(r'<img[^>]+src="([^"]+)"', section_html)]

    for img_pos, img_src in img_positions:
        target = None
        for occ in module_occurrences:
            if occ["start_pos"] <= img_pos:
                target = occ
            else:
                break
        if target is not None:
            target["images"].append(to_high_res(img_src))

    modules = []
    for i, occ in enumerate(module_occurrences):
        imgs = dedupe_preserve_order(occ["images"])
        module_type = classify_module_type(occ["module_id"])
        modules.append({
            "order": i + 1,
            "module_id": occ["module_id"],
            "module_type": module_type,
            "image_count": len(imgs),
            "images": [{"order": j + 1, "url_original": u} for j, u in enumerate(imgs)]
        })

    text_only = re.sub('<[^>]+>', ' ', section_html)
    text_only = re.sub(r'\s+', ' ', text_only).strip()
    caption_text = text_only if 0 < len(text_only) < 2000 else None

    warning = "⚠️ video_detected_in_section" if has_video else None
    return {"text": caption_text, "modules": modules}, warning


def process_product_once(asin):
    fields = get_product_fields(asin)
    html = get_raw_html(asin)
    soup = BeautifulSoup(html, "lxml")

    fields["top_highlights"] = extract_top_highlights(soup, html)
    fields["features_specs"] = extract_features_specs(soup)
    fields["product_description"] = extract_product_description(soup)
    fields["aplus_related_ids"] = collect_aplus_related_ids(html)

    from_mfr, warning = extract_from_manufacturer(html)
    fields["from_manufacturer"] = from_mfr

    # --- Important Information 보강 ---
    # API가 채운 값이 우선. 비어있는 항목만 HTML에서 채우고,
    # 표준 5개 외의 항목(Warnings, Indications 등)이 있으면 그대로 추가한다.
    html_info = extract_important_information_from_html(soup)
    added = []
    for key, value in html_info.items():
        if not value:
            continue
        if not fields["important_information"].get(key):
            fields["important_information"][key] = value
            added.append(key)

    # disclaimer는 섹션 밖에 따로 있는 경우가 많아 기존 폴백도 유지
    if not fields["important_information"].get("disclaimer"):
        fallback = extract_disclaimer_fallback(soup)
        if fallback:
            fields["important_information"]["disclaimer"] = fallback
            added.append("disclaimer")

    if added:
        print(f"     (HTML에서 수집: {', '.join(added)})")

    fields["_warning"] = warning
    return fields


def process_product(asin):
    print(f"\n처리 중: {asin}")
    try:
        result = process_product_once(asin)
    except Exception as e1:
        print(f"  -> 1차 실패: {e1}. 2초 뒤 재시도...")
        time.sleep(2)
        try:
            result = process_product_once(asin)
        except Exception as e2:
            print(f"  -> 재시도도 실패: {e2}")
            return {
                "asin": asin,
                "error": str(e2),
                "country": COUNTRY,
                "channel": CHANNEL,
            }

    from_mfr = result.get("from_manufacturer")
    mod_count = len(from_mfr["modules"]) if isinstance(from_mfr, dict) else 0
    warning = result.get("_warning")
    print(f"  -> from_manufacturer 모듈 {mod_count}개 {'| ' + warning if warning else ''}")
    return result


ASIN_LIST = [
    "B00U2VQZDS", "B07PBXXNCY", "B0B2RM68G2", "B081KL2QYJ", "B08BW46XXK",
    "B0DWFLY18Y", "B01N9SPQHQ", "B0DG4WXBCF", "B01MYEZPC8", "B0DBF65JYY",
    "B01MDTVZTZ", "B074PVTPBW", "B00365DABC", "B0DG1DQ2S7", "B00TTD9BRC",
    "B06WD5J8KY", "B01N34XW93", "B0DK4Y2YP3", "B0DGTMR754", "B00949CTQQ",
    "B00MEDOY2G", "B08KT2Z93D", "B09DDD6YGJ", "B001ET7IQK", "B00SK71SAG",
    "B006IB5T4W", "B0107QPFBU", "B00F1U0YB4", "B07RK4HST7", "B0060OUV5Y",
    "B0FPQ3Z16S", "B07BRDVQ4B", "B081FFRGZB", "B0DPHQRLJC", "B00I69SEK0",
    "B002MSN3QQ", "B01MQXX9US", "B0FPQGLYK9", "B00F97FHAW", "B07YLKXV11",
    "B0FXH5LHN8", "B005IHT94S", "B00L2PB3BW", "B00J5KDCO2", "B084ZP848Y",
    "B0BZ3G9GKL", "B007U54P36", "B077TQR6ZW", "B0FXNHDWM7", "B093W7CDWD",
    "B00XTTFI6K", "B0DKJ3BX2F", "B00ANL8QHA", "B07GRBQXTV", "B00HNSSV0S",
    "B0GHMZXX8Y", "B0GD6R7CFJ", "B091NJQ29P", "B0G38FGSKL", "B0CNCL35CH",
    "B01MUZVE1C", "B0DDC3QGJL", "B014E2D6BY", "B00JJPMXDO", "B0DWMSM6Y9",
    "B0054LHI5A", "B000GG64O4", "B0044B4HSM", "B07SRRLVQ1", "B0B2TKJVDH",
    "B004FHZKOA", "B06XDCPYYL", "B07XXPHQZK", "B0G2T52PRG", "B0DFRL3GHB",
    "B0GYNK6PBB", "B0FSJQ3KJT", "B0F384Y1KR", "B09S6JKB52", "B0G4W2FT6S",
    "B00DM14TYC", "B071RCMQNG", "B09S2K1R7X", "B00GDIL0AM", "B07MX9C5LR",
]


all_results = []
for asin in ASIN_LIST:
    result = process_product(asin)
    all_results.append(result)
    time.sleep(1)

with open("validation_10_products.json", "w", encoding="utf-8") as f:
    json.dump(all_results, f, ensure_ascii=False, indent=2)

print("\n완료! validation_10_products.json 파일을 확인하세요.")

lines = []
for r in all_results:
    asin = r.get("asin")
    lines.append(f"\n{'='*60}")
    lines.append(f"ASIN: {asin}")
    lines.append(f"원본 페이지: https://www.amazon.com/dp/{asin}")
    lines.append(f"country: {r.get('country')} | channel: {r.get('channel')}")
    lines.append(f"{'='*60}")

    if r.get("error"):
        lines.append(f"\n⚠️ 이 상품 처리 실패 - 에러 메시지:\n{r.get('error')}")
        continue

    lines.append(f"\n[상품명]\n{r.get('product_name')}")
    lines.append(f"\n[브랜드]\n{r.get('brand_name')}")

    breadcrumb = r.get('breadcrumb') or []
    lines.append(f"\n[브레드크럼] ({len(breadcrumb)}단계)")
    lines.append(" > ".join(breadcrumb))

    thumbs = r.get('thumbnail_images') or []
    lines.append(f"\n[썸네일 이미지] ({len(thumbs)}개)")
    for t in thumbs:
        lines.append(f"  - {t['url_original']}")

    highlights = r.get('top_highlights')
    lines.append(f"\n[Top Highlights]")
    if not highlights:
        lines.append("  없음")
    else:
        lines.append("  [상단 표 - Brand/Color/Scent 등]")
        for row in highlights.get("overview_table", []):
            lines.append(f"    - {row['label']}: {row['value']}")
        lines.append("  [About this item] (전체 텍스트)")
        for b in highlights.get("about_this_item", []):
            lines.append(f"    - {b}")

    specs = r.get('features_specs')
    lines.append(f"\n[Features & Specs]")
    if not specs:
        lines.append("  없음")
    else:
        for s in specs:
            lines.append(f"  - {s['label']}: {s['value']}")

    info = r.get('important_information') or {}
    lines.append(f"\n[Important Information] (페이지에 있는 항목 전부, 발견 순서대로)")
    if not info:
        lines.append("  없음")
    else:
        lines.append(f"  항목 {len(info)}개: {', '.join(info.keys())}")
        for k, v in info.items():
            lines.append(f"  - {k}: {v if v else '(내용 없음)'}")

    aplus_ids = r.get('aplus_related_ids') or []
    lines.append(f"\n[페이지 내 'aplus' 포함 이름표 전체] ({len(aplus_ids)}개, 등장 순서 그대로)")
    if aplus_ids:
        for i in aplus_ids:
            lines.append(f"  - {i}")
    else:
        lines.append("  없음")

    pd = r.get('product_description')
    lines.append(f"\n[Product Description]")
    if pd == "없음" or pd is None:
        lines.append("  없음")
    else:
        lines.append(f"  텍스트: {pd.get('text') or '없음'}")
        lines.append(f"  이미지: {len(pd.get('images', []))}개")
        for u in pd.get('images', []):
            lines.append(f"    - {u}")

    fm = r.get('from_manufacturer')
    lines.append(f"\n[From the Manufacturer] (모듈 1번부터 순서대로)")
    if fm == "없음" or fm is None:
        lines.append("  없음")
    else:
        lines.append(f"  캡션 텍스트: {fm.get('text') or '없음'}")
        modules = fm.get('modules', [])
        lines.append(f"  모듈 개수: {len(modules)}개")
        for m in modules:
            lines.append(f"\n  ▶ 모듈 {m['order']} | 타입: {m['module_type']} | id: {m['module_id']} | 이미지 {m['image_count']}장")
            for img in m['images']:
                lines.append(f"      [{img['order']}] {img['url_original']}")

with open("review_report.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print("검토용 리포트 저장 완료: review_report.txt")