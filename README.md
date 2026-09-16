# seed-builder

아마존 미국(US) 뷰티 카테고리 상품 상세페이지를 수집해서,
**번역 파이프라인에 넣을 원문 텍스트**로 가공하는 코드 모음이다.

이미지 안에 박혀 있는 글자까지 OCR 로 뽑아내고, 사람이 읽는 순서대로
재배열해서 엑셀/CSV 로 떨어뜨리는 것이 최종 목표다.

여기에 더해, 화장품 성분 번역에 쓸 **식약처 성분 용어집** 구축 코드가
`mfds/` 폴더에 따로 들어 있다.

---

## 시작하기

### 1. 필요한 것

- Python 3.12 (`py -3.12` 로 실행)
- 아마존 스크래핑 서비스(Decodo) API 토큰
- 식약처 공공데이터 API 인증키 (`mfds/` 작업을 할 때만)

### 2. 라이브러리 설치

```bash
py -3.12 -m pip install -r requirements.txt
```

### 3. API 토큰 넣기 (가장 먼저 할 일)

토큰은 코드에 적지 않는다. `.env` 파일에만 적어두고 코드가 읽어가는 방식이다.
`.env` 는 `.gitignore` 에 등록되어 있어 git 에 올라가지 않는다.

```bash
cp .env.example .env
```

그런 다음 `.env` 를 열어 토큰을 붙여넣는다.

```
DECODO_TOKEN=발급받은_토큰
```

식약처 작업을 한다면 `mfds/.env` 도 같은 방식으로 만든다.

```
MFDS_SERVICE_KEY_ENCODED=발급받은_인증키
```

### 4. OCR 을 돌린다면 — 모델 캐시 경로 주의

Paddle 의 추론 엔진은 **경로에 한글이 들어가면 모델 파일을 열지 못한다.**
그래서 `run_ocr.py` 는 모델 캐시를 `C:\paddlex_cache` (영문 경로) 로 강제한다.
이 폴더가 없으면 자동으로 만들어지므로 따로 할 일은 없지만,
경로를 바꿀 때는 반드시 **영문+숫자 경로**를 써야 한다.

자세한 내용은 [OCR_작업정리.md](OCR_작업정리.md) 참고.

---

## 실행 순서

앞 단계가 만든 파일을 뒤 단계가 읽는 구조라, **순서대로** 실행해야 한다.

| 순서 | 실행 | 하는 일 | 만들어지는 파일 |
|---|---|---|---|
| 1 | `py -3.12 get_asins.py` | 카테고리별 검색 결과에서 상품번호(ASIN) 수집 | `asin_list.csv` |
| 2 | `py -3.12 test_scrape.py` | 상품별 상세페이지 본문·이미지 주소 수집 | `validation_10_products.json` |
| 3 | `py -3.12 to_csv.py` | 위 JSON 을 엑셀에서 열리는 CSV 4개로 분리 | `out_products.csv` 외 3개 |
| 4 | `py -3.12 download_images.py` | 상세페이지 이미지 내려받기 | `images/` |
| 5 | `py -3.12 run_ocr.py` | 이미지 속 글자를 좌표와 함께 추출 | `out_ocr_lines.csv`, `out_images_ocr.csv` |
| 6 | `py -3.12 reorder_ocr.py` | 글자 읽는 순서 바로잡기 (XY-cut) | `out_*_ordered.csv` |
| 7 | `py -3.12 make_xlsx.py` | 최종 엑셀 파일로 합치기 | `ocr_reordered.xlsx` |

4·5번은 중간에 멈춰도 **다시 실행하면 이어서** 진행된다.
(`download_images.py` 는 이미 받은 파일을 건너뛰고,
`run_ocr.py` 는 `ocr_progress.json` 에 진행상황을 기록한다.)

---

## 파일 설명

### 본 파이프라인

| 파일 | 설명 |
|---|---|
| `get_asins.py` | 아마존 검색 → ASIN + 상품명 + 브랜드 수집 |
| `test_scrape.py` | 상세페이지 스크래핑 (본문, A+ 모듈, 이미지, Important Information) |
| `to_csv.py` | JSON → CSV 4종 변환 (상품 / 텍스트조각 / 이미지 / 주의사항) |
| `download_images.py` | OCR 대상 이미지 다운로드. 실패분은 `download_failed.csv` 에 기록 |
| `run_ocr.py` | PaddleOCR 로 이미지 텍스트 추출 (검출=server, 인식=mobile 조합) |
| `reorder_ocr.py` | 저장된 좌표만 보고 읽는 순서 재배열. OCR 을 다시 돌리지 않는다 |
| `make_xlsx.py` | 시트 3개짜리 최종 엑셀 생성. **행 순서를 절대 바꾸지 않는다** |
| `env_loader.py` | `.env` 에서 API 토큰을 읽어오는 공용 모듈 |

### `pair_` 로 시작하는 파일

위 파이프라인과 **하는 일이 동일하다.** 입출력 폴더 이름만 다르다.
전체를 다시 돌리지 않고 특정 상품(한국 브랜드 18종)만 따로 수집하려고 복제한 것.

> 코드가 두 벌이라 한쪽만 고치면 다른 쪽이 어긋난다.
> 추후 폴더명을 인자로 받는 한 벌로 통합할 것.

### 조사용 임시 코드

| 파일 | 설명 |
|---|---|
| `inspect_module_names.py` | 아마존 A+ 모듈의 id 패턴을 파악하려고 써본 코드 |
| `list_aplus_ids.py` | 상품별 A+ 모듈 id 목록 뽑기 |

### `mfds/` — 식약처 성분 용어집 (별도 작업)

| 순서 | 실행 | 하는 일 |
|---|---|---|
| 1 | `python mfds/step1_probe.py` | API 연결 확인 (응답 원문 그대로 출력) |
| 2 | `python mfds/step2_collect.py` | 성분 데이터 전량 수집 (500건씩, 끊겨도 이어받기) |
| 3 | `python mfds/step3_build.py` | 기존 용어집과 대조 → 차이 보고서 생성 |
| 4 | `python mfds/step4_glossary.py` | 식약처 전량을 용어집 형식 엑셀로 변환 |

정리 문서: `mfds/용어집_성분_구축정리_2026-09-14.md`

---

## git 에 올라가지 않는 것

`.gitignore` 에 등록되어 있다. 코드를 다시 돌리면 만들어지는 것들이다.

- `.env` — **API 토큰. 절대 올리지 않는다**
- `images/`, `images_pair/` — 내려받은 이미지 (약 570MB)
- `*_raw.html` — 긁어온 원본 HTML
- `out_*.csv`, `pair_*.csv`, `*.xlsx` — 가공 결과물
- `ocr_progress*.json`, `*_log.txt`, `review_report.txt` — 진행상황·로그

---

## 참고 문서

- [OCR_작업정리.md](OCR_작업정리.md) — OCR 도입 과정에서 막혔던 문제 4가지와 해결법,
  모델 조합 실측 비교, 최종 결과 수치 (이미지 1,437장 → 텍스트 25,336줄, 성공률 98.7%)
