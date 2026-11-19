"""④ 7칸 채우기 — 라벨 붙은 섹션으로 칸마다 템플릿(A/B)을 고르고 영어 문구·사진 위치를 정한 뒤 렌더링한다.

판단 기준: Claude outputs/A+템플릿_AI선택기준_2026-11-10.png (아래 SELECT 에 옮겨 적음)
템플릿 규격: aplus_renderer (README·spec) — 칸마다 글자 수 한도는 상자 너비로 계산한 대략치
범위 밖(작업 지시): 규제 검사, 빈 칸 보충, AI 사진 생성, 누끼

    py -3.12 aplus_auto/step4_fill.py --product A000000206826 --dry-run
    py -3.12 aplus_auto/step4_fill.py --product A000000206826          (Claude 1회 + 렌더링)
    py -3.12 aplus_auto/step4_fill.py --product A000000206826 --render-only   (캐시로 다시 그리기, 비용 0)

출력: aplus_auto/work/<상품>/step4/
    plan.json        Claude 답(칸별 템플릿·이유·문구·한국어 뜻·사진 위치)
    content/*.json   렌더러 입력 JSON (모델 담당에게 넘길 형식)
    images/          원본에서 자른 사진
    renders/*.png    970×300 결과, report.json
    칸확인.html       확인 화면
"""
import argparse
import base64
import hashlib
import html
import io
import json
import os
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

Image.MAX_IMAGE_PIXELS = None
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
RENDERER = REPO / "aplus_renderer"
MODEL = "claude-opus-5-5"
PRICE_IN, PRICE_OUT = 4.00, 20.00
MAX_EDGE = 1568

