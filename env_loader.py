# -*- coding: utf-8 -*-
"""
env_loader.py
-------------
API 토큰을 .env 파일에서 읽어오는 담당 파일.

토큰을 코드에 직접 적어두면 git 에 올리는 순간 누구나 볼 수 있다.
그래서 토큰은 .env 에만 적어두고(이 파일은 .gitignore 로 git 에서 제외),
코드는 여기를 통해 꺼내 쓴다.

쓰는 법:
    from env_loader import load_token
    MY_TOKEN = load_token()

.env 파일은 이 폴더에 두고, 아래처럼 한 줄 적으면 된다:
    DECODO_TOKEN=발급받은_토큰
(양식은 .env.example 참고. 복사해서 .env 로 이름만 바꾸면 된다.)
"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
ENV_PATH = HERE / ".env"
DEFAULT_KEY = "DECODO_TOKEN"


def load_token(key_name=DEFAULT_KEY):
    """.env 에서 key_name 값을 찾아 돌려준다. 없으면 안내 후 종료."""
    if not ENV_PATH.exists():
        sys.exit(
            f"\n[중단] {ENV_PATH} 파일이 없습니다.\n"
            f"       .env.example 을 복사해 .env 로 이름을 바꾸고,\n"
            f"       {key_name} 뒤에 발급받은 토큰을 붙여넣으세요.\n"
        )

    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key_name:
            value = value.strip().strip('"').strip("'")
            if value:
                return value

    sys.exit(
        f"\n[중단] .env 에 {key_name} 값이 비어 있습니다.\n"
        f"       {key_name}= 뒤에 발급받은 토큰을 붙여넣고 저장하세요.\n"
    )
