"""자리 표시 이미지와 샘플 내용(JSON)을 만든다.

    py -3.12 make_samples.py

- samples/images/   : 회색 자리 표시 이미지 (실제 사진 대신)
- samples/content/  : 템플릿 14개 기본 샘플 JSON
- samples/content/variants/ : 반복 칸 개수·좌우 반전·긴 문구 등 변형

샘플 문구는 가상의 브랜드 LUMERA 를 쓴다. 화장품 범위의 표현만 쓴다
(치료·완치·100% 효과 같은 의약품처럼 보이는 표현 금지).
"""
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
IMG = ROOT / "samples" / "images"
CONTENT = ROOT / "samples" / "content"
VARIANTS = CONTENT / "variants"
FONT = ROOT / "fonts" / "NotoSans-VF.ttf"

INK = (92, 98, 106)


def font(size):
    f = ImageFont.truetype(str(FONT), size)
    try:
        f.set_variation_by_name("Bold")
    except Exception:
        pass
    return f


def say(d, xy, text, size, fill=INK):
    d.text(xy, text, font=font(size), fill=fill, anchor="mm")


# ---------------------------------------------------------------- 이미지
def bottle(path, kind="bottle"):
    """투명 배경 제품 실루엣 (contain 테스트용)."""
    im = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if kind == "bottle":
        d.rounded_rectangle((250, 70, 350, 150), 10, fill=(112, 120, 130))
        d.rectangle((262, 150, 338, 200), fill=(150, 160, 170))
        d.rounded_rectangle((200, 195, 400, 560), 36, fill=(180, 189, 198))
        say(d, (300, 380), "PRODUCT", 30)
    elif kind == "tall":
        d.rounded_rectangle((268, 30, 332, 120), 8, fill=(112, 120, 130))
        d.rectangle((278, 120, 322, 160), fill=(150, 160, 170))
        d.rounded_rectangle((230, 155, 370, 575), 28, fill=(186, 194, 202))
        say(d, (300, 370), "PRODUCT", 24)
    elif kind == "jar":
        d.rounded_rectangle((140, 260, 460, 330), 14, fill=(112, 120, 130))
        d.rounded_rectangle((160, 320, 440, 540), 30, fill=(180, 189, 198))
        say(d, (300, 430), "PRODUCT", 30)
    im.save(path)


def gradient(size, top, bottom):
    w, h = size
    im = Image.new("RGB", size)
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / max(1, h - 1)
        c = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
        d.line([(0, y), (w, y)], fill=c)
    return im


def model(path):
    """꽉 찬 사진 (cover 테스트용). 사람 실루엣은 오른쪽."""
    im = gradient((1600, 900), (214, 218, 222), (172, 178, 186))
    d = ImageDraw.Draw(im)
    d.ellipse((980, 210, 1220, 450), fill=(232, 234, 237))
    d.ellipse((820, 470, 1380, 1000), fill=(232, 234, 237))
    say(d, (1100, 640), "MODEL", 64)
    im.save(path)


def square(path, word, top, bottom, deco=None):
    im = gradient((900, 900), top, bottom)
    d = ImageDraw.Draw(im)
    if deco == "drops":
        for cx, cy, r in [(250, 260, 90), (640, 220, 60), (700, 620, 110), (230, 680, 50)]:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(226, 230, 234))
    elif deco == "rings":
        for r in (360, 260, 160):
            d.ellipse((450 - r, 450 - r, 450 + r, 450 + r), outline=(222, 226, 230), width=10)
    say(d, (450, 450), word, 72)
    im.save(path)


