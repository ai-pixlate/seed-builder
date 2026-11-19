"""① 보충 — Claude가 섹션 경계를 다시 고른다 (임시. 실제 서비스는 ai-poc Gemini 방식).

ai-poc 코드는 고치지 않는다. ai-poc가 만든 결과(plan)를 **읽기만** 하고, 같은 방식을 이 파일에서 따로 한다.
    - ai-poc color_snap_vlm2 와 같은 방식: 자를 수 있는 여백마다 번호 붙은 빨간 선을 그려 보여 주고
      AI가 **번호만** 고르게 한다(좌표를 묻지 않음 → 글자를 자를 일이 없음)
    - 다른 점 ① AI가 Gemini 가 아니라 Claude (팀 Gemini 키가 없어 임시로)
    - 다른 점 ② 긴 구간만이 아니라 **그림 전체**를 보여 준다. 배경색 전환 자리(파란 선)도 후보로 보여 주고
      AI가 쓸지 말지 고른다. 무료 단계(color_snap_ws)의 아래쪽 섹션이 엉망이었기 때문(2026-11-10 사용자 검토)

    py -3.12 aplus_auto/step1b_claude_split.py --product A000000206826 --dry-run   (비용 추정만)
    py -3.12 aplus_auto/step1b_claude_split.py --product A000000206826

출력: aplus_auto/work/<상품>/step1b_claude/
    sections/<그림>.json, crops/<그림>/<i>.jpg   — ai-poc 와 같은 형식 (step1_sections.py 가 그대로 읽음)
    prompts/   Claude 에 보낸 그림 조각
    cache/     Claude 응답 원본 (다시 돌리면 캐시 사용, 비용 0)
    meta.json  토큰·비용
"""
import argparse
import base64
import hashlib
import io
import json
import os
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

Image.MAX_IMAGE_PIXELS = None

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
AIPOC = Path(r"C:\Users\인공지능사관학교\Desktop\ai-poc")
PLAN = AIPOC / "poc" / "section_split" / "results" / "color_snap_ws" / "plan"
SRC = AIPOC / "data" / "golden_sample"

MODEL = "claude-opus-5-5"
PRICE_IN, PRICE_OUT = 4.00, 20.00   # $ / 1M tokens

# ai-poc run_color_vlm.py 와 같은 값
BLANK_TOL = 6.0
BLANK_GAP = 40
MIN_SECTION = 400
CAND_MERGE = 50     # ai-poc 는 150. 150이면 각주 아래·사진 위 여백이 앞 후보에 합쳐져 사라짐(Point.2 사례)
VIEW_W = 768
CHUNK_H = 2000
MIN_IMAGE_H = 1500   # 이보다 짧은 그림은 통째로 한 섹션

# ai-poc 프롬프트 v2 를 바탕으로, 파란 선(배경색 전환) 설명과 출력 형식만 덧붙임
SYSTEM = """너는 한국 이커머스 상품 상세페이지를 문맥 단위 섹션으로 나눈다.

상세페이지 한 장을 위에서 아래로 잘라 순서대로 준다. 이미지들은 이어져 있다.
**가로선과 `#번호`는 자를 수 있는 여백 후보**다. 빨간 선은 여백, 파란 선은 배경색이 바뀌는 여백이다.
파란 선이라고 꼭 자를 필요는 없다. 내용을 보고 판단한다.

**새 논점이 시작되는 자리의 번호**를 고른다.

나누는 신호
- 새 **소제목**이 등장한다. 예) "더 특별한 이유", "POINT 02", "Point.3", "Test", "FAQ", "HOW TO USE", "이런 분들께 추천"
- 다루는 대상이 바뀐다. 예) 성분 A 설명 → 성분 B 설명, 설문 결과 → 시험 결과
- 역할이 바뀐다. 예) 제품 소개 → 효과 근거 → 사용법 → 추천 대상 → 성분표

**큰 주제가 같아도 소제목으로 논점이 새로 시작되면 나눈다.** 성분 설명이 이어지더라도
성분마다 소제목이 따로 있으면 각각 한 섹션이다.

나누지 않는 자리
- 소제목과 그 바로 아래 설명·그래프·사진 사이 (소제목이 위 섹션 끝에 붙어 떨어지면 안 된다)
- 한 소제목 아래 나열된 항목 1·2·3 사이
- 시험 결과와 그 바로 아래 출처·각주 사이
- 다음 섹션을 여는 연결 문장(예: "즉, ~라면,")은 다음 섹션에 붙인다

문맥 전환이 없으면 빈 배열로 답한다.

출력은 JSON 하나만. 설명을 붙이지 않는다.
{"cuts": [3, 7], "sections": ["제품 소개", "핵심 성분", "사용법"]}

`sections`는 고른 번호로 나뉜 구간의 이름을 위에서부터 한국어로 적는다(개수 = cuts + 1)."""


