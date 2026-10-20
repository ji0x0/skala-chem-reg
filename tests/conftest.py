"""테스트 공통 설정.

app.main이 .env를 읽으므로(load_dotenv) 개발자가 LangSmith 키를 넣어 두면 테스트 실행도 트레이스로 전송된다.
→ 테스트에서는 트레이싱을 끈다 (load_dotenv는 이미 있는 환경 변수를 덮어쓰지 않음). 네트워크 없이 결정론적으로.
"""
import os

os.environ["LANGSMITH_TRACING"] = "false"
os.environ.pop("LANGCHAIN_TRACING_V2", None)