SELECT = """칸마다 A·B 중 더 맞는 템플릿을 고른다(A 기본값 없음).
| 칸 | A를 고를 때 | B를 고를 때 |
| 1 제품 소개 | 1A 글·사진 좌우형 — 제품·제품 묶음 사진이 중심 | 1B 통짜 사진형 — 모델·라이프스타일 사진이 중심 |
| 2 효능 | 2A 글·나열+사진형 — 짧은 체크 문구형 효능 | 2B 사진+나열형 — 효능마다 이름 + 설명 |
| 3 성분 | 3A 글·사진 좌우형 — 핵심 성분 1~2개 강조 + 원료 사진 | 3B 글·나열+사진형 — 성분 3개 이상 나열 |
| 4 신뢰·증명 | 4A 글·사진 좌우형 — 핵심 근거 1개를 크게 | 4B 제목+나열형 — 근거 2개 이상 나열 (전후면 2칸) |
| 5 옵션·라인업 | 5A 통짜 나열형 — 색상·향 등 옵션(스와치) | 5B 제목+나열형 — 같은 브랜드 다른 제품 라인업 |
| 6 사용법·루틴 | 6A 제목+나열형 — 단계마다 사진이 있음 | 6B 글·나열+사진형 — 단계가 글로만 있고 모델 사진 있음 |
| 7 브랜드 | 7A 글·사진 좌우형 — 긴 브랜드 이야기 | 7B 제목+나열형 — 브랜드 가치 키워드 3~5개 |
**SOCIAL(신뢰·평판: 리뷰·판매량·#1·수상·언론) 라벨 섹션은 어느 칸의 재료로도 쓰지 않는다**(글·사진 모두).
공통: 바로 앞 칸과 같은 뼈대는 피한다(예: 1A 다음 2A 는 둘 다 글+오른쪽 사진 → 가능하면 다른 쪽). 없는 내용은 만들지 않는다.

=== 2026-11-11 사람 검수(8개 상품·52칸)에서 나온 기준 — 꼭 지킨다 ===
[재료 — 엄격 규칙] 칸의 **글 재료(sources)**는 **아래 '칸별 후보'에 적힌 그 칸 라벨 섹션만** 쓴다. 다른 섹션은 쓰지 않는다(코드가 지운다).
  한 섹션은 한 칸에만 쓴다. 재료 후보가 없는 칸은 비운다(template null). **예외: 1 제품 소개.**
[사진은 예외] 엄격 규칙은 **글에만** 적용한다. 큰 사진(images.main)은 그 칸 섹션에 알맞은 사진이 없으면
  **다른 섹션의 제품·모델 사진을 가져와도 된다**(리뷰·안내·로고 섹션 제외). 사진이 없다고 칸을 비우거나 main 을 null 로 두지 않는다.
  필수 사진(1A·1B·2A·2B·3A·3B·4A·6B·7A 의 image)은 반드시 채운다.
[2 효능] 원문 효능이 **2~4개 포인트로 정리돼 있으면** 2A(체크 문구)·2B(이름+설명).
  포인트로 정리돼 있지 않으면 **번호·불릿을 억지로 만들지 말고**, 효능 중 **가장 중요한 하나**를
  **2A 대표 하나형**(content.layout="single": headline + body 짧은 문단, items 없음) + 제품 사진으로 깔끔하게 쓴다.
  효능 섹션이 있는데 효능 칸을 비우지 않는다.
[패키지 정보 빼기] 상품 이름·문구에 들어 있는 **기획·증정·구성·용량 표기**(예: "150ml+토너25ml+폼3g*3", "기획", "증정", "1+1", "더블 기획")는
  **어느 칸에도 쓰지 않는다.** 제품명은 브랜드 + 제품 이름만(예: "Atobarrier365 Lotion").
[1 제품 소개] **모델·손과 제품이 한 사진에 함께 있으면 1B**(사진이 칸을 꽉 채우고 글이 사진 위에 올라가는 구성)를 쓴다
  (사람 검수 11-11: 바세린·아누아·에스트라 로션 1B 좋음). 970×300 비율에 맞추기 어려워도 1A 로 바꾸지 말고,
  제품이 가장 잘 보이는 쪽으로 box 를 옮겨 자른다(글 상자는 왼쪽에 올라가므로 제품은 오른쪽·가운데에 오게).
  **모델 얼굴만 나오고 제품이 없는 사진뿐이면 1A**(제품 사진 중심)를 쓴다(비디비치·마녀공장은 1A 가 나았음).
  1B 의 큰 글씨(headline)는 **제품명**으로 쓴다(효능 문구 아님). 제품명이 길면 짧은 이름으로(예: "Lip Therapy Color + Care").
  1B 사진 box 는 **제품 전체가 들어가게** 정한다(제품이 위아래·옆으로 잘리면 안 됨).
  제품 사진만 있을 때 1A. HERO 섹션이 없어도 비우지 않는다. 제품이 잘 보이는 사진 하나(어느 섹션이든, 리뷰 섹션 제외) +
  제품명(아래 '상품 이름'에서 브랜드·제품명만 깔끔하게)으로 1A 를 만든다. 이때 sources 는 [] 로 둔다.
[4 신뢰·증명] 근거를 작게 여러 개 늘어놓지 않는다. 970×300 한 장에서 작은 항목은 안 보인다.
  - 기본은 **4A: 가장 중요한 근거 하나를 크게.** 그 근거의 **그래프·전후 사진을 큰 사진(image)으로** 쓰고, headline 에 수치·결과,
    body 에 조건(대상·기간·기관)을 쓴다. 제품 사진은 근거 그림이 전혀 없을 때만.
  - 같은 근거의 **전/후 사진 2장**을 크게 보여 줄 수 있으면 4B mode="before_after" 도 좋다.
  - 4B 나열은 근거 2~4개가 **각자 인증 마크·배지 그림**을 가지고 있을 때만. 글만 있는 근거("테스트 완료" 문구)를 나열하지 않는다.
  - 그림이 있는 근거(전후 사진·그래프)가 있으면 글만 있는 근거보다 먼저 고른다.
  - 근거 그림(그래프·전후 사진)은 **일부를 확대하지 말고 통째로** 쓴다: box 는 그래프·전후 사진 전체(제목·축·전/후 표시 포함)를 담고
    fit 은 contain(코드도 4A·4B 근거 그림은 contain 으로 고정). (사람 검수 11-12: 닥터디퍼런트 그래프 일부 확대 안 됨)
[5 옵션·라인업] 옵션(색상·향)은 **전부** 넣는다(최대 12개). 스와치 사진은 **모두 같은 종류**(예: 전부 입술 발색, 전부 단품 사진)로
  같은 크기·같은 구도가 되게 자르고, 한 칸에 제품 여러 개가 들어간 사진은 쓰지 않는다. 같은 종류로 맞출 수 없으면 색 코드(color)를 쓴다.
  색상 옵션은 **발색샷(입술·피부에 바른 사진)이 있으면 발색샷을 먼저** 쓴다. 패키지 사진은 색이 안 보이거나 잘리면 쓰지 않는다
  (사람 검수 11-11: 패키지 사진으로는 색 구분이 안 됨).
[5B 라인업] 콜라보·에디션·한정·기획세트 이름(예: "Powerpuff Girls Edition")은 쓰지 않고 **그냥 브랜드 라인업**으로 쓴다
  (headline 예: "The UNOVE Deep Damage Repair Line"). 항목은 **제품명 + 제품 종류 한 줄**(예: "Deep Damage Repair Shampoo" / "Protein ampoule shampoo"),
  이 상품 자체도 라인업에 넣는다. 증정품·1+1·향 목록 나열은 넣지 않는다(사람 검수 11-11: 처음 결과의 구성이 좋음).
  5B 항목 사진은 **그 제품(용기·포장) 단독 사진**만 쓴다. 모델 얼굴·사용 장면·원료·무드 사진은 안 된다. 라인업 섹션에 이 상품 사진이 없으면
  다른 섹션(대표·제품 소개 등)의 제품 단독 컷을 쓰고, box 를 잡은 그림의 섹션 번호를 section 에 정확히 적는다
  (사람 검수 11-12: 더페이스샵 미감수 라인업에 모델 얼굴이 들어감 — 제품 사진 box 에 섹션 번호를 잘못 적었음).
[3 성분 사진] 성분을 형상화한 그림(캡슐·원료 이미지 등)은 라벨이 OTHER 여도 **사진으로** 가져와 쓴다(글 재료는 아님).
[3 성분 고르기] 원문이 성분 3개 이상을 **각각 설명**하면 하나로 묶은 3A("A + B + C")로 만들지 말고 **3B 로 하나씩 나열**한다.
  원문이 성분 하나(또는 둘)를 중심으로 이야기할 때 3A. 성분 칸 글은 원문 성분 설명을 충실히 옮긴다(사람 검수 11-11: 아누아·마녀공장은 처음 결과가 나았음).
[7 브랜드] 7A 사진은 **그 브랜드의 제품 사진**을 우선 쓴다(무드 사진·다른 그림보다). (사람 검수 11-11: 바세린)
[아이콘] 2B·3B·7B 항목에 사진(box)을 주지 않는 항목은 items[].icon 에 뜻이 맞는 아이콘 이름 하나를 적는다(한 칸 안에서 되도록 겹치지 않게).
  **뜻이 맞는 아이콘이 없으면 icon 을 적지 않는다**(억지로 비슷한 것을 고르지 않음 — 그 칸은 번호로 남음, 사람 결정 11-12).
  이름: {ICON_LIST}
  원본에 항목별 그림(성분 사진·배지 등)이 있으면 사진이 먼저다 — 아이콘은 그림이 없을 때만(사람 결정 11-12).
[반복 칸 개수] 항목 수는 원문에 있는 개수대로(2~4개). 성분이 4개면 4개, 2개면 2개. 템플릿 기본 3개에 맞추지 않는다.
[6 사용법] 원문 사용법에 **단계마다 사진·그림이 있으면 6A**(각 단계 사진 사용).
  원문이 **번호 없는 줄글**이면 단계 번호를 억지로 만들지 않고 **6B 줄글형**(content.layout="prose", headline + body 문단)으로 짧게 옮긴다.
  원문에 번호 단계가 글로만 있으면 6B(단계 목록)."""

# 칸 크기로 계산한 대략적 글자 수 한도(영문, 공백 포함). 넘치면 렌더러가 글자를 줄이고 그래도 넘치면 경고한다.
sys.path.insert(0, str(RENDERER))
from renderer.icons import ICONS as _ICONS  # noqa: E402
SELECT = SELECT.replace("{ICON_LIST}", " · ".join(f"{k}({v[0]})" for k, v in _ICONS.items()))

