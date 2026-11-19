"""규칙 1 — 페이지 리듬: 한 세트(최대 7장)를 순서대로 그릴 때 한쪽 사진 템플릿의 사진 위치를 번갈아 둔다.

- 대상(사진이 한쪽): 1A 2A 2B 3A 3B 4A 6B 7A
- 통짜·가운데 대칭(1B 4B 5A 5B 6A 7B)은 반전하지 않고 세는 순서에서도 건너뛴다.
- 시작 방향은 start(기본 오른쪽).
- 모듈 JSON 에 "mirror" 가 직접 적혀 있으면(true/false) 그 값을 따른다.
  그다음 장은 **바로 앞 한쪽 사진 장의 실제 방향의 반대**로 이어 간다(2026-11-10 사용자 결정 ②).
- mirror=false 는 사진 오른쪽(기본), true 는 사진 왼쪽.
"""
ONE_SIDED = {"1A", "2A", "2B", "3A", "3B", "4A", "6B", "7A"}


def apply_rhythm(contents, start="right"):
    """contents: 렌더러 입력 dict 목록(순서대로). mirror 를 채운 새 목록과 장마다 설명을 돌려준다."""
    if start not in ("right", "left"):
        raise ValueError("start 는 right 또는 left")
    prev = None
    out, notes = [], []
    for c in contents:
        c = dict(c)
        tid = c.get("template")
        if tid not in ONE_SIDED:
            notes.append(f"{tid}: 통짜·대칭 — 반전 안 함, 세는 순서에서 건너뜀")
            out.append(c)
            continue
        if isinstance(c.get("mirror"), bool):
            side = "left" if c["mirror"] else "right"
            why = "직접 지정"
        else:
            side = start if prev is None else ("left" if prev == "right" else "right")
            c["mirror"] = side == "left"
            why = "시작 방향" if prev is None else "앞 장의 반대"
        notes.append(f"{tid}: 사진 {'왼쪽' if side == 'left' else '오른쪽'} ({why})")
        prev = side
        out.append(c)
    return out, notes
