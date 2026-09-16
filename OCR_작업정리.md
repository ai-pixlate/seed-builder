# PaddleOCR 이미지 텍스트 추출 작업 정리

**작업일** 2026-09-02
**대상** 아마존 US 뷰티 카테고리 상품 상세페이지 이미지
**목적** 픽슬레이트(뷰티 이커머스 상세페이지 로컬라이징 번역 서비스) 번역 파이프라인에 넣을 원문 텍스트 확보

---

## 1. 한 줄 요약

`run_ocr.py` 가 실행조차 되지 않던 상태였다. 원인 4가지를 찾아 고쳤고,
이미지 1,437장에서 텍스트 25,336줄을 좌표와 함께 추출 완료했다. 성공률 98.7%.

---

## 2. 실행을 막고 있던 문제와 해결

### 문제 1 — 한글 경로 (실행 자체가 불가)

**증상**
```
RuntimeError: (NotFound) Cannot open file
C:\Users\?????\.paddlex\official_models\PP-OCRv6_medium_det\inference.json
```

**원인**
모델 파일은 정상적으로 다운로드되어 있었다. 그런데 PaddlePaddle 의 C++ 추론 엔진이
경로에 한글(non-ASCII)이 들어가면 파일을 열지 못한다. 기본 캐시 위치가
`C:\Users\인공지능사관학교\.paddlex` 라서 걸렸다. 에러 메시지에서 사용자명이
`?????` 로 깨진 것이 그 증거.

**해결**
모델 캐시를 ASCII 경로 `C:\paddlex_cache` 로 이전.
스크립트가 `paddleocr` 를 import 하기 **전에** 환경변수를 직접 설정하도록 했다.

```python
CACHE_DIR = r"C:\paddlex_cache"
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", CACHE_DIR)
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
# 이 다음에야 paddleocr import
```

### 문제 2 — 모델과 엔진의 버전 불일치

**증상**
```
ValueError: (InvalidArgument) Type of attribute: strides is not right.
```

**원인**
설치된 `paddleocr 3.7.0` 은 기본 모델이 PP-OCRv6 인데,
설치된 엔진 `paddlepaddle 3.0.0` 이 이 모델을 감당하지 못한다.

**해결**
모델을 PP-OCRv5 로 명시적으로 고정.
```python
DET_MODEL = "PP-OCRv5_server_det"
REC_MODEL = "PP-OCRv5_mobile_rec"
```

### 문제 3 — numpy 배열 버그 (전량 실패 원인)

위 두 문제를 고친 뒤에도 20장 테스트에서 **20장 전부 실패**했다.

**증상**
```
The truth value of an array with more than one element is ambiguous.
```

**원인**
`extract_polys()` 안에서 `or` 연산자를 썼는데, `dt_polys` 가 numpy 배열이라
`배열 or 배열` 형태가 되면서 파이썬이 참/거짓 판단을 못 하고 예외를 던졌다.

```python
# 문제 코드
return first.get("dt_polys", []) or first.get("rec_polys", []) or []
```

**해결**
길이로만 판단하도록 수정.
```python
for key in ("dt_polys", "rec_polys"):
    polys = first.get(key)
    if polys is not None and len(polys) > 0:
        return polys
return []
```

### 문제 4 — 이어서 실행하면 데이터 유실

**원인**
인식된 줄 정보를 메모리 변수(`line_rows`)에만 담고 있었다.
중간에 멈췄다 재실행하면 이미 처리된 이미지는 건너뛰므로,
최종 `out_ocr_lines.csv` 에서 **앞부분이 통째로 빠졌다.**

**해결**
줄 정보를 `ocr_progress.json` 에 함께 저장하고, 최종 CSV 는 progress 전체를
훑어서 생성하도록 변경. 저장은 임시파일 → `os.replace` 로 원자적 교체.

---

## 3. 성능 개선

### 인식을 배치 처리로 변경

기존 코드는 글자 상자 하나마다 `recognizer.predict()` 를 개별 호출했다.
한 장에서 검출된 상자 전체를 리스트로 묶어 한 번에 넘기도록 변경.

```python
# 변경 후
for box, out in zip(boxes, recognizer.predict(crops)):
    ...
```

### 이미지 로딩 방식 변경

`predict(경로)` 대신 `predict(numpy 배열)` 로 넘기도록 변경.
`cv2.imdecode(np.fromfile(path, ...))` 를 써서 한글 경로에서도 안전하게 읽는다.

### 읽기 순서 정렬 로직 추가

y좌표만으로 정렬하면 같은 줄에 나란히 있는 글자가 1px 차이로 뒤바뀐다.
글자 높이의 절반 안쪽이면 같은 줄로 묶고, 그 안에서 x좌표(좌→우) 정렬.

결과: `Gently cleanses & removes up to 99% of makeup, including waterproof mascara`
처럼 문장이 자연스럽게 이어진다.

---