SPECS = """템플릿별 칸(필드)과 글자 수 한도 — 영어 기준 대략치. 한도를 넘기지 말 것.
1A: label(브랜드명, 대문자, ≤20) · headline(제품명, ≤40, 2줄까지) · subheadline(≤36, 1줄) · body(≤120, 3줄) · image=제품 사진(contain)
1B: headline(제품명, ≤22, 1줄) · body(≤85, 2줄) · image=모델·손과 제품이 함께 있는 사진 970×300 꽉 채움(cover, 제품 안 잘리게)
2A: headline(≤28) · body(≤60, 1줄) · items 2~4개 [title(칸 3개면 ≤45, 4개면 ≤40)] · image=제품 사진
2A 대표 하나형: layout="single" · headline(대표 효능, ≤40, 2줄) · body(≤160, 4줄) · items 없음 · image=제품 사진
2B: items 2~4개 [title(≤30), body(≤55)] · image=제품 사진   (headline 없음)
3A: label(기본 KEY INGREDIENT) · headline(성분명, ≤20) · subheadline(≤36) · body(≤120) · image=원료·무드 사진(cover)
3B: headline(≤30) · items 2~4개 [title(3개면 ≤18, 4개면 ≤13), body(3개면 ≤45, 4개면 ≤32), image(선택: 아이콘)] · image=제품 사진
4A: headline(핵심 근거·수치, ≤30, 2줄) · body(조건·대상·기간·기관, ≤120) · mark(선택: 인증 마크 이미지) · image=근거 그래프·전후 사진(없으면 제품 사진)
4B: headline(모듈 제목, ≤38) · items 2~4개 [title(≤30, 2줄까지), image(필수: 배지·아이콘·수치 그림)]
    mode="before_after" 이면 items 정확히 2개 [title(라벨 ≤12), image(필수: 전/후 사진)]
5B: headline(≤38) · items 2~4개 [title(제품명, 3개면 ≤26), body(≤40), image(필수: 제품 사진)]
6A: headline(≤38) · items 2~4개 [title(단계 이름 ≤20), body(≤40), image(선택: 단계 그림)]
6B: headline(≤28) · items 2~4개 [title(≤40), body(3단계면 ≤60 1줄, 2단계면 ≤150)] · image=모델·제품 사진
6B 줄글형: layout="prose" · headline(≤28) · body(≤320, 7줄 문단) · items 없음 · image=모델·제품 사진
7A: label(기본 OUR STORY) · headline(브랜드명 ≤20) · body(≤330, 6줄) · image=브랜드 제품 사진(없으면 무드 사진)
7B: headline(≤38) · items 2~4개 [title(≤20), body(≤40), image(선택: 아이콘)]"""

SYSTEM = f"""너는 한국 화장품 상세페이지를 아마존 US A+ 모듈 이미지(970×300) 7장으로 바꾸는 편집자다.
섹션마다 라벨(A+ 내용 종류)과 7칸 번호(slot)가 이미 붙어 있다. 칸마다 템플릿을 고르고, 들어갈 영어 문구와 사진 위치를 정한다.

{SELECT}

{SPECS}

문구 규칙
- 미국 아마존 화장품 상세페이지의 자연스러운 영어. 한국어를 직역하지 말고 뜻을 살려 짧게.
- 한국 페이지에 있는 사실(수치, 시험 조건, 성분명)만 쓴다. 수치는 그대로 옮기고 지어내지 않는다.
- 근거 수치를 쓰면 body 에 조건(대상·기간 등)을 짧게 붙인다.
- 의약품처럼 보이는 표현(treat, cure, heal, prevent disease 등)은 쓰지 않는다.
- 규제 검사·번역 다듬기는 이 단계의 범위 밖이다(2026-11-11 결정). 원문 뜻대로 옮기고 규제 표시(flags)는 달지 않는다.
- 리뷰·별점·평점·판매 1위·'#1' 같은 순위 표현은 쓰지 않는다.
- 본문 안의 Tip·Note 같은 덧붙임은 앞에서 줄을 바꾼다(문자열에 \\n). 예: "...until absorbed.\\nTip: ..."

사진 규칙
- 사진은 주어진 섹션 그림에서 직사각형으로 잘라 쓴다. 그림 가장자리의 눈금(0~100%)을 보고 위치를 정한다.
- box = [왼쪽, 위, 오른쪽, 아래] 를 그림 크기 대비 0~1 비율로. 글자가 많이 들어간 곳은 피하고 사진·제품만 담기게.
- 제품 사진(contain)은 제품 전체가 들어가게, 정사각형에 가깝게. 모델·무드 사진(cover)은 넉넉하게.
- 4B 배지·5B 제품·6A 단계 그림처럼 칸마다 사진이 필요하면 items 마다 box 를 준다.

출력은 JSON 배열 하나(칸 1~7 순서), 설명을 붙이지 않는다. 항목 형식:
{{"slot":1,"template":"1A","why":"고른 이유(한국어 한 문장)","sources":["S07"],
 "content":{{"headline":"...","subheadline":"...","body":"...","label":"...","mode":null,"layout":null,
            "items":[{{"title":"...","body":"..."}}]}},
 "ko":{{"headline":"한국어 뜻","subheadline":"","body":"","label":"","items":[{{"title":"","body":""}}]}},
 "images":{{"main":{{"section":"S07","box":[0.1,0.2,0.9,0.8],"fit":"contain"}},"mark":null,
           "items":[{{"section":"S06","box":[0,0,0.3,0.2],"fit":"contain"}}]}},
 "flags":["..."]}}
- content 에는 그 템플릿에 쓰는 필드만 넣는다. images.items 는 items 순서와 개수를 맞추고, 사진이 없는 항목은 null.
- 칸을 비울 때: {{"slot":7,"template":null,"why":"재료 없음","sources":[]}}
- 맨 마지막에 전체 색 테마 하나를 추가 항목으로: {{"theme":{{"bg":"#FFFFFF","photo_bg":"#...","text":"#...","accent":"#..."}},"why":"한국 페이지 색에서 고른 이유"}}"""


def fingerprint():
    return hashlib.sha256(json.dumps({"s": SYSTEM, "m": MODEL, "e": MAX_EDGE, "v": 2}).encode()).hexdigest()[:10]


