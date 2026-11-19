"""① 그림 경계 합치기 — 상세페이지가 여러 그림 파일로 잘려 있을 때, 파일 경계에서 내용이 이어지면 한 섹션으로 합친다.

2026-11-11 사용자 결정: 그림을 이어 붙여 다시 나누지 않는다. 그림은 그대로 두고
    - 긴 그림은 그 안에서 섹션을 나누고(앞 단계)
    - 그림과 그림 사이 경계에서, 앞 그림 끝 섹션과 다음 그림 첫 섹션이 **같은 내용이면 합치고**, 다르면 그대로 둔다.
판단은 Claude 가 한다(경계마다 위·아래 조각을 빨간 선으로 이어 붙인 그림을 보고, 이어지는지만 고름). 응답은 캐시.

    py -3.12 aplus_auto/step1d_merge_boundaries.py --product <상품> --dry-run
    py -3.12 aplus_auto/step1d_merge_boundaries.py --product <상품>

입력: work/<상품>/step1_final_src/sections/<그림>.json (그림별 섹션, step1c 결과)
출력: work/<상품>/step1_final_src/sections_all.json  (섹션 목록. 섹션마다 parts = [{그림, 범위}] — 여러 그림에 걸칠 수 있음)
      work/<상품>/step1_final_src/merged/*.jpg        (여러 그림에 걸친 섹션은 조각을 위아래로 붙인 그림, 폭은 가장 넓은 조각에 맞춤)
      work/<상품>/step1_final_src/boundary_pairs/     (Claude 에 보낸 경계 그림)
"""
import argparse
import base64
import hashlib
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
MODEL = "claude-opus-5-5"
PRICE_IN, PRICE_OUT = 4.00, 20.00
VIEW_W = 560      # 경계 그림 폭
EDGE_H = 900      # 경계 위·아래로 보여 줄 높이(원본 기준, 폭을 맞춘 뒤)

SYSTEM = """너는 한국 화장품 상세페이지를 문맥 단위 섹션으로 나누는 일을 돕는다.
원래 한 장으로 이어진 상세페이지가 저장할 때 여러 그림 파일로 잘렸다. 그래서 파일 경계에서 내용이 끊겨 있을 수 있다.

경계마다 그림 한 장을 준다. **빨간 가로선 위는 앞 그림의 끝부분, 아래는 다음 그림의 시작부분**이다.
빨간 선에서 같은 섹션이 이어지는지(merge=true), 새 섹션이 시작되는지(merge=false) 판단한다.

이어지는 것 (merge=true)
- 소제목은 위에 있고 그 설명·사진·그래프가 아래로 이어진다
- 한 소제목 아래 나열된 항목 1·2·3 이 선 위아래로 나뉘어 있다
- 시험 결과가 위에, 그 출처·각주가 아래에 있다
- 문장·표·사진 하나가 선에서 잘려 있다
- 위가 다음 내용을 여는 연결 문장(예: "즉, ~라면,")이고 아래가 그 내용이다

새로 시작하는 것 (merge=false)
- 아래에 새 소제목이 나온다. 예) "POINT 02", "HOW TO USE", "FAQ", "이런 분들께 추천"
- 다루는 대상·역할이 바뀐다. 예) 성분 설명 → 사용법, 설문 결과 → 다른 시험 결과
- 위는 한 섹션의 끝맺음(각주·여백)이고 아래는 다른 내용의 시작이다

애매하면 merge=false (나누어 두면 사람이 합치기 쉽다).
출력은 JSON 배열 하나만, 설명을 붙이지 않는다: [{"pair":1,"merge":true,"reason":"한국어 짧게"}]"""


def fingerprint():
    return hashlib.sha256(json.dumps({"s": SYSTEM, "m": MODEL, "w": VIEW_W, "h": EDGE_H}).encode()).hexdigest()[:10]


