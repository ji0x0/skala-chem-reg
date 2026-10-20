# Step 0 — 프로젝트 골격

## 목표
코드를 넣을 뼈대와 설정·로그 체계를 만든다. 아직 기능은 없다.

## 만드는 파일

```
skala-ai_service/
├── pyproject.toml        프로젝트 정보, 의존성 (uv add가 채움)
├── uv.lock               설치된 정확한 버전 (자동 생성)
├── .python-version       Python 3.11 고정 (자동 생성)
├── .env.example          환경변수 템플릿 (.env는 Git 제외)
├── app/
│   ├── __init__.py
│   └── core/
│       ├── __init__.py
│       ├── config.py     Settings — 환경변수를 읽어 검증
│       └── logging.py    JSON 한 줄 로그
└── tests/
    ├── __init__.py
    └── test_config.py
```

## 따라 하기

> 저장소를 처음 받아 직접 만들 때 실행하는 명령이다. 이미 `.venv`와 `uv.lock`이 있으면 건너뛰고 아래 "확인"으로 간다. (이미 받은 저장소라면 `uv sync` 한 번이면 같은 환경이 만들어진다.)

```bash
uv venv --python 3.11
```

```bash
uv python pin 3.11
```

```bash
uv add pydantic pydantic-settings python-dotenv
```

```bash
uv add --dev pytest
```

```bash
cp .env.example .env
```

의존성은 한꺼번에 넣지 않고 **단계마다 필요한 것만** `uv add`로 추가한다. 어떤 단계에서 무엇이 왜 들어왔는지 `pyproject.toml` 변경 이력으로 보인다.

## 핵심 코드

**`Settings` (config.py)** — 필드 이름과 같은 환경변수를 자동으로 읽는다. 우선순위: 실제 환경변수 → `.env` → 코드 기본값.

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
```

`Literal`이라 오타가 있으면 시작할 때 바로 실패한다. 서비스는 `get_settings()`(한 번만 읽고 재사용)를, 테스트는 `Settings(...)`를 직접 만들어 쓴다.

**`JsonFormatter` (logging.py)** — 로그 한 줄을 JSON으로 만든다. `thread_id`, `run_id`, `node`, `latency_ms` 같은 필드 이름을 미리 약속해 두면 서버 로그와 LangSmith 트레이스를 같은 키로 찾을 수 있다.

## 확인

아래 4개를 순서대로 실행한다. **3번은 일부러 실패시키는 명령**이다.

1) 설정 읽기

```bash
uv run python -c "from app.core.config import get_settings; print(get_settings())"
```

```
log_level='INFO'
```

2) JSON 로그 한 줄 출력

```bash
uv run python -c "import logging; from app.core.logging import setup_logging; setup_logging(); logging.getLogger('app.check').info('설정 로드 완료', extra={'event': 'startup'})"
```

```
{"ts": "2026-10-20T05:03:19.790+00:00", "level": "INFO", "logger": "app.check", "msg": "설정 로드 완료", "event": "startup"}
```

3) ⚠️ 의도된 실패 — 로그 수준에 오타(`INFOO`)를 넣고 실행한다. **`ValidationError`가 나오면 성공**이다 (잘못된 설정을 시작 단계에서 막는지 확인). 에러 없이 끝나면 검증이 동작하지 않는 것이다.

```bash
LOG_LEVEL=INFOO uv run python -c "from app.core.config import Settings; Settings()"
```

```
log_level
  Input should be 'DEBUG', 'INFO', 'WARNING' or 'ERROR' [type=literal_error, input_value='INFOO', input_type=str]
```

4) 테스트

```bash
uv run pytest -q
```

```
4 passed
```

## 다음 단계
Step 1에서 `DATA_DIR`(`data/`)에 가상 공정 데이터를 만든다.