def font(size):
    for n in ("malgun.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            pass
    return ImageFont.load_default()


def with_ruler(path):
    """축소한 섹션 그림 왼쪽·위에 10% 눈금을 그린다(AI가 자를 위치를 비율로 말하기 쉽게)."""
    im = Image.open(path).convert("RGB")
    s = min(1.0, (MAX_EDGE - 40) / max(im.size))
    im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
    pad = 34
    canvas = Image.new("RGB", (im.width + pad, im.height + pad), (255, 255, 255))
    canvas.paste(im, (pad, pad))
    d = ImageDraw.Draw(canvas)
    f = font(12)
    for k in range(11):
        y = pad + round(im.height * k / 10)
        x = pad + round(im.width * k / 10)
        d.line([(pad - 8, y), (pad, y)], fill=(220, 0, 0), width=2)
        d.text((1, y - 7), f"{k * 10}", fill=(220, 0, 0), font=f)
        d.line([(x, pad - 8), (x, pad)], fill=(0, 90, 220), width=2)
        d.text((x - 6, 2), f"{k * 10}", fill=(0, 90, 220), font=f)
    return canvas


def b64(im):
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode()


def load_key():
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


SLOT_LABELS = {1: "HERO", 2: "BENEFIT", 3: "INGREDIENT", 4: "PROOF·CERT·COMPARE", 5: "VARIANT·LINEUP",
               6: "HOWTO·ROUTINE", 7: "BRAND"}


def slot_candidates(secs):
    """엄격 규칙: 칸 재료 후보 = 그 칸 라벨 섹션 (labels 의 slot 값, SOCIAL 등은 None)."""
    out = {n: [] for n in range(1, 8)}
    for s in secs:
        if s.get("slot") in out:
            out[s["slot"]].append(s["sid"])
    return out


PHOTO_BANNED = {"SOCIAL", "FAQ", "LOGO"}  # 사진을 가져오면 안 되는 섹션 라벨 (리뷰·안내·로고). OTHER(그림 위주 섹션)는 사진으로 허용 11-11


def apply_rules(slots, secs):
    """AI 답을 코드 규칙으로 바로잡는다 (2026-11-11 사람 검수 결과).
    - 엄격 규칙: 재료(sources)는 그 칸 라벨 섹션만 — 밖이면 뺀다
    - 한 섹션은 한 칸에만 — 앞 칸에서 쓴 섹션은 뒤 칸에서 뺀다
    - 재료가 하나도 안 남은 칸은 빈 칸 (1 제품 소개는 예외: 제품 사진 + 제품명으로 채울 수 있음)
    - 리뷰·안내·로고 섹션에서 가져온 사진은 표시만 한다"""
    cands = slot_candidates(secs)
    lab = {s["sid"]: s for s in secs}
    used = {}
    for x in slots:
        n = x["slot"]
        x["flags"] = [f for f in (x.get("flags") or []) if not str(f).startswith("규제")]
        src = x.get("sources") or []
        drop = [s for s in src if s not in cands.get(n, [])]
        if drop:
            x["flags"].append("[규칙] 칸 밖 재료 뺌: " + ", ".join(f"{s}({lab.get(s, {}).get('label', '?')})" for s in drop))
        keep = []
        for s in src:
            if s in drop:
                continue
            if s in used:
                x["flags"].append(f"[규칙] {s} 는 칸 {used[s]} 에서 이미 써서 뺌")
                continue
            used[s] = n
            keep.append(s)
        x["sources"] = keep
        imgs = x.get("images") or {}
        pics = [("큰 사진", imgs.get("main")), ("마크", imgs.get("mark"))] + \
               [(f"항목{i + 1} 사진", im) for i, im in enumerate(imgs.get("items") or [])]
        if x.get("template") == "5B":  # 11-12: 라인업 제품 사진이 문제·제형·사용법 섹션이면 모델·장면일 가능성 큼
            for i, im in enumerate(imgs.get("items") or []):
                lb = lab.get((im or {}).get("section"), {}).get("label")
                if lb in ("PROBLEM", "TEXTURE", "HOWTO", "ROUTINE", "SOCIAL", "BRAND"):
                    x["flags"].append(f"[확인] 5B 항목{i + 1} 사진이 {im['section']}({lb}) 섹션 — 제품 단독 사진인지 확인")
        for nm, im in pics:
            if im and lab.get(im.get("section"), {}).get("label") in PHOTO_BANNED:
                x["flags"].append(f"[규칙] {nm}이 {im['section']}({lab[im['section']]['label']}) 섹션에서 옴 — 확인 필요")
        if x.get("template") in ("4A", "4B"):  # 근거 그림은 확대(cover)하지 않고 통째로 (11-12)
            for im in [imgs.get("main")] + list(imgs.get("items") or []):
                if im and im.get("fit") != "contain":
                    im["fit"] = "contain"
        if x.get("template") and not keep and n != 1:
            x["flags"].append("[규칙] 재료가 없어 빈 칸으로 바꿈")
            x["template"] = None
    return slots


NEEDS_MAIN = {"1A", "1B", "2A", "2B", "3A", "3B", "4A", "6B", "7A"}  # 렌더러가 큰 사진(image)을 꼭 요구하는 템플릿
PKG_RE = re.compile(r"\s*(\(|\[)?\s*(단독\s*)?(기획|증정|한정|더블|1\+1|세트)[^)\]]*(\)|\])?|\s*\(?\+\s*\S*\d.*$|\s*\d+(\.\d+)?\s*(ml|mL|ML|g|G|매|ea|EA)\b.*$")


def clean_name(name):
    """올리브영 상품명에서 기획·증정·구성·용량 표기를 뗀다 (예: '…로션 150ml 기획(+토너25ml…)' → '…로션')."""
    n = re.sub(r"\[[^\]]*\]", " ", name or "")  # [단독기획] 같은 머리표
    n = PKG_RE.sub("", n)
    return re.sub(r"\s+", " ", n).strip() or (name or "")


TIP_RE = re.compile(r"\s+(?=(Tip|TIP|Pro tip|Note|NOTE)\s*:)")


def tip_newline(slots):
    """본문의 'Tip:'·'Note:' 앞에서 줄을 바꾼다 (11-11 사람 검수: 팁은 줄바꿈해서 보이게)."""
    for x in slots:
        c = x.get("content") or {}
        for k in ("body", "subheadline"):
            if isinstance(c.get(k), str):
                c[k] = TIP_RE.sub("\n", c[k])
        for it in c.get("items") or []:
            if isinstance(it.get("body"), str):
                it["body"] = TIP_RE.sub("\n", it["body"])
    return slots


def fill_missing_photos(slots):
    """필수 큰 사진이 비었으면 칸 1(또는 앞 칸)의 큰 사진을 다시 쓴다 — 사진 때문에 렌더링이 실패하지 않게 (11-11)."""
    donor = next((x["images"]["main"] for x in slots
                  if x.get("template") and (x.get("images") or {}).get("main")), None)
    for x in slots:
        if x.get("template") in NEEDS_MAIN and not (x.get("images") or {}).get("main") and donor:
            x.setdefault("images", {})["main"] = dict(donor)
            x.setdefault("flags", []).append("[규칙] 큰 사진이 없어 다른 칸의 제품 사진을 다시 씀 — 확인 필요")
    return slots


SIDE_PROMPT = """이 사진은 970×300 배너 배경으로 꽉 채워 쓴다. 글 상자가 한쪽(왼쪽 6~49% 또는 오른쪽 51~94%)을 덮는다.
사진 속 화장품 제품(용기·패키지)이 가로로 어디에 있는지 보고 JSON 하나로만 답하라:
{"product_x": 제품 가로 중심(0=왼쪽 끝, 1=오른쪽 끝), "visible": 제품이 알아볼 수 있게 보이면 true(너무 잘리거나 거의 안 보이면 false)}"""


def picture_span(path, y0, y1):
    """섹션 그림의 y0~y1 띠에서 무늬가 있는 가로 범위(0~1). 양옆 단색 여백은 뺀다."""
    im = Image.open(path).convert("L")
    band = im.crop((0, round(y0 * im.height), im.width, max(round(y0 * im.height) + 1, round(y1 * im.height))))
    band = band.resize((max(1, band.width // 4), max(1, min(200, band.height))))
    px, W, H = band.load(), band.width, band.height
    def busy(cx):
        vals = [px[cx, yy] for yy in range(H)]
        m = sum(vals) / H
        return (sum((v - m) ** 2 for v in vals) / H) ** 0.5 > 6
    cols = [cx for cx in range(W) if busy(cx)]
    if not cols:
        return 0.0, 1.0
    return cols[0] / W, (cols[-1] + 1) / W


def side_1b(slots, out, by_sid, quiet=False):
    """1B: 자른 사진에서 제품 위치를 물어 글 상자를 제품 반대쪽에 둔다 (11-11 사람 검수: 글 상자가 제품을 가림).
    작은 그림 1장만 보내므로 칸당 약 1센트. 답은 사진 내용 지문으로 저장해 다시 묻지 않는다."""
    todo = [x for x in slots if x.get("template") == "1B" and (x.get("crops") or {}).get("main")]
    if not todo:
        return 0.0
    cost, client = 0.0, None
    for x in todo:
        p = out / "images" / x["crops"]["main"]
        key = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
        cf = out / "cache" / "side1b" / f"{key}.json"
        if cf.exists():
            ans = json.loads(cf.read_text(encoding="utf-8"))
        else:
            if client is None:
                load_key()
                import anthropic
                client = anthropic.Anthropic()
            im = Image.open(p).convert("RGB")
            im.thumbnail((800, 800))
            res = client.messages.create(model=MODEL, max_tokens=300, messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64(im)}},
                {"type": "text", "text": SIDE_PROMPT}]}])
            text = "".join(b.text for b in res.content if b.type == "text")
            ans = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
            cost += res.usage.input_tokens / 1e6 * PRICE_IN + res.usage.output_tokens / 1e6 * PRICE_OUT
            cf.parent.mkdir(parents=True, exist_ok=True)
            cf.write_text(json.dumps(ans, ensure_ascii=False), encoding="utf-8")
        px = float(ans.get("product_x", 0.7))
        # 제품이 가운데 쪽이면 자르는 자리를 옆으로 옮겨 제품을 글 상자 반대쪽(28% 안쪽 또는 72% 바깥)으로 보낸다(원본에 여유가 있을 때)
        mi = x["images"]["main"]
        x0, y0, x1, y1 = [float(v) for v in mi["box"]]
        w = x1 - x0
        if 0 < w < 1:
            ab = x0 + px * w
            target = max(px, 0.72) if px >= 0.5 else min(px, 0.28)
            lo, hi = picture_span(by_sid[mi["section"]]["crop"], y0, y1)  # 흰 여백까지 끌어오지 않게
            lo, hi = min(lo, x0), max(hi, x1)
            nx0 = min(max(ab - target * w, lo), hi - w)
            if abs(nx0 - x0) > 1e-3:
                mi["box"] = [round(nx0, 4), y0, round(nx0 + w, 4), y1]
                x.setdefault("flags", []).append(f"[규칙] 1B 제품이 글 상자 밑에 오지 않게 자르는 자리를 옆으로 옮김 ({x0:.2f}→{nx0:.2f})")
            px = (ab - nx0) / w
        x["_side"] = True
        if 0.38 < px < 0.62:  # 옮길 여유가 없어 제품이 여전히 가운데 → 글 상자가 가리므로 1A(사진 따로)로
            x["template"], x["mirror"] = "1A", False
            mi["fit"] = "contain"
            x["flags"].append(f"[규칙] 1B 제품이 가운데({px:.2f})라 글 상자가 가림 → 1A 로 바꿈")
            continue
        x["mirror"] = px < 0.5  # 제품이 왼쪽이면 글 상자를 오른쪽으로
        x.setdefault("flags", []).append(f"[규칙] 1B 제품 위치 {px:.2f} → 글 상자 {'오른쪽' if x['mirror'] else '왼쪽'}")
        if not ans.get("visible", True):
            x["flags"].append("[규칙] 1B 사진에서 제품이 잘 안 보임 — 사진 자리 확인 필요")
    return cost