def circle(path, word, ring=False):
    """원형 아이콘·배지 (투명 배경)."""
    im = Image.new("RGBA", (240, 240), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if ring:
        d.ellipse((4, 4, 236, 236), fill=(206, 211, 217))
        d.ellipse((22, 22, 218, 218), outline=(150, 158, 168), width=6)
    else:
        d.ellipse((4, 4, 236, 236), fill=(206, 211, 217))
    say(d, (120, 120), word, 40 if len(word) <= 5 else 34)
    im.save(path)


def plain(path, size, word, shade):
    im = Image.new("RGB", size, (shade, shade, shade + 4))
    d = ImageDraw.Draw(im)
    say(d, (size[0] // 2, size[1] // 2), word, 56)
    im.save(path)


def make_images():
    IMG.mkdir(parents=True, exist_ok=True)
    bottle(IMG / "product.png", "bottle")
    bottle(IMG / "product_tall.png", "tall")
    bottle(IMG / "product_jar.png", "jar")
    model(IMG / "model.png")
    square(IMG / "mood.png", "MOOD", (220, 222, 226), (186, 190, 196), "rings")
    square(IMG / "ingredient.png", "INGREDIENT", (210, 216, 214), (180, 188, 186), "drops")
    circle(IMG / "icon.png", "ICON")
    circle(IMG / "badge.png", "BADGE", ring=True)
    plain(IMG / "step.png", (400, 400), "STEP", 196)
    plain(IMG / "before.png", (800, 344), "BEFORE", 168)
    plain(IMG / "after.png", (800, 344), "AFTER", 206)


# ---------------------------------------------------------------- 내용
I = "samples/images/"
PRODUCT = {"src": I + "product.png", "fit": "contain"}

BENEFITS = [
    {"title": "72-hour hydration", "body": "Helps skin hold moisture all day long."},
    {"title": "Soothes the look of redness", "body": "Centella comforts skin that feels stressed."},
    {"title": "Non-sticky finish", "body": "Absorbs fast with a fresh, soft feel."},
    {"title": "Supports the skin barrier", "body": "Ceramides help keep skin smooth and supple."},
]
INGREDIENTS = [
    {"title": "Hyaluronic Acid", "body": "Holds moisture for a plump, bouncy look", "image": I + "icon.png"},
    {"title": "Centella Asiatica", "body": "Soothes and comforts dry, tight skin", "image": I + "icon.png"},
    {"title": "Ceramide NP", "body": "Supports the skin's moisture barrier", "image": I + "icon.png"},
    {"title": "Panthenol", "body": "Helps soften rough, dry patches", "image": I + "icon.png"},
]
PROOFS = [
    {"title": "Dermatologist Tested", "image": I + "badge.png"},
    {"title": "Hypoallergenic", "image": I + "badge.png"},
    {"title": "Vegan Certified", "image": I + "badge.png"},
    {"title": "Cruelty Free", "image": I + "badge.png"},
]
STEPS = [
    {"title": "Cleanse", "body": "Wash your face and gently pat dry.", "image": I + "step.png"},
    {"title": "Apply", "body": "Smooth a pea-sized amount over face.", "image": I + "step.png"},
    {"title": "Pat gently", "body": "Pat lightly until fully absorbed.", "image": I + "step.png"},
    {"title": "Protect", "body": "Follow with sunscreen in the morning.", "image": I + "step.png"},
]
SHADES = [
    ("Petal", "#F2C4C0"), ("Rose", "#E39A9C"), ("Coral", "#EE8B6E"), ("Berry", "#B4485E"),
    ("Plum", "#7E3A55"), ("Nude", "#D9A88C"), ("Peach", "#F4B08F"), ("Brick", "#A9503C"),
    ("Mauve", "#B98393"), ("Cherry", "#C2283F"), ("Cocoa", "#7A4E3C"), ("Fig", "#5E3348"),
]
LINEUP = [
    {"title": "Hydra Calm Toner", "body": "Preps skin with a light layer of moisture", "image": I + "product_tall.png"},
    {"title": "Hydra Calm Gel Cream", "body": "All-day hydration with a non-sticky finish", "image": I + "product.png"},
    {"title": "Hydra Calm Night Mask", "body": "Rich overnight care for soft morning skin", "image": I + "product_jar.png"},
    {"title": "Hydra Calm Toner Pads", "body": "Quick, soothing prep on busy mornings", "image": I + "product_jar.png"},
]
PROMISES = [
    {"title": "Gentle formulas", "body": "Made without parabens or added fragrance", "image": I + "icon.png"},
    {"title": "Recyclable packaging", "body": "Bottles and cartons made to be recycled", "image": I + "icon.png"},
    {"title": "Made in Korea", "body": "Developed and produced in Seoul", "image": I + "icon.png"},
    {"title": "Tested on sensitive skin", "body": "Every formula is checked for comfort", "image": I + "icon.png"},
]
STORY = ("LUMERA began in a small Seoul lab with one idea: skincare should feel as calm as it looks. "
         "We pair gentle Korean botanicals with proven hydrators, test every formula on sensitive skin, "
         "and keep our ingredient lists short and clear.")


def c(template, **kw):
    d = {"template": template, "mirror": False}
    d.update(kw)
    return d


BASE = {
    "1A": c("1A", image=PRODUCT, label="LUMERA", headline="Hydra Calm Gel Cream",
            subheadline="Lightweight hydration for sensitive skin",
            body="A cooling gel cream with hyaluronic acid and centella that melts into skin, "
                 "leaving it soft, plump and comfortable all day."),
    "1B": c("1B", image={"src": I + "model.png", "fit": "cover"}, overlay=True,
            headline="Calm, dewy skin",
            body="A lightweight gel cream that absorbs fast and layers well under makeup."),
    "2A": c("2A", image=PRODUCT, headline="Why you'll love it",
            body="Lightweight gel cream for all-day hydration.",
            items=[{"title": b["title"]} for b in BENEFITS[:3]]),
    "2B": c("2B", image=PRODUCT,
            items=[dict(b, image=I + "icon.png") for b in BENEFITS[:3]]),
    "3A": c("3A", image={"src": I + "ingredient.png", "fit": "cover"}, headline="Hyaluronic Acid",
            subheadline="Deep, lasting moisture",
            body="Multi-weight hyaluronic acid draws moisture into the skin's surface layers "
                 "for a smooth, bouncy look."),
    "3B": c("3B", image=PRODUCT, headline="Key ingredients", items=INGREDIENTS[:3]),
    "4A": c("4A", image=PRODUCT, mark={"src": I + "badge.png"}, headline="Dermatologist Tested",
            body="Tested on sensitive skin under dermatologist supervision. "
                 "Individual results may vary."),
    "4B": c("4B", headline="Gentle by design", items=PROOFS[:3]),
    "5A": c("5A", headline="Choose your shade",
            items=[{"title": n, "color": h} for n, h in SHADES[:6]]),
    "5B": c("5B", headline="Complete your routine", items=LINEUP[:3]),
    "6A": c("6A", headline="How to use", round_images=True, items=STEPS[:3]),
    "6B": c("6B", image=PRODUCT, headline="How to use",
            items=[{"title": s["title"], "body": s["body"]} for s in STEPS[:3]]),
    "7A": c("7A", image={"src": I + "mood.png", "fit": "cover"}, headline="LUMERA", body=STORY),
    "7B": c("7B", headline="Our promise", items=PROMISES[:3]),
}


def with_items(tid, n, src):
    d = json.loads(json.dumps(BASE[tid]))
    d["items"] = json.loads(json.dumps(src[:n]))
    return d


def variants():
    v = {}
    # 반복 칸 2개 / 4개
    for tid, src in [("2A", [{"title": b["title"]} for b in BENEFITS]),
                     ("2B", [dict(b, image=I + "icon.png") for b in BENEFITS]),
                     ("3B", INGREDIENTS), ("4B", PROOFS), ("5B", LINEUP),
                     ("6A", STEPS),
                     ("6B", [{"title": s["title"], "body": s["body"]} for s in STEPS]),
                     ("7B", PROMISES)]:
        v[f"{tid}_items2"] = with_items(tid, 2, src)
        v[f"{tid}_items4"] = with_items(tid, 4, src)
    # 스와치 12개
    v["5A_swatch12"] = dict(BASE["5A"], items=[{"title": n, "color": h} for n, h in SHADES])
    # 좌우 반전
    for tid in ("1A", "2A"):
        v[f"{tid}_mirror"] = dict(BASE[tid], mirror=True)
    # 브랜드 색
    v["2A_theme"] = dict(BASE["2A"], theme={"bg": "#FFF8F3", "photo_bg": "#F6E3DA",
                                            "text": "#3A2A28", "accent": "#C0675A"})
    # 4B 전후 모드
    v["4B_before_after"] = c("4B", mode="before_after", headline="See the difference",
                             items=[{"title": "Before", "image": {"src": I + "before.png", "fit": "cover"}},
                                    {"title": "After", "image": {"src": I + "after.png", "fit": "cover"}}])
    # 제목 2줄 (아래 글 밀기 확인용)
    v["1A_title2"] = dict(BASE["1A"], headline="Hydra Calm Gel Cream for Sensitive Skin",
                          body="A cooling gel cream with hyaluronic acid and centella that "
                               "leaves skin soft and comfortable.")
    v["3A_title2"] = dict(BASE["3A"], headline="Hyaluronic Acid & Ceramide Complex")
    # 긴 문구 (넘침 경고 확인용)
    v["1A_long"] = dict(BASE["1A"],
                        headline="Hydra Calm Ultra-Light Gel Cream for Sensitive, Dehydrated Skin",
                        body="A cooling, featherlight gel cream made with three types of hyaluronic acid, "
                             "centella asiatica and ceramides. It melts into skin in seconds, leaves no "
                             "sticky film, sits well under sunscreen and makeup, and keeps skin feeling "
                             "soft, plump and comfortable from morning until night.")
    v["2A_long"] = dict(BASE["2A"], headline="Why thousands of people love this lightweight cream",
                        items=[{"title": "Up to 72 hours of lightweight, long-lasting hydration for dry skin"},
                               {"title": "Helps soothe the look of redness and comforts skin that feels tight"},
                               {"title": "Non-sticky finish"}])
    v["4A_long"] = dict(BASE["4A"], headline="Dermatologist Tested and Clinically Evaluated for Sensitive Skin",
                        body="Tested on 32 adults with self-reported sensitive skin under the supervision of "
                             "a board-certified dermatologist over four weeks of twice-daily use. Individual "
                             "results may vary. Patch test before first use.")
    v["6A_long"] = dict(BASE["6A"], items=[
        dict(STEPS[0], body="Wash your face with a gentle cleanser, rinse well with lukewarm water and pat dry."),
        STEPS[1], STEPS[2]])
    v["7A_long"] = dict(BASE["7A"], body=STORY + " Every product is designed to slip easily into your daily "
                        "routine, to feel good on the skin from the very first use, and to be gentle "
                        "enough for every season, every climate and every skin type in your family.")
    return v


STYLED = CONTENT / "styled"   # 2026-11-10 추가: 사진 처리·장식(style)·배치 변형(layout) 예시
SETS = ROOT / "samples" / "sets"


def styled():
    """옵션별 예시. 이름 = 템플릿_무엇."""
    def s(tid, layout=None, n=None, src=None, **style):
        d = json.loads(json.dumps(BASE[tid]))
        if n and src:
            d["items"] = json.loads(json.dumps(src[:n]))
        if layout:
            d["layout"] = layout
        if style:
            d["style"] = style
        return d
    v = {
        # 규칙 2 — 사진 처리
        "1A_photo-arch+backdrop-circle": s("1A", photo_shape="arch", photo_backdrop="circle"),
        "3A_photo-circle+border": s("3A", photo_shape="circle", photo_border="thin"),
        "2A_backdrop-blob": s("2A", photo_backdrop="blob"),
        "2B_backdrop-gradient": s("2B", photo_backdrop="gradient"),
        "4A_photo-rounded+backdrop-arch": s("4A", photo_shape="rounded", photo_backdrop="arch"),
        # 규칙 2 — 장식
        "1A_label-pill+underline-bar": s("1A", label="pill", headline_underline="bar"),
        "7A_label-pill+underline-line": s("7A", label="pill", headline_underline="line"),
        "3B_card+item-circle": s("3B", card=True, item_image_shape="circle"),
        "5B_card+item-rounded+underline": s("5B", card=True, item_image_shape="rounded", headline_underline="bar"),
        "6A_number-outline+dotted": s("6A", step_number="outline", step_connector="dotted"),
        "6A_number-big+line": s("6A", step_number="big", step_connector="line"),
        "6B_number-square": s("6B", step_number="square"),
        "2A_margin-dots": s("2A", margin_deco="dots"),
        "7B_margin-corner": s("7B", margin_deco="corner"),
        "4B_margin-circle": s("4B", margin_deco="circle"),
        # 규칙 3 — 배치 변형
        "2B_zigzag(4)": s("2B", layout="zigzag", n=4, src=[dict(b, image=I + "icon.png") for b in BENEFITS]),
        "4B_cards": s("4B", layout="cards"),
        "5A_chips": s("5A", layout="chips"),
        "5B_cards": s("5B", layout="cards"),
        "6A_zigzag": s("6A", layout="zigzag", step_connector="line"),
        "6A_timeline": s("6A", layout="timeline"),
        "6B_timeline": s("6B", layout="timeline"),
        "7B_cards": s("7B", layout="cards"),
        "1A_vcenter": s("1A", layout="vcenter"),
        "1A_center": s("1A", layout="center", headline_underline="bar"),
        "4A_vcenter": s("4A", layout="vcenter"),
        "7A_center": s("7A", layout="center", label="pill"),
    }
    return v


def sets():
    """규칙 1 페이지 리듬 예시: 7장 한 세트(파일 이름 순서 = 위→아래). mirror 를 적지 않은 장은 자동으로 번갈아."""
    def nm(d):
        d = json.loads(json.dumps(d))
        d.pop("mirror", None)
        return d
    auto = {"1_1A": nm(BASE["1A"]), "2_2A": nm(BASE["2A"]), "3_3B": nm(BASE["3B"]), "4_4B": nm(BASE["4B"]),
            "5_5B": nm(BASE["5B"]), "6_6B": nm(BASE["6B"]), "7_7A": nm(BASE["7A"])}
    fixed = dict(auto)
    fixed["2_2A"] = dict(auto["2_2A"], mirror=False)  # 2장째를 오른쪽으로 직접 지정 → 다음 장(3B)은 그 반대(왼쪽)
    return {"lumera_auto": auto, "lumera_fixed2": fixed}


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    make_images()
    CONTENT.mkdir(parents=True, exist_ok=True)
    VARIANTS.mkdir(parents=True, exist_ok=True)
    STYLED.mkdir(parents=True, exist_ok=True)
    for tid, d in BASE.items():
        write_json(CONTENT / f"{tid}.json", d)
    for name, d in variants().items():
        write_json(VARIANTS / f"{name}.json", d)
    for name, d in styled().items():
        write_json(STYLED / f"{name}.json", d)
    for sname, files in sets().items():
        d = SETS / sname
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*.json"):
            old.unlink()
        for fn, data in files.items():
            write_json(d / f"{fn}.json", data)
    print(f"이미지 {len(list(IMG.glob('*.png')))}개, 기본 샘플 {len(BASE)}개, 변형 {len(variants())}개, "
          f"사진·장식·배치 예시 {len(styled())}개, 세트 {len(sets())}개 작성")


if __name__ == "__main__":
    main()
