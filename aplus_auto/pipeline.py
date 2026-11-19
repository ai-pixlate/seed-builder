"""업로드한 상세페이지 하나를 처음부터 끝까지 자동으로 돌린다 (작업대 앱이 부름, 명령줄로도 가능).

    py -3.12 aplus_auto/pipeline.py --product U20261110_1530

단계 (모두 지금까지 만든 코드를 그대로 부름)
    ① split      ai-poc run_color.py (코드 고치지 않음)            무료
    ② refine     step1b_claude_split.py (Claude 경계 보충)          유료
    ③ sections   step1_sections → step1c(빈 띠 자동 제외) → step1_sections  무료
    ④ ocr        step2_text.py (PaddleOCR 새로 읽기)               무료, 몇 분
    ⑤ label      step3_label.py → step3b (Claude 라벨)            유료
    ⑥ fill       step4_fill.py (Claude 칸 채우기 + 렌더링)          유료
    ⑦ final      step4b_fill_empty.py --base main (빈 칸 보충 → 최종 7장)  유료(빈 칸 있을 때)
진행 상황: work/<상품>/progress.json. 실패하면 그 단계부터 다시 실행할 수 있다(끝난 단계는 건너뜀, AI 응답은 캐시).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
AIPOC = Path(r"C:\Users\인공지능사관학교\Desktop\ai-poc")
PY = sys.executable

STEPS = [
    ("split", "섹션 나누기 (배경색)"),
    ("refine", "섹션 경계 다듬기 (Claude)"),
    ("sections", "섹션 확정 (그림 경계 합치기 포함)"),
    ("ocr", "한국어 글자 읽기"),
    ("label", "라벨 붙이기 (Claude)"),
    ("fill", "7칸 채우기·그리기 (Claude)"),
    ("final", "빈 칸 보충 → 최종 7장 (Claude, 빈 칸 있을 때만)"),
]


def env():
    e = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    if Path(r"C:\ms-playwright").is_dir():
        e["PLAYWRIGHT_BROWSERS_PATH"] = r"C:\ms-playwright"
    return e


class Run:
    def __init__(self, p):
        self.p = p
        self.base = HERE / "work" / p
        self.meta = json.loads((self.base / "meta.json").read_text(encoding="utf-8"))
        self.prog_path = self.base / "progress.json"
        if self.prog_path.exists():
            self.prog = json.loads(self.prog_path.read_text(encoding="utf-8"))
        else:
            self.prog = {"status": "waiting", "steps": {k: {"name": n, "status": "waiting"} for k, n in STEPS},
                         "cost_usd": 0.0}
        self.save()

    def save(self):
        tmp = self.prog_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.prog, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.prog_path)

    def sh(self, key, args, cwd=REPO):
        """하위 프로그램 실행. 출력 마지막 줄들을 진행 상황에 보여 주고, 비용 줄($)을 모은다."""
        st = self.prog["steps"][key]
        proc = subprocess.Popen([PY, *args], cwd=str(cwd), env=env(), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        tail = st.setdefault("log", [])
        for line in proc.stdout:
            line = line.rstrip()
            if not line or "ccache" in line or "�" in line or "warnings.warn" in line \
                    or "Model files already exist" in line or "\x1b[" in line:
                continue
            tail.append(line)
            del tail[:-15]
            m = re.search(r"\$(\d+\.\d+)", line)
            if m and ("in " in line or "완료" in line):
                c = float(m.group(1))
                st["cost_usd"] = round(st.get("cost_usd", 0) + c, 4)
                self.prog["cost_usd"] = round(self.prog.get("cost_usd", 0) + c, 4)
            self.save()
        if proc.wait() != 0:
            raise RuntimeError(f"{' '.join(Path(a).name for a in args[:1])} 실패 (마지막 줄: {tail[-1] if tail else '-'})")

    # ---------------------------------------------------------- 단계들
    def step_split(self):
        imgs = sorted((self.base / "input").glob("*.jpg"))
        # ai-poc 코드는 data/golden_sample 아래 그림을 읽게 되어 있다 → 코드는 그대로 두고 그림만 그 자리에 복사
        dst = AIPOC / "data" / "golden_sample" / f"images_{self.p}"
        dst.mkdir(parents=True, exist_ok=True)
        import shutil
        for i in imgs:
            shutil.copy2(i, dst / i.name)
        self.sh("split", [str(AIPOC / "poc" / "section_split" / "run_color.py"), "--images", *[i.name for i in imgs]],
                cwd=AIPOC)

    def step_refine(self):
        self.sh("refine", [str(HERE / "step1b_claude_split.py"), "--product", self.p])

    def step_sections(self):
        w = self.base
        nm = ["--name", self.meta.get("name", "")]
        self.sh("sections", [str(HERE / "step1_sections.py"), "--product", self.p, *nm,
                             "--source", str(w / "step1b_claude"), "--out-name", "step1_claude"])
        self.sh("sections", [str(HERE / "step1c_apply_review.py"), "--product", self.p,
                             "--sections", str(w / "step1_claude" / "sections.json")])
        # 여러 그림으로 잘린 상세페이지: 그림 경계에서 내용이 이어지면 합침 (그림 1장이면 경계 없음, 비용 0)
        self.sh("sections", [str(HERE / "step1d_merge_boundaries.py"), "--product", self.p])
        self.sh("sections", [str(HERE / "step1_sections.py"), "--product", self.p, *nm,
                             "--source", str(w / "step1_final_src"), "--out-name", "step1_final"])

    def step_ocr(self):
        self.sh("ocr", [str(HERE / "step2_text.py"), "--product", self.p, "--name", self.meta.get("name", "")])

    def step_label(self):
        self.sh("label", [str(HERE / "step3_label.py"), "--product", self.p, "--name", self.meta.get("name", "")])
        self.sh("label", [str(HERE / "step3b_apply_review.py"), "--product", self.p], cwd=HERE)

    def step_fill(self):
        self.sh("fill", [str(HERE / "step4_fill.py"), "--product", self.p, "--name", self.meta.get("name", "")])

    def step_final(self):
        # 빈 칸을 우선순위대로 채워 항상 7장 (2026-11-12). 결과: step4/final/ (작업대 '최종 7장' 버튼)
        self.sh("final", [str(HERE / "step4b_fill_empty.py"), "--product", self.p, "--base", "main"])

    def run(self):
        self.prog["status"] = "running"
        self.prog["started"] = self.prog.get("started") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.prog.pop("error", None)
        self.save()
        for key, _ in STEPS:
            st = self.prog["steps"].setdefault(key, {"name": dict(STEPS)[key], "status": "waiting"})
            if st["status"] == "done":
                continue
            st.update(status="running", error=None, log=[])
            t0 = time.time()
            self.save()
            try:
                getattr(self, f"step_{key}")()
            except Exception as e:  # noqa: BLE001 — 실패 내용을 화면에 보여 준다
                st.update(status="failed", error=str(e), sec=round(time.time() - t0))
                self.prog.update(status="failed", error=f"{st['name']}: {e}")
                self.save()
                return False
            st.update(status="done", sec=round(time.time() - t0))
            self.save()
        self.prog.update(status="done", finished=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.save()
        return True


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    a = ap.parse_args()
    ok = Run(a.product).run()
    print("완료" if ok else "실패 — progress.json 확인")


if __name__ == "__main__":
    main()