def build_request(secs, product_name=""):
    content, tok = [], 0
    cands = slot_candidates(secs)
    content.append({"type": "text", "text": "상품 이름(기획·용량 표기 뗀 것): " + (clean_name(product_name) or "(모름)") + "\n칸별 후보(엄격 규칙 — 재료는 이 안에서만):\n"
                    + "\n".join(f"  칸 {n} ({SLOT_LABELS[n]}): {', '.join(cands[n]) or '없음'}" for n in range(1, 8))})
    for s in secs:
        im = with_ruler(s["crop"])
        tok += im.width * im.height / 750
        slot = f"칸 {s['slot']}" if s["slot"] else "7칸 밖(보조 재료)"
        text = "\n".join(s["texts"]) or "(읽은 글 없음)"
        content.append({"type": "text", "text": f"[{s['sid']}] 라벨 {s['label']} {s['sub'] or ''} → {slot}\n"
                                                 f"요약: {s['summary']}\n읽은 글(OCR):\n{text}"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64(im)}})
    content.append({"type": "text", "text": "위 섹션들로 칸 1~7을 채워 JSON 배열로 답하라(마지막에 theme 항목)."})
    return content, tok


def crop(sec, box, out):
    im = Image.open(sec["crop"]).convert("RGB")
    x0, y0, x1, y1 = [max(0.0, min(1.0, float(v))) for v in box]
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"잘못된 box {box}")
    im.crop((round(x0 * im.width), round(y0 * im.height), round(x1 * im.width), round(y1 * im.height))).save(out)
    return out