def font(size):
    for n in ("malgun.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            pass
    return ImageFont.load_default()


def to_w(im, w):
    return im.resize((w, max(1, round(im.height * w / im.width))), Image.LANCZOS)


def pair_image(top_crop, bot_crop, n):
    a = to_w(Image.open(top_crop).convert("RGB"), VIEW_W)
    b = to_w(Image.open(bot_crop).convert("RGB"), VIEW_W)
    k = VIEW_W / 1080  # EDGE_H 는 폭 1080 기준
    eh = round(EDGE_H * k)
    a = a.crop((0, max(0, a.height - eh), VIEW_W, a.height))
    b = b.crop((0, 0, VIEW_W, min(b.height, eh)))
    im = Image.new("RGB", (VIEW_W, a.height + 6 + b.height), (230, 20, 20))
    im.paste(a, (0, 0))
    im.paste(b, (0, a.height + 6))
    d = ImageDraw.Draw(im)
    f = font(20)
    d.rectangle([4, a.height - 13, 64, a.height + 19], fill=(230, 20, 20))
    d.text((10, a.height - 11), f"#{n}", fill=(255, 255, 255), font=f)
    return im


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


def stack(paths, out):
    ims = [Image.open(p).convert("RGB") for p in paths]
    w = max(i.width for i in ims)
    ims = [to_w(i, w) if i.width != w else i for i in ims]
    canvas = Image.new("RGB", (w, sum(i.height for i in ims)), (255, 255, 255))
    y = 0
    for i in ims:
        canvas.paste(i, (0, y))
        y += i.height
    canvas.save(out, quality=92)
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    src = HERE / "work" / a.product / "step1_final_src"
    files = sorted((src / "sections").glob("*.json"))
    pieces = []  # 그림 순서·그림 안 순서대로 모든 조각
    for fp in files:
        d = json.loads(fp.read_text(encoding="utf-8"))
        for s in d["sections"]:
            pieces.append({"image": d["image"], "range": s["range"], "crop": str(src / s["crop"]),
                           "ai_label": s.get("ai_label", ""), "cut_source": s.get("cut_source", "")})
    # 경계 = 그림이 바뀌는 자리
    bidx = [i for i in range(1, len(pieces)) if pieces[i]["image"] != pieces[i - 1]["image"]]
    (src / "boundary_pairs").mkdir(parents=True, exist_ok=True)
    pairs = []
    for n, i in enumerate(bidx, 1):
        im = pair_image(pieces[i - 1]["crop"], pieces[i]["crop"], n)
        im.save(src / "boundary_pairs" / f"pair_{n:02d}.jpg", quality=85)
        pairs.append(im)
    tok = sum(min(1.0, 1568 / max(p.size)) ** 2 * p.size[0] * p.size[1] / 750 for p in pairs)
    if a.dry_run:
        cost = (tok + 1500) / 1e6 * PRICE_IN + (60 * len(pairs) + 2000) / 1e6 * PRICE_OUT
        print(f"그림 {len(files)}장 · 조각 {len(pieces)}개 · 경계 {len(pairs)}곳 · 입력 약 {tok:,.0f} 토큰 → 예상 ${cost:.2f}. 호출 없음")
        return

    decisions = {}
    usage = {"in": 0, "out": 0}
    if pairs:
        cache = src / "cache" / fingerprint()
        cache.mkdir(parents=True, exist_ok=True)
        cp = cache / "answer.json"
        if cp.exists():
            c = json.loads(cp.read_text(encoding="utf-8"))
            ans, usage = c["answer"], c["usage"]
            print("캐시 사용 (비용 0)")
        else:
            load_key()
            import anthropic
            content = [{"type": "text", "text": f"경계 {len(pairs)}곳. 그림마다 #번호가 경계 번호다."}]
            for n, im in enumerate(pairs, 1):
                content.append({"type": "text", "text": f"[경계 #{n}]"})
                content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64(im)}})
            res = anthropic.Anthropic().messages.create(model=MODEL, max_tokens=16000, system=SYSTEM,
                                                        output_config={"effort": "medium"},
                                                        messages=[{"role": "user", "content": content}])
            if res.stop_reason == "refusal":
                raise SystemExit("Claude 가 거절함")
            text = "".join(b.text for b in res.content if b.type == "text")
            ans = json.loads(re.search(r"\[.*\]", text, re.S).group(0))
            usage = {"in": res.usage.input_tokens, "out": res.usage.output_tokens}
            cp.write_text(json.dumps({"answer": ans, "usage": usage}, ensure_ascii=False, indent=1), encoding="utf-8")
        decisions = {int(x["pair"]): x for x in ans}

    # 합치기: 경계에서 merge=true 면 앞 섹션에 이어 붙임
    merge_at = {i: decisions.get(n, {}) for n, i in enumerate(bidx, 1)}
    groups = []
    for i, p in enumerate(pieces):
        if i in merge_at and merge_at[i].get("merge") and groups:
            groups[-1]["parts"].append(p)
            groups[-1]["merge_reasons"].append(merge_at[i].get("reason", ""))
        else:
            groups.append({"parts": [p], "merge_reasons": [],
                           "split_reason": merge_at.get(i, {}).get("reason", "") if i in merge_at else ""})
    (src / "merged").mkdir(exist_ok=True)
    for old in (src / "merged").glob("*.jpg"):
        old.unlink()
    out = []
    for k, g in enumerate(groups, 1):
        parts = g["parts"]
        crop = parts[0]["crop"] if len(parts) == 1 else str(stack([q["crop"] for q in parts], src / "merged" / f"M{k:03d}.jpg"))
        out.append({"parts": [{"image": q["image"], "range": q["range"]} for q in parts], "crop": crop,
                    "ai_label": " + ".join(x for x in (q["ai_label"] for q in parts) if x),
                    "cut_source": parts[0]["cut_source"], "merge_reasons": g["merge_reasons"],
                    "split_reason": g["split_reason"]})
    cost = usage["in"] / 1e6 * PRICE_IN + usage["out"] / 1e6 * PRICE_OUT
    (src / "sections_all.json").write_text(json.dumps(
        {"product": a.product, "pieces": len(pieces), "boundaries": len(bidx),
         "merged_boundaries": sum(1 for v in merge_at.values() if v.get("merge")),
         "decisions": [dict(merge_at[i], pair=n, between=[pieces[i - 1]["image"], pieces[i]["image"]])
                       for n, i in enumerate(bidx, 1)],
         "sections": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"조각 {len(pieces)}개 · 경계 {len(bidx)}곳 중 {sum(1 for v in merge_at.values() if v.get('merge'))}곳 합침 "
          f"→ 섹션 {len(out)}개 · in {usage['in']} out {usage['out']} · ${cost:.4f}")


if __name__ == "__main__":
    main()