def fingerprint():
    raw = json.dumps({"system": SYSTEM, "model": MODEL, "view_w": VIEW_W, "chunk_h": CHUNK_H,
                      "cand_merge": CAND_MERGE, "min_section": MIN_SECTION}, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:10]


def blank_centers(gray):
    std = gray.std(axis=1)
    b = std <= BLANK_TOL
    out, s = [], None
    for y, x in enumerate(b):
        if x and s is None:
            s = y
        elif not x and s is not None:
            if y - s >= BLANK_GAP:
                out.append((s + y) // 2)
            s = None
    return out


def candidates(centers, color_cuts, h):
    """여백 후보 + 배경색 전환 자리. 가장자리 가까운 것 빼고, 붙은 것은 하나로(색 전환 우선)."""
    pts = sorted([(y, "blank") for y in centers] + [(y, "color") for y in color_cuts])
    pts = [(y, k) for y, k in pts if MIN_SECTION <= y <= h - MIN_SECTION]
    merged = []
    for y, k in pts:
        if merged and y - merged[-1][0] < CAND_MERGE:
            if k == "color" and merged[-1][1] != "color":
                merged[-1] = (y, k)
            continue
        merged.append((y, k))
    return merged


def font(size):
    for name in ("malgun.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_chunks(img, cands):
    w = img.width
    s = VIEW_W / w
    seg = img.resize((VIEW_W, max(1, round(img.height * s))), Image.BILINEAR).convert("RGB")
    d = ImageDraw.Draw(seg)
    f = font(22)
    for i, (y, k) in enumerate(cands, 1):
        yy = round(y * s)
        col = (20, 90, 230) if k == "color" else (230, 20, 20)
        d.line([(0, yy), (VIEW_W, yy)], fill=col, width=3)
        label = f"#{i}"
        tw = int(d.textlength(label, font=f)) + 12
        d.rectangle([4, yy - 15, 4 + tw, yy + 15], fill=col)
        d.text((10, yy - 13), label, fill=(255, 255, 255), font=f)
    return [seg.crop((0, t, VIEW_W, min(seg.height, t + CHUNK_H))) for t in range(0, seg.height, CHUNK_H)]


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
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("amazon_crawler/.env 에 ANTHROPIC_API_KEY 가 없음")


def ask(client, chunks, n):
    content = [{"type": "text", "text": f"상세페이지 한 장을 위에서 아래로 {len(chunks)}조각으로 나눴다. 후보는 #1~#{n}."}]
    for i, ch in enumerate(chunks, 1):
        content.append({"type": "text", "text": f"[{i}/{len(chunks)}]"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64(ch)}})
    res = client.messages.create(model=MODEL, max_tokens=16000, system=SYSTEM,
                                 output_config={"effort": "medium"},
                                 messages=[{"role": "user", "content": content}])
    if res.stop_reason == "refusal":
        raise RuntimeError("Claude 가 응답을 거절함")
    text = "".join(b.text for b in res.content if b.type == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RuntimeError(f"JSON 을 찾지 못함: {text[:200]}")
    return json.loads(m.group(0)), {"in": res.usage.input_tokens, "out": res.usage.output_tokens}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    out = HERE / "work" / a.product / "step1b_claude"
    fp = fingerprint()
    cache = out / "cache" / fp
    for d in ("prompts", "sections", "crops"):
        (out / d).mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)

    plans = sorted(PLAN.glob(f"{a.product}_*.json"))
    if not plans:
        raise SystemExit("ai-poc run_color.py 결과(plan)가 없음")
    client = None
    if not a.dry_run:
        load_key()
        import anthropic
        client = anthropic.Anthropic()

    tok_in = tok_out = calls = n_chunks = 0
    t0 = time.perf_counter()
    for pp in plans:
        plan = json.loads(pp.read_text(encoding="utf-8"))
        src = next(SRC.rglob(plan["image"]))
        img = Image.open(src).convert("RGB")
        w, h = img.size
        cuts, labels = {}, []
        if h >= MIN_IMAGE_H:
            centers = blank_centers(cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY))
            cands = candidates(centers, plan["color_cuts"], h)
            if cands:
                chunks = render_chunks(img, cands)
                n_chunks += len(chunks)
                for i, ch in enumerate(chunks, 1):
                    ch.save(out / "prompts" / f"{pp.stem}_{i}.jpg", quality=85)
                # 이미지 토큰 대략치: 긴 변 1568px 로 줄인 뒤 (가로×세로)/750
                est = sum(min(1.0, 1568 / max(c.size)) ** 2 * c.size[0] * c.size[1] / 750 for c in chunks)
                if a.dry_run:
                    print(f"  {plan['image']:<24} {w}x{h}  후보 {len(cands):>2}  조각 {len(chunks)}  이미지 토큰 약 {est:,.0f}")
                    tok_in += est
                    continue
                cp = cache / f"{pp.stem}.json"
                if cp.exists():
                    c = json.loads(cp.read_text(encoding="utf-8"))
                    ans, usage, hit = c["answer"], c["usage"], " (캐시)"
                else:
                    ans, usage = ask(client, chunks, len(cands))
                    cp.write_text(json.dumps({"answer": ans, "usage": usage,
                                              "candidates": cands}, ensure_ascii=False, indent=1), encoding="utf-8")
                    hit = ""
                    calls += 1
                tok_in += usage["in"]
                tok_out += usage["out"]
                for k in ans.get("cuts", []):
                    try:
                        k = int(k)
                    except (TypeError, ValueError):
                        continue
                    if 1 <= k <= len(cands):
                        y, kind = cands[k - 1]
                        cuts[y] = "claude_color" if kind == "color" else "claude"
                labels = ans.get("sections", [])
                print(f"  {plan['image']:<24} 후보 {len(cands):>2}  선택 {len(cuts)}  in {usage['in']} out {usage['out']}{hit}")
        elif a.dry_run:
            print(f"  {plan['image']:<24} {w}x{h}  짧아서 통째로 한 섹션")
        if a.dry_run:
            continue

        bounds = [0] + sorted(cuts) + [h]
        crop_dir = out / "crops" / pp.stem
        crop_dir.mkdir(parents=True, exist_ok=True)
        secs = []
        for i, (y0, y1) in enumerate(zip(bounds, bounds[1:]), 1):
            img.crop((0, y0, w, y1)).save(crop_dir / f"{i:03d}.jpg", quality=92)
            secs.append({"index": i, "top_offset": y0, "range": [y0, y1], "height": y1 - y0,
                         "cut_source": "시작" if y0 == 0 else cuts[y0],
                         "ai_label": labels[i - 1] if i - 1 < len(labels) else "",
                         "crop": f"crops/{pp.stem}/{i:03d}.jpg"})
        (out / "sections" / f"{pp.stem}.json").write_text(json.dumps(
            {"image": plan["image"], "variant": f"claude_split ({MODEL})", "size": [w, h],
             "cuts": sorted(cuts), "snap_failed": [], "sections": secs}, ensure_ascii=False, indent=1),
            encoding="utf-8")

    cost = tok_in / 1e6 * PRICE_IN + tok_out / 1e6 * PRICE_OUT
    if a.dry_run:
        n_calls = sum(1 for p in plans if json.loads(p.read_text(encoding="utf-8"))["size"][1] >= MIN_IMAGE_H)
        out_est = 1000 * n_calls  # 실측: 호출당 생각·답 100~1,000 토큰
        cost = (tok_in + 3000) / 1e6 * PRICE_IN + out_est / 1e6 * PRICE_OUT
        print(f"→ 그림 조각 {n_chunks}장, 입력 약 {tok_in:,.0f} 토큰. 예상 비용 약 ${cost:.2f} (넉넉히 잡음). 호출 없음")
        return
    meta = {"model": MODEL, "fingerprint": fp, "calls": calls, "chunks": n_chunks,
            "tokens": {"in": tok_in, "out": tok_out}, "cost_usd": round(cost, 4),
            "sec": round(time.perf_counter() - t0, 1), "run_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"완료 — 호출 {calls}회 · in {tok_in} out {tok_out} · ${cost:.4f}")


if __name__ == "__main__":
    main()