def build_slot(x, theme, by_sid, out):
    """칸 하나: 사진을 자르고 렌더러 입력 JSON(content/slotN_TID.json)을 쓴다. x 에 crops·errors·content_file 을 채워 돌려준다.
    (작업대 앱도 이 함수를 그대로 쓴다)"""
    import copy
    x["errors"] = []
    x.pop("content_file", None)
    if not x.get("template"):
        return x
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "content").mkdir(parents=True, exist_ok=True)
    tid = x["template"]
    c = {"template": tid, "mirror": bool(x.get("mirror")),
         **{k: v for k, v in copy.deepcopy(x.get("content") or {}).items() if v not in (None, "")}}
    if theme:  # 배경색(11-12 ②): 장마다 뒤집기(bg_flip)·글자 대비 보정 — bg_rules.py
        import bg_rules
        c["theme"] = bg_rules.card_theme(theme, bool(x.get("bg_flip")))
    imgs = x.get("images") or {}
    x["crops"] = {}
    try:
        mi = imgs.get("main")
        if mi:
            p = crop(by_sid[mi["section"]], mi["box"], out / "images" / f"slot{x['slot']}_main.png")
            c["image"] = {"src": str(p), "fit": mi.get("fit", "contain")}
            x["crops"]["main"] = p.name
        mk = imgs.get("mark")
        if mk:
            p = crop(by_sid[mk["section"]], mk["box"], out / "images" / f"slot{x['slot']}_mark.png")
            c["mark"] = {"src": str(p), "fit": "contain"}
            x["crops"]["mark"] = p.name
        for i, ii in enumerate(imgs.get("items") or []):
            if ii and i < len(c.get("items", [])):
                p = crop(by_sid[ii["section"]], ii["box"], out / "images" / f"slot{x['slot']}_item{i + 1}.png")
                c["items"][i]["image"] = {"src": str(p), "fit": ii.get("fit", "contain")}
                x["crops"][f"item{i + 1}"] = p.name
    except Exception as e:  # noqa: BLE001 — 자르기 실패는 화면에 보여 준다
        x["errors"].append(f"사진 자르기 실패: {e}")
    # 뜻 아이콘(11-12 디자인 고도화 ①): 2B·3B·7B 항목에 사진이 없으면 번호 원 대신 아이콘. AI 가 준 icon 우선, 없으면 낱말 규칙
    import icon_pick
    x["icons"] = icon_pick.pick(tid, c.get("items") or [])
    for old in (out / "content").glob(f"slot{x['slot']}_*.json"):
        old.unlink()
    name = f"slot{x['slot']}_{tid}"
    (out / "content" / f"{name}.json").write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
    x["content_file"] = f"content/{name}.json"
    return x


BOX_COLORS = [(230, 30, 60), (20, 110, 230), (20, 150, 80), (200, 120, 0), (140, 60, 200), (0, 150, 160)]
MARK_W = 380


def mark_sources(built, by_sid, out):
    """칸마다 재료 섹션 그림을 줄이고, 그 칸에 쓴 사진을 자른 자리를 색 상자로 표시한다."""
    d_out = out / "sources"
    d_out.mkdir(parents=True, exist_ok=True)
    for old in d_out.glob("*.jpg"):
        old.unlink()
    for x in built:
        boxes = {}  # sid → [(이름, box)]
        imgs = x.get("images") or {}
        named = [("사진", imgs.get("main")), ("마크", imgs.get("mark"))] + \
                [(f"항목{i + 1}", ii) for i, ii in enumerate(imgs.get("items") or [])]
        for nm, ii in named:
            if ii and ii.get("section") in by_sid:
                boxes.setdefault(ii["section"], []).append((nm, ii["box"]))
        sids = list(dict.fromkeys(list(x.get("sources") or []) + list(boxes)))
        x["src_marked"] = []
        for sid in sids:
            if sid not in by_sid:
                continue
            s = by_sid[sid]
            im = Image.open(s["crop"]).convert("RGB")
            k = MARK_W / im.width
            im = im.resize((MARK_W, max(1, round(im.height * k))), Image.LANCZOS)
            dr = ImageDraw.Draw(im)
            f = font(14)
            for j, (nm, b) in enumerate(boxes.get(sid, [])):
                col = BOX_COLORS[j % len(BOX_COLORS)]
                x0, y0, x1, y1 = [float(v) for v in b]
                r = [x0 * im.width, y0 * im.height, x1 * im.width, y1 * im.height]
                dr.rectangle(r, outline=col, width=3)
                tw = dr.textlength(nm, font=f) + 8
                dr.rectangle([r[0], r[1], r[0] + tw, r[1] + 18], fill=col)
                dr.text((r[0] + 4, r[1] + 1), nm, fill=(255, 255, 255), font=f)
            fn = f"slot{x['slot']}_{sid}.jpg"
            im.save(d_out / fn, quality=85)
            x["src_marked"].append({"sid": sid, "file": f"sources/{fn}", "label": s["label"],
                                    "summary": s.get("summary", ""), "is_source": sid in (x.get("sources") or []),
                                    "photos": [nm for nm, _ in boxes.get(sid, [])]})


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--name", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--render-only", action="store_true")
    ap.add_argument("--variant", default="", help="개선안 이름. 주면 step4/variants/<이름>/ 에 따로 만든다(원래 결과·작업대는 그대로)")
    a = ap.parse_args()

    base = HERE / "work" / a.product
    meta = base / "meta.json"
    pname = a.name or (json.loads(meta.read_text(encoding="utf-8")).get("name", "") if meta.exists() else "")
    labels = json.loads((base / "step3" / "labels_final.json").read_text(encoding="utf-8"))["sections"]
    crops = {s["sid"]: s for s in json.loads((base / "step2" / "section_texts.json").read_text(encoding="utf-8"))["sections"]}
    def absp(c):
        return c if Path(c).is_absolute() else str(REPO / c)
    secs = [dict(l, crop=absp(crops[l["sid"]]["crop"])) for l in labels if l["sid"] in crops]
    by_sid = {s["sid"]: s for s in secs}

    out = base / "step4" / "variants" / a.variant if a.variant else base / "step4"
    out.mkdir(parents=True, exist_ok=True)
    pj = out / "plan.json"
    if not a.variant and pj.exists() and json.loads(pj.read_text(encoding="utf-8")).get("edited") and not a.dry_run:
        raise SystemExit("작업대 앱에서 고친 내용이 plan.json 에 있어 덮어쓰지 않음. 앱에서 작업하거나, "
                         "plan.json 을 다른 이름으로 옮긴 뒤 다시 실행")
    # 캐시 이름에 입력(라벨·칸·요약·글) 지문도 넣는다 — 라벨이나 칸 연결이 바뀌면 옛 답을 다시 쓰지 않게 (11-11)
    import hashlib
    in_fp = hashlib.sha256(json.dumps([[s["sid"], s["label"], s["slot"], s["summary"], s["texts"]] for s in secs],
                                      ensure_ascii=False).encode()).hexdigest()[:8]
    cache = out / "cache" / f"{fingerprint()}_{in_fp}"
    cp = cache / "answer.json"
    old_cp = out / "cache" / fingerprint() / "answer.json"
    if not cp.exists() and old_cp.exists() and a.render_only:
        cp = old_cp  # 다시 그리기만 할 때는 예전 답 사용
    if not cp.exists() and a.render_only:  # 규칙 글이 바뀌어 지문이 달라졌어도, 다시 그리기는 가장 최근 답으로
        olds = sorted((out / "cache").glob("*/answer.json"), key=lambda q: q.stat().st_mtime)
        if olds:
            cp = olds[-1]
    if a.dry_run:
        _, tok = build_request(secs, pname)
        tin = tok + sum(len("\n".join(s["texts"])) for s in secs) * 1.2 + len(SYSTEM) * 1.2
        tout = 12000
        print(f"섹션 {len(secs)}개 · 입력 약 {tin:,.0f} 토큰 · 출력(생각 포함) 약 {tout:,} 토큰 → "
              f"예상 ${tin/1e6*PRICE_IN + tout/1e6*PRICE_OUT:.2f}. 호출 없음")
        return
    if cp.exists():
        c = json.loads(cp.read_text(encoding="utf-8"))
        ans, usage = c["answer"], c["usage"]
        print("캐시 사용 (비용 0)")
    else:
        if a.render_only:
            raise SystemExit("캐시가 없어 --render-only 불가")
        load_key()
        import anthropic
        content, _ = build_request(secs, pname)
        client = anthropic.Anthropic()
        with client.messages.stream(model=MODEL, max_tokens=48000, system=SYSTEM,
                                    output_config={"effort": "medium"},
                                    messages=[{"role": "user", "content": content}]) as st:
            res = st.get_final_message()
        if res.stop_reason == "refusal":
            raise SystemExit("Claude 가 거절함")
        text = "".join(b.text for b in res.content if b.type == "text")
        m = re.search(r"\[.*\]", text, re.S)
        ans = json.loads(m.group(0))
        usage = {"in": res.usage.input_tokens, "out": res.usage.output_tokens}
        cache.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps({"answer": ans, "usage": usage, "raw": text}, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    cost = usage["in"] / 1e6 * PRICE_IN + usage["out"] / 1e6 * PRICE_OUT
    print(f"Claude in {usage['in']} out {usage['out']} · ${cost:.4f}")

    theme = next((x.get("theme") for x in ans if "theme" in x), None)
    theme_why = next((x.get("why", "") for x in ans if "theme" in x), "")
    slots = sorted([x for x in ans if "slot" in x], key=lambda x: x["slot"])
    slots = tip_newline(fill_missing_photos(apply_rules(slots, secs)))

    # ---- 사진 자르기 + 렌더러 입력 만들기
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "content").mkdir(parents=True, exist_ok=True)
    for old in (out / "content").glob("*.json"):
        old.unlink()
    import bg_rules
    bg_rules.assign(slots)  # 배경 번갈아 뒤집기(11-12 ②)
    built = [build_slot(x, theme, by_sid, out) for x in slots]
    side_cost = side_1b(built, out, by_sid)
    if side_cost:
        print(f"1B 제품 위치 확인 ${side_cost:.4f}")
        cost += side_cost
    import zigzag
    re_zz = set(zigzag.alternate(built))  # 좌우 번갈아(11-12 ③) — 1B 글 상자 쪽까지 세어서
    re_bg = set(bg_rules.assign(built)) | re_zz  # 1B→1A 로 바뀐 칸이 있으면 배경 순서도 다시
    built = [build_slot(x, theme, by_sid, out) if (x.pop("_side", False) or x.get("slot") in re_bg) else x
             for x in built]  # 좌우·자리·템플릿·배경 바뀐 것 반영

    mark_sources(built, by_sid, out)

    # ---- 렌더링 (aplus_renderer 그대로 사용)
    sys.path.insert(0, str(RENDERER))
    from batch import run as render_batch  # noqa: E402
    files = sorted((out / "content").glob("*.json"))
    reps = render_batch(files, out / "renders", scale=1, html=False, quiet=True) if files else []
    rep_by = {r["name"]: r for r in reps}
    for x in built:
        if x.get("content_file"):
            r = rep_by.get(Path(x["content_file"]).stem, {})
            x["render"] = {"png": f"renders/{Path(x['content_file']).stem}.png" if "error" not in r else None,
                           "warnings": r.get("warnings", []), "error": r.get("error")}

    plan = {"product": a.product, "model": MODEL, "usage": usage, "cost_usd": round(cost, 4),
            "theme": theme, "theme_why": theme_why, "slots": built}
    (out / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "칸확인.html").write_text(page(a, plan, by_sid), encoding="utf-8")
    for x in built:
        r = x.get("render") or {}
        print(f"  칸 {x['slot']} {x.get('template') or '빈 칸'} · 재료 {x.get('sources')} · "
              f"{'오류 ' + str(r.get('error')) if r.get('error') else '경고 ' + str(len(r.get('warnings', [])))}"
              f"{' · ' + '; '.join(x['errors']) if x.get('errors') else ''}")
    print(out / "칸확인.html")