## 4. 모델 선택 근거

샘플 이미지 4장으로 3개 조합을 실측 비교했다.

| 조합 | 이미지당 소요 | 판정 |
|---|---|---|
| mobile_det + mobile_rec | ~1.0초 | 작은 이미지(300x225) 텍스트를 놓침 |
| **server_det + mobile_rec** | ~4초 | **채택.** 검출률 최고, 인식 정확 |
| server_det + server_rec | ~11초 | 느린데 오히려 오인식 (`Sunscren`, `gracstia`) |

server_rec 이 mobile_rec 보다 느린데도 정확도가 떨어지는 것이 실측으로 확인됐다.
검출(det)은 server, 인식(rec)은 mobile 조합이 최적.

---

## 5. 최종 결과

**총 소요시간** 약 2시간 40분 (11:37 ~ 14:16), 1,437장

| 항목 | 수치 |
|---|---|
| 처리 성공 | 1,418장 / 1,437장 (98.7%) |
| 글자를 찾은 이미지 | 1,361장 |
| 글자가 없던 이미지 | 57장 (제품 사진만 있는 경우) |
| 추출된 텍스트 줄 | 25,336줄 |
| 커버한 상품 | 85개 (ASIN 기준) |
| 평균 신뢰도 | 0.956 |
| 신뢰도 0.9 이상 | 1,265장 / 1,361장 |

### 카테고리별 추출량

| 카테고리 | 줄 수 |
|---|---|
| Sunscreens & Tanning | 6,792 |
| Face | 5,897 |
| Body | 3,658 |
| Eyes | 3,112 |
| Lip Care | 2,236 |
| Sets, Kits | 1,902 |
| Maternity | 1,739 |

### 실패 19장 — 전부 상품 이미지가 아님

- **오류 2장** (`I00963`, `I01053`) — 16x16 픽셀 8프레임 애니메이션 GIF.
  아마존 페이지의 로딩 스피너 아이콘이다.
- **파일 없음 17장** — 애초에 다운로드 실패한 것들. URL 확인 결과
  `data:image/svg+xml` 빈 껍데기 2건, 아마존 UI 스프라이트(`/images/S/sash/`) 11건,
  기타 아이콘 4건. 전부 UI 장식용.

**번역 대상이 되는 실제 상품 이미지는 누락 없음.**

---

## 6. 산출물

### `out_ocr_lines.csv` (25,336행) — 번역 파이프라인 투입용 핵심 파일

```
line_id, image_id, asin, source_category, image_type, text, x1, y1, x2, y2, confidence
L000001, I00002, B00U2VQZDS, Face, thumbnail, "Gently cleanses &", 1474, 1024, 2371, 1166, 0.968
L000002, I00002, B00U2VQZDS, Face, thumbnail, "removes",           1437, 1165, 1873, 1270, 1.0
```

`x1, y1, x2, y2` 는 원본 이미지 내 픽셀 좌표(좌상단, 우하단).
번역문을 원래 위치에 다시 렌더링할 때 필요하다.

### `out_images_ocr.csv` (1,522행)

기존 `out_images.csv` 에 다음 4개 컬럼을 추가한 것.
`ocr_done`, `ocr_text`(이미지 내 전체 텍스트를 읽기순으로 이어붙임),
`ocr_line_count`, `ocr_avg_confidence`

### `ocr_progress.json`

진행 상황 + 줄 단위 원본 데이터. 재실행 시 이어서 처리하는 근거 파일.
지우면 처음부터 다시 돌린다.

### `run_ocr.py.bak`

수정 전 원본 백업.

---

## 7. 다음 단계 — 문장 재조립 필요

현재 결과는 원본 이미지의 줄바꿈을 그대로 따라 **덩어리 단위로 분절**되어 있다.

```
L000001  "Gently cleanses &"
L000002  "removes"
L000003  "s up to 99%"
L000004  "of makeup, including"
L000005  "waterproof mascara"
```

이 상태로 번역하면 "부드럽게 세정하고 / 제거합니다 / 최대 99%를" 같은
비문이 나온다. 번역 전에 **좌표 기반으로 같은 문단에 속한 조각을 이어붙이는
전처리**가 필요하다. (y 간격 + x 정렬 + 글자 높이 유사도로 그룹핑)

`L000003` 의 `"s up to 99%"` 처럼 앞 글자가 잘려 들어간 케이스도 있어,
재조립 시 중복 문자 정리도 함께 봐야 한다.

---

## 8. 실행 환경 참고

- Python 3.12 (`py -3.12`)
- paddlepaddle 3.0.0 / paddleocr 3.7.0 / opencv-python 4.10.0
- 모델 캐시: `C:\paddlex_cache` (한글 경로 회피용, 반드시 ASCII 경로여야 함)
- 실행: `py -3.12 run_ocr.py`
- 중단해도 `ocr_progress.json` 기준으로 이어서 실행됨
