"""배경색 규칙 (2026-11-12 디자인 고도화 ② 배경색, 사용자 결정: ③ 번갈아 뒤집기 + 글자 대비 보정)

테마 색은 그대로(7칸 단계 AI 가 한국 페이지에서 고른 bg·photo_bg·text·accent), 칠하는 자리만 장마다 정한다.
  - 모든 장(1B 제외)을 바로 앞 장과 반대로: 흰 바탕 ↔ 연한 바탕. 사진 구역이 있는 장이 연한 바탕이 되면 사진 구역은 흰색(뒤집기)
  - 첫 장: 사진 구역이 있으면 흰 바탕, 없으면 연한 바탕
  - 1B(사진이 칸 전체): 그대로
  - 글자 대비: 강조색을 글자(라벨·부제·번호)로 쓸 때 바탕과 대비가 4.5 미만이면 같은 계열로 진하게 한 accent_text 를 준다
    (렌더러 테마 accent_text — 도형·선·아이콘은 accent 그대로)
장마다 결과는 칸의 bg_flip(True/False)로 plan 에 남겨, 작업대에서 한 칸만 다시 그려도 같은 배경이 나오게 한다.
시안·비교: aplus_auto/design_bg/ (배경색_시안_2026-11-12.html)
"""
ZONELESS = {"4B", "5A", "5B", "6A", "7B"}
FULL = {"1B"}


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(c):
    return "#%02X%02X%02X" % tuple(max(0, min(255, round(v))) for v in c)


def _lum(h):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    """글자 대비(WCAG, 1~21). 본문 글자는 4.5 이상이면 읽기 좋음."""
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def accent_text(accent, bg, need=4.5):
    """대비가 모자라면 검정 쪽으로 조금씩 섞어(색 계열 유지) 처음 기준을 넘는 색. 충분하면 None."""
    if contrast(accent, bg) >= need:
        return None
    c = _rgb(accent)
    for k in range(1, 40):
        cand = _hex([v * (1 - k * 0.025) for v in c])
        if contrast(cand, bg) >= need:
            return cand
    return "#222222"


def flip_of(tids, mode="alternate"):
    """템플릿 순서 → 장마다 뒤집기 여부. mode: alternate(③) · zone_less(②) · fix_only(①)."""
    out, prev = [], None  # prev = 바로 앞 장(1B 제외)이 연한 바탕이었는지
    for tid in tids:
        if mode == "fix_only" or not tid or tid in FULL:
            out.append(False)
            continue
        if mode == "alternate":
            # 앞 장과 반대(첫 장: 사진 구역 있으면 흰 바탕, 없으면 연한 바탕).
            # 시안 1차는 사진 구역 장끼리만 세어 5·6장이 둘 다 연한 바탕 → 고침. 2차는 사진 구역 없는 장을 늘 연한 바탕으로 둬
            # 연한 장이 3장까지 이어짐(에스트라 4A·5B·6A) → 사진 구역 없는 장도 앞 장과 반대로(흰 바탕이면 예전 모습 그대로).
            f = (not prev) if prev is not None else (tid in ZONELESS)
        elif tid in ZONELESS:
            f = True
        else:
            f = False
        out.append(f)
        prev = f
    return out


def assign(slots, mode="alternate"):
    """plan 칸 목록(순서대로)에 bg_flip 을 적는다. 바뀐 칸 번호 목록을 돌려준다."""
    real = [x for x in slots if x.get("template")]
    changed = []
    for x, f in zip(real, flip_of([x["template"] for x in real], mode)):
        if bool(x.get("bg_flip")) != f:
            changed.append(x.get("slot"))
        x["bg_flip"] = f
    return changed


def card_theme(theme, flip=False):
    """장 하나에 쓸 테마. flip=True 이면 바탕 = 연한 테마색, 사진 구역 = 흰색."""
    t = {k: v for k, v in dict(theme).items() if k != "accent_text"}
    if flip:
        t["bg"], t["photo_bg"] = theme["photo_bg"], "#FFFFFF"
    at = accent_text(t["accent"], t["bg"])
    if at:
        t["accent_text"] = at
    return t
