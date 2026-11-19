"""자른 선을 '색이 바뀌는 지점'으로 옮긴다 (2026-11-12 사용자 제안: 한국 상세페이지는 섹션마다 배경색이 바뀐다).

- 선이 빈 여백(글·그림 없는 단색 줄들) 안에 있을 때만 움직인다 → 섹션 내용은 그대로, 잘린 자리만 깔끔해짐
- 그 빈 여백 안에 배경색이 바뀌는 줄이 있으면 가장 가까운 그곳으로 옮긴다. 없으면 그대로 둔다.
- 8개 상품 사람 검수와 비교(±40px): 정밀도 68%→71%, 재현율 78%→81%. 단순히 '가장 크게 색이 바뀌는 곳'은 사진 테두리로
  끌려가 오히려 53%/61% 로 나빠져서 쓰지 않음.
"""
import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
FLAT = 6.0      # 줄의 가로 표준편차가 이보다 작으면 단색 줄(빈 여백)
COL = 12.0      # 이웃 두 줄의 평균색 차이(RGB 합)가 이보다 크면 색이 바뀜
MAXGO = 400     # 위·아래로 이만큼까지만 살핀다(원본 px)


def rows(img):
    """그림 → (줄마다 평균색, 줄마다 가로 표준편차)"""
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    return a.mean(axis=1), a.std(axis=1).mean(axis=1)


def _flat(r, y):
    return r[1][y] < FLAT


def _same(r, a, b):
    return float(np.abs(r[0][a] - r[0][b]).sum()) < COL


def blank_span(r, y):
    """y 를 포함한 빈 여백(단색 줄이 이어지는 구간)의 [위, 아래). y 가 빈 줄이 아니면 None."""
    n = len(r[1])
    y = min(max(y, 0), n - 1)
    if not _flat(r, y):
        return None
    t = y
    while t - 1 >= 0 and y - t < MAXGO and _flat(r, t - 1):
        t -= 1
    b = y
    while b + 1 < n and b - y < MAXGO and _flat(r, b + 1):
        b += 1
    return t, b + 1


def snap_y(r, y):
    """선 y 를 빈 여백 안의 가장 가까운 '배경색 바뀌는 줄'로 옮긴 값. 해당 없으면 y 그대로."""
    span = blank_span(r, y)
    if not span:
        return y
    t, b = span
    cc = [yy for yy in range(t + 1, b) if not _same(r, yy - 1, yy)]
    return min(cc, key=lambda c: abs(c - y)) if cc else y


def same_content(r, y1, y2):
    """두 선 사이가 전부 빈 여백이면 잘린 섹션 내용이 같다(평가용)."""
    a, b = sorted((int(y1), int(y2)))
    b = min(b, len(r[1]))
    return b <= a or bool((r[1][a:b] < 12).all())