SLOT_NAME = {1: "제품 소개", 2: "효능", 3: "성분", 4: "신뢰·증명", 5: "옵션·라인업", 6: "사용법·루틴", 7: "브랜드"}
CSS = """
:root{--bg:#f4f5f7;--card:#fff;--ink:#1d2127;--sub:#5d6670;--line:#dfe3e8;--acc:#2f6fd6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 "Malgun Gothic",system-ui,sans-serif}
header{position:sticky;top:0;z-index:3;background:var(--card);border-bottom:1px solid var(--line);padding:12px 16px;
display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center}
h1{font-size:18px;margin:0}.sum{color:var(--sub)}
button{font:inherit;padding:6px 14px;border-radius:6px;border:1px solid var(--acc);background:var(--acc);color:#fff;cursor:pointer}
main{max-width:1500px;margin:0 auto;padding:12px 16px 80px}
.box{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin:12px 0}
.slot{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin-top:16px}
.slot h2{margin:0 0 8px;font-size:17px}.slot h2 small{color:var(--sub);font-weight:400}
.render img{width:100%;max-width:970px;display:block;border:1px solid var(--line)}
.grid{display:grid;grid-template-columns:400px 1fr;gap:18px;margin-top:6px;align-items:start}
@media (max-width:1000px){.grid{grid-template-columns:1fr}}
.src{display:flex;flex-direction:column;gap:12px;max-height:760px;overflow:auto;padding-right:6px;
border:1px solid var(--line);border-radius:8px;padding:8px;background:#fafbfc}
.srchead{font-weight:700;position:sticky;top:-8px;background:#fafbfc;padding:2px 0 4px;z-index:1}
.src figure{margin:0}.src img{width:100%;display:block;border:1px solid var(--line);border-radius:4px;margin-top:4px}
.src figcaption{font-size:12.5px}.lab{background:#eef2f7;border-radius:8px;padding:0 6px;font-size:12px}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
th{width:110px;color:var(--sub);font-weight:600}.ko{color:var(--sub)}
.crops{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}.crops figure{margin:0;text-align:center;font-size:12px;color:var(--sub)}
.crops img{height:110px;border:1px solid var(--line);background:repeating-conic-gradient(#eee 0 25%,#fff 0 50%) 0 0/12px 12px}
.warn{color:#c62828}.flag{color:#b45309}.why{background:#f6f8fb;border-radius:6px;padding:6px 10px}
.rev{display:flex;flex-wrap:wrap;gap:10px 18px;margin-top:10px;align-items:center}
.rev label{font-size:13px}textarea{width:100%;min-height:44px;font:inherit;border:1px solid var(--line);border-radius:6px;padding:6px;margin-top:6px}
.empty{color:#c62828;font-weight:700}
"""
JS = """
const KEY='step4_review_'+document.body.dataset.product;let st={};try{st=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}
function save(){try{localStorage.setItem(KEY,JSON.stringify(st))}catch(e){}}
document.querySelectorAll('.slot').forEach(el=>{const id=el.dataset.slot,v=st[id]||{};
 el.querySelectorAll('select').forEach(s=>{if(v[s.name])s.value=v[s.name];s.onchange=()=>{st[id]={...(st[id]||{}),[s.name]:s.value};save()}});
 const t=el.querySelector('textarea');if(t){t.value=v.m||'';t.oninput=()=>{st[id]={...(st[id]||{}),m:t.value};save()}}});
document.getElementById('csv').onclick=()=>{const rows=[['칸','템플릿','템플릿판단','문구판단','사진판단','메모']];
 document.querySelectorAll('.slot').forEach(el=>{const v=st[el.dataset.slot]||{};rows.push([el.dataset.slot,el.dataset.tid,v.t||'',v.c||'',v.p||'',v.m||''])});
 const csv='\\ufeff'+rows.map(r=>r.map(x=>'"'+String(x).replace(/"/g,'""')+'"').join(',')).join('\\r\\n');
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download='칸확인_결과.csv';a.click()};
"""


