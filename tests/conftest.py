"""테스트 공통 설정.

app.main이 .env를 읽으므로(load_dotenv) 개발자가 LangSmith 키를 넣어 두면 테스트 실행도 트레이스로 전송된다.
→ 테스트에서는 트레이싱을 끈다 (load_dotenv는 이미 있는 환경 변수를 덮어쓰지 않음). 네트워크 없이 결정론적으로.
법제처 키(LAW_API_OC)도 비운다 — MCP 서버가 .env를 읽어 테스트 중 실제 API를 부르지 않게.
규제 DB 갱신 폴더(Step 12)는 빈 임시 폴더로 — 로컬에서 승인해 반영한 갱신이 테스트의 서버 시작에 섞이지 않게.
"""
import os
import tempfile

os.environ["LANGSMITH_TRACING"] = "false"
os.environ.pop("LANGCHAIN_TRACING_V2", None)
os.environ["LAW_API_OC"] = ""
os.environ["REG_UPDATES_DIR"] = tempfile.mkdtemp(prefix="reg-updates-")
