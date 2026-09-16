# -*- coding: utf-8 -*-
"""
make_xlsx.py
------------
재정렬한 OCR 결과를 엑셀 파일(.xlsx) 하나로 만든다.

[가장 중요] 행 순서를 절대 바꾸지 않는다.
    out_images.csv 에 있던 1,522줄을 그 순서 그대로 유지한다.
    글자가 안 나온 빈 줄도 지우지 않는다.
    그래야 다른 엑셀 파일에 열만 복사해 붙여넣어도 상품이 어긋나지 않는다.

시트 3개:
    붙여넣기용   image_id / asin / ocr_text_ordered 만. 복사해서 바로 붙이는 용도
    전체         원본 모든 칸 + 재정렬 텍스트
    글자덩어리   글자 조각별 좌표 + 문단번호 + 읽는순서 (인페인팅용)

실행:  py -3 make_xlsx.py
"""

import csv
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

IMAGES_CSV = "out_images_ocr_ordered.csv"
LINES_CSV = "out_ocr_lines_ordered.csv"
BASE_CSV = "out_images.csv"          # 순서 기준이 되는 최초 수집본
OUT_XLSX = "ocr_reordered.xlsx"
ENCODING = "utf-8-sig"

HEAD_FILL = PatternFill("solid", fgColor="DDEBF7")
KEY_FILL = PatternFill("solid", fgColor="FFF2CC")


def read(path):
    with io.open(path, encoding=ENCODING, newline="") as f:
        return list(csv.DictReader(f))


def add_sheet(wb, title, header, rows, widths, wrap_cols=(), freeze="A2"):
    ws = wb.create_sheet(title)
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = HEAD_FILL
        c.alignment = Alignment(vertical="center")
    for r in rows:
        ws.append(r)
    ws.freeze_panes = freeze
    ws.auto_filter.ref = ws.dimensions
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for i in wrap_cols:
        for cell in ws[get_column_letter(i)][1:]:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    return ws


def main():
    imgs = read(IMAGES_CSV)
    base = read(BASE_CSV)

    # --- 안전장치: 순서가 원본과 한 줄이라도 어긋나면 만들지 않는다 ---
    if [r["image_id"] for r in imgs] != [r["image_id"] for r in base]:
        raise SystemExit("중단: 행 순서가 원본(out_images.csv)과 다릅니다.")

    wb = Workbook()
    wb.remove(wb.active)

    # 시트1: 붙여넣기용 (칸을 최소로. 순서는 원본 그대로)
    add_sheet(
        wb, "붙여넣기용",
        ["image_id", "asin", "image_type", "ocr_text_ordered"],
        [[r["image_id"], r["asin"], r["image_type"], r["ocr_text_ordered"]] for r in imgs],
        widths=[11, 13, 12, 130], wrap_cols=[4],
    )

    # 시트2: 전체 (원본 모든 칸 + 재정렬 결과)
    head2 = list(imgs[0].keys())
    ws2 = add_sheet(
        wb, "전체", head2,
        [[r[k] for k in head2] for r in imgs],
        widths=[11, 13, 14, 11, 15, 30, 20, 45, 10, 9, 60, 9, 10, 130, 10],
        wrap_cols=[head2.index("ocr_text_ordered") + 1],
    )
    for cell in ws2[get_column_letter(head2.index("ocr_text_ordered") + 1)]:
        cell.fill = KEY_FILL

    # 시트3: 글자덩어리별 좌표
    lines = read(LINES_CSV)
    head3 = list(lines[0].keys())
    add_sheet(
        wb, "글자덩어리", head3,
        [[r[k] for k in head3] for r in lines],
        widths=[11, 11, 13, 14, 11, 60, 8, 8, 8, 8, 11, 9, 12],
    )

    wb.save(OUT_XLSX)

    filled = sum(1 for r in imgs if r["ocr_text_ordered"].strip())
    print("저장: %s" % OUT_XLSX)
    print("  붙여넣기용 %d줄 (원본 out_images.csv 와 순서 100%% 동일, 빈 줄 유지)" % len(imgs))
    print("  그중 글자 있는 줄 %d개 / 빈 줄 %d개" % (filled, len(imgs) - filled))
    print("  글자덩어리 %d줄" % len(lines))


if __name__ == "__main__":
    main()