def sel(name, opts):
    return f'<select name="{name}"><option value="">-</option>' + "".join(f"<option>{o}</option>" for o in opts) + "</select>"


def page(a, plan, by_sid):
    e = html.escape
    blocks = []
    for x in plan["slots"]:
        n = x["slot"]
        srcs = "".join(
            f'<figure><figcaption><b>{e(m["sid"])}</b> <span class="lab">{e(m["label"])}</span>'
            f'{" · 글 재료" if m["is_source"] else ""}{" · 사진: " + ", ".join(m["photos"]) if m["photos"] else ""}'
            f'<div class="ko">{e(m["summary"])}</div></figcaption>'
            f'<a href="{e(m["file"])}" target="_blank"><img src="{e(m["file"])}" loading="lazy"></a></figure>'
            for m in x.get("src_marked", []))
        if not x.get("template"):
            blocks.append(f'<div class="slot" data-slot="{n}" data-tid=""><h2>칸 {n} {SLOT_NAME[n]} — <span class="empty">빈 칸</span></h2>'
                          f'<p class="why">{e(x.get("why", ""))}</p></div>')
            continue
        c, ko = x.get("content") or {}, x.get("ko") or {}
        rows = []
        for k in ("label", "headline", "subheadline", "body"):
            if c.get(k):
                rows.append(f"<tr><th>{k}</th><td>{e(c[k])}<div class='ko'>{e(ko.get(k, ''))}</div></td></tr>")
        for i, it in enumerate(c.get("items") or []):
            kit = (ko.get("items") or [{}] * 10)[i] if i < len(ko.get("items") or []) else {}
            rows.append(f"<tr><th>항목 {i + 1}</th><td><b>{e(it.get('title', ''))}</b> {e(it.get('body', '') or '')}"
                        f"<div class='ko'>{e(kit.get('title', ''))} {e(kit.get('body', '') or '')}</div></td></tr>")
        if c.get("mode"):
            rows.append(f"<tr><th>mode</th><td>{e(c['mode'])}</td></tr>")
        crops = "".join(f'<figure><img src="images/{e(v)}"><br>{e(k)}</figure>' for k, v in (x.get("crops") or {}).items())
        r = x.get("render") or {}
        img = f'<img src="{e(r["png"])}">' if r.get("png") else f'<p class="warn">렌더링 실패: {e(str(r.get("error")))}</p>'
        warns = "".join(f"<li class='warn'>{e(w)}</li>" for w in r.get("warnings", []) + x.get("errors", []))
        flags = "".join(f"<li class='flag'>{e(f)}</li>" for f in x.get("flags") or [])
        blocks.append(f"""<div class="slot" data-slot="{n}" data-tid="{e(x['template'])}">
<h2>칸 {n} {SLOT_NAME[n]} — {e(x['template'])} <small>재료 {', '.join(x.get('sources', []))}</small></h2>
<div class="grid"><div class="src"><div class="srchead">한국어 원본 섹션 <span class="ko">(색 상자 = 사진을 자른 자리, 클릭하면 크게)</span></div>{srcs}</div><div>
<div class="render">{img}</div>{'<ul>' + warns + flags + '</ul>' if warns or flags else ''}
<p class="why"><b>고른 이유:</b> {e(x.get('why', ''))}</p>
<table>{''.join(rows)}</table><div class="crops">{crops}</div>
<div class="rev"><label>템플릿 {sel('t', ['좋음', 'A/B 바꾸기', '다른 칸이 맞음'])}</label>
<label>문구 {sel('c', ['좋음', '고칠 곳 있음'])}</label>
<label>사진 {sel('p', ['좋음', '위치 다시', '다른 사진'])}</label></div>
<textarea placeholder="메모 (예: 제목을 더 짧게, 사진은 S07 제품만)"></textarea></div></div></div>""")
    t = plan.get("theme") or {}
    sw = "".join(f'<span style="display:inline-block;width:18px;height:18px;border:1px solid #ccc;background:{e(v)};vertical-align:middle"></span> {e(k)} {e(v)} &nbsp;' for k, v in t.items())
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>④ 칸 확인 {e(a.product)}</title><style>{CSS}</style></head><body data-product="{e(a.product)}">
<header><h1>④ 7칸 채우기 확인 — {e(a.name)}</h1><span class="sum">Claude {e(plan['model'])} · ${plan['cost_usd']}</span>
<button id="csv">판단 결과 CSV 내려받기</button></header><main>
<div class="box"><b>색 테마</b> {sw}<div class="ko">{e(plan.get('theme_why', ''))}</div></div>
<div class="box">칸마다 왼쪽: 이 모듈을 만든 <b>한국어 원본 섹션</b>(사진을 자른 자리는 색 상자) · 오른쪽: 완성 이미지(970×300), 고른 이유, 영어 문구(회색은 한국어 뜻), 자른 사진.
<span class="flag">주황</span>은 규제 확인 필요 표시, <span class="warn">빨강</span>은 글 넘침·오류. 칸마다 판단을 고르고 메모 → CSV.</div>
{''.join(blocks)}</main><script>{JS}</script></body></html>"""


if __name__ == "__main__":
    main()
