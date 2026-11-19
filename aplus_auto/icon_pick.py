"""뜻 아이콘 고르기 (2026-11-12 디자인 고도화 ① 아이콘 배치)

2B·3B·7B 항목에 원본 그림이 없을 때 번호 원 대신 넣을 아이콘을 정한다(렌더러 aplus_renderer/renderer/icons.py 목록).
원칙(사용자 11-12): 아이콘은 준비만 해 두고, **뜻이 맞는 게 있으면 쓰고 없으면 쓰지 않는다**(뜻 없는 일반 아이콘으로 채우지 않음).
  1) AI(7칸 단계)가 준 icon 이 목록에 있으면 그대로
  2) 없으면 영어 낱말 규칙(아래 RULES, 위에서부터 먼저 맞는 것) — AI 호출 없음
  3) 한 칸 안에서는 되도록 다른 아이콘. 맞는 게 이미 쓴 것뿐이면 같은 아이콘을 한 번 더 씀(뜻이 맞으니까)
  4) 맞는 아이콘이 없는 항목이 하나라도 있으면 그 칸은 아이콘을 넣지 않음(번호 원 그대로 — 아이콘과 번호가 섞이지 않게)
     → 그 항목을 design_icons/icon_misses.csv 에 쌓아 두고, 자주 나오는 뜻은 나중에 아이콘을 추가한다
항목에 사진(image)이 있으면 손대지 않는다(사진 우선).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "aplus_renderer"))
from renderer.icons import NAMES  # noqa: E402

TIDS = ("2B", "3B", "7B")
RULES = [  # (아이콘, 낱말 정규식) — 위에서부터 먼저 맞는 것. 11-12 아마존 1,735개 상품 점검으로 보강
    ("hair", r"hair|scalp|tangle|frizz|shampoo|condition|split end"),
    ("lash", r"lash|brow|volumi|lengthen|\bcurl"),
    ("eye", r"\beyes?\b|dark circle|puff|under[- ]?eye|eye bag"),
    ("waterproof", r"waterproof|water[- ]?resist|sweat|humidity|smudge[- ]?proof|transfer[- ]?proof"),
    ("sun", r"\bspf|\buv\b|sunscreen|sun protect|sunburn"),
    ("cool", r"cool|soothing|soothe|calm|redness"),
    ("shield", r"barrier|protect|defen|shield|strengthen"),
    ("scrub", r"exfoliat|scrub|peel|polish|keratosis|bumpy|rough texture"),
    ("bubbles", r"cleans|wash|foam|lather|residue|impurit|remov\w* makeup|makeup remov|rinse|emulsif|blackhead|sebum|detox|purif"),
    ("target", r"pore|targeted|spot|blemish|acne|trouble"),
    ("droplet", r"hydrat|moistur|dryness|\bdry\b|water[- ]?based|oil\b|\boils\b|jojoba|hyaluron|\bha\b|essence|serum|absorb"),
    ("nourish", r"nourish|repair|restor|replenish|damage|breakage"),
    ("matte", r"matte|non[- ]?sticky|oil control|shine control|velvet finish"),
    ("hold", r"\bhold\b|stay put|\block|setting spray|makeup setting|\bset (and|&|it|makeup)|\+ ?set\b|\bfix"),
    ("clock", r"long[- ]?last|long[- ]?wear|lasting|all[- ]?day|\b\d+[- ]?(hour|hr|h)\b|\bwear\b|stay|durab"),
    ("layers", r"coverage|cover\b|adhes|adhere|cling|blur|close[- ]?fit|layer|smudge|transfer|blendable|buildable|primer"),
    ("contour", r"contour|sculpt|chisel|cheekbone|defin"),
    ("antioxidant", r"antioxidant|free radical"),
    ("sparkle", r"glow|radian|bright|tone|toning|luminous|shine|shiny|gloss|dewy|vitamin c|glutathione|niacinamide|revitaliz|refresh|energiz|flawless|imperfection"),
    ("lift", r"firm|elastic|lift|wrinkle|fine line|collagen|peptide|anti[- ]?aging|aging|plump|tighten|rejuvenat|youthful"),
    ("leaf", r"gentle|mild|sensitive|non[- ]?irrit|low[- ]?irrit|natural|plant|botanical|cica|centella|chamomile|tea tree|herb|extract|hypoallergenic|non[- ]?comedogenic|paraben|sulfate[- ]?free"),
    ("sprout", r"vegan|\beco|clean beauty|cruelty"),
    ("grain", r"rice|grain|\bsoy|bean|\boat|seed|wheat|ferment"),
    ("fruit", r"fruit|acerola|berry|citrus|lemon|apple|peach|vitamin"),
    ("flower", r"flower|floral|\brose|scent|fragrance|lavender|camellia"),
    ("wave", r"\bspa\b|spa-|mineral|biome|probiotic|thermal|\bsea\b|marine|\bwater\b"),
    ("feather", r"light|weightless|soft|airy|feather|silky|velvet|smooth"),
    ("check", r"tested|clinical|dermatolog|certif|approved|verified|proven|\bsafe"),
    ("flask", r"tech|formula|complex|patent|research|\blab|ceramide|panthenol|allantoin|ingredient|pdrn|\bmw\b|micellar"),
    ("brush", r"brush|\btip\b|applicator|angled"),
    ("lips", r"\blips?\b"),
    ("swatch", r"shade|color|colour|tint|pigment|swatch|lipstick|blush"),
]
MISSES = Path(__file__).resolve().parent / "design_icons" / "icon_misses.csv"


def matches(txt):
    return [name for name, rx in RULES if re.search(rx, txt.lower())]


def candidates(it):
    """제목에서 맞는 게 있으면 제목 것만, 제목에 없을 때만 설명에서 찾는다.
    설명은 낱말이 많아 엉뚱한 아이콘이 걸리기 쉬움(예: 'waterproof makeup and sunscreen' → 해)."""
    t = matches(it.get("title") or "")
    return t if t else matches(it.get("body") or "")


def log_misses(tid, items):
    """맞는 아이콘이 없던 항목을 쌓아 둔다(나중에 아이콘 추가 판단용). 실패해도 그리기는 계속."""
    try:
        import csv
        from datetime import datetime
        new = not MISSES.exists()
        MISSES.parent.mkdir(parents=True, exist_ok=True)
        with open(MISSES, "a", encoding="utf-8-sig", newline="") as fo:
            w = csv.writer(fo)
            if new:
                w.writerow(["시각", "템플릿", "제목", "설명"])
            for it in items:
                w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M"), tid, it.get("title", ""), it.get("body", "")])
    except OSError:
        pass


def pick(tid, items, log=True):
    """items = 렌더러 content items(dict 목록). 아이콘을 정해 it['icon'] 에 넣고, 결과 설명 목록을 돌려준다."""
    if tid not in TIDS or not items:
        return []
    need = [i for i, it in enumerate(items) if not it.get("image")]
    if not need:
        return []
    used, chosen = [], {}
    for i in need:  # AI 가 준 것 먼저
        ic = items[i].get("icon")
        if ic in NAMES:
            chosen[i] = ic
            used.append(ic)
    for i in need:
        if i in chosen:
            continue
        cands = candidates(items[i])
        ic = next((c for c in cands if c not in used), cands[0] if cands else None)
        if ic:
            chosen[i] = ic
            used.append(ic)
    missing = [items[i] for i in need if i not in chosen]
    if missing:
        for i in need:
            items[i].pop("icon", None)
        if log:
            log_misses(tid, missing)
        return ["[아이콘] 뜻이 맞는 아이콘이 없는 항목이 있어 번호 원 그대로: " + ", ".join(m.get("title", "") for m in missing)]
    for i in need:
        items[i]["icon"] = chosen[i]
    return [f"{items[i].get('title', '')} → {chosen[i]}" for i in need]
