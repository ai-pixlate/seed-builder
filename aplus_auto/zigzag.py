"""좌우 번갈아(지그재그) 규칙 (2026-11-12 디자인 고도화 ③ 지그재그)

글 상자가 왼쪽/오른쪽에 있는 장을 번갈아 둔다. 기준은 '글 상자 쪽'.
  - 사진이 한쪽에 있는 템플릿(1A 2A 2B 3A 3B 4A 6B 7A): 앞 장의 글 상자 반대쪽에 글 상자(=사진은 반대쪽). 첫 장은 글 왼쪽·사진 오른쪽.
  - 1B(사진이 칸 전체 + 글 상자): 글 상자 쪽은 제품 위치로 이미 정해짐(side_1b) → 바꾸지 않고, 다음 장이 그 반대로 이어 가도록 '세기'만 한다.
    (예전 규칙은 1B 를 세지 않아, 1B 글 왼쪽 다음 장도 글 왼쪽 → 처음 두 장이 같은 쪽)
  - 대칭·통짜(4B 5A 5B 6A 7B): 바꾸지 않고 세지도 않음.
  - 같은 템플릿이 바로 이어지면 표시만.
mirror 의미: 한쪽 템플릿은 True = 사진 왼쪽(글 오른쪽). 1B 는 True = 글 상자 오른쪽.
"""
ONE_SIDED = {"1A", "2A", "2B", "3A", "3B", "4A", "6B", "7A"}


def text_side(x):
    t = x.get("template")
    if t in ONE_SIDED or t == "1B":
        return "right" if x.get("mirror") else "left"
    return None


def alternate(slots, count_1b=True):
    """slots 순서대로 mirror 를 정한다(1B 는 그대로). 바뀐 칸 번호 목록을 돌려준다."""
    prev, prev_t, changed = None, None, []
    for x in slots:
        t = x.get("template")
        if t in ONE_SIDED:
            side = "left" if prev in (None, "right") else "right"  # 글 상자 쪽
            m = side == "right"
            if bool(x.get("mirror")) != m:
                changed.append(x.get("slot"))
            x["mirror"] = m
            prev = side
        elif t == "1B" and count_1b:
            prev = text_side(x)
        if t and t == prev_t:
            fl = x.setdefault("flags", [])
            msg = f"[배치] 바로 앞 장과 같은 뼈대({t}) — 확인 필요"
            if msg not in fl:
                fl.append(msg)
        prev_t = t
    return changed
