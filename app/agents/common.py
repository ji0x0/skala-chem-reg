"""노드 공통 보조 함수 — graph.py(v2)·understand.py(Step 9)·baseline.py가 함께 쓴다 (순환 import를 피하려고 분리)."""
from __future__ import annotations

import logging
import re
import time
from functools import wraps

from langgraph.config import get_stream_writer

from app.domain.cas import find_cas_numbers
from app.domain.mentions import KO_AMBIGUOUS, find_substance_mentions

from .deps import AgentDeps
from .state import AgentState

log = logging.getLogger("app.agents.graph")

NODE_LABELS = {"route": "질문 분류", "understand": "질문 이해·범위 확인", "inform": "규제 설명·목록 조회",
               "chat_answer": "답변", "lookup": "규제 조회·판정",
               "plan": "브리핑 계획", "gate": "계획 검증", "review": "수집 결과 확인",
               "summarize": "문서 요약·근거 번역", "impact": "제품 영향 판정", "write": "브리핑 작성",
               "guard": "사실·근거 검사", "validate": "품질 검토",
               "finalize": "최종 정리"}


def node(name: str):
    """노드 시작을 진행 이벤트로 알리고, 소요 시간을 로그로 남긴다."""
    def deco(fn):
        @wraps(fn)
        async def wrapper(state, deps: AgentDeps):
            get_stream_writer()({"type": "node_start", "node": name, "label": NODE_LABELS.get(name, name)})
            started = time.perf_counter()
            result = await fn(state, deps)
            log.info("노드 완료", extra={"node": name,
                                       "latency_ms": int((time.perf_counter() - started) * 1000)})
            return result
        return wrapper
    return deco


def history_text(state: AgentState, turns: int = 6) -> str:
    return "\n".join(f"{m['role']}: {m['content'][:300]}" for m in state.get("history", [])[-turns:])


def token_writer(attempt: int = 1):
    writer = get_stream_writer()
    return lambda piece: writer({"type": "token", "delta": piece, "attempt": attempt})


def resolve_substances(question: str, deps: AgentDeps) -> list[str]:
    """질문 속 물질 → CAS. ① CAS 그대로 ② 영문 이름·약어 ③ 한글 이름 (모두 코드 규칙)."""
    found = find_cas_numbers(question)
    found += [m["cas"] for m in find_substance_mentions(question, deps.substances)]
    for s in deps.substances:
        core = re.sub(r"\s*\(.*?\)\s*", "", s.get("name_ko") or "").strip()
        if s["cas"] not in KO_AMBIGUOUS and len(core) >= 2 and core in question:
            found.append(s["cas"])
    # 일상어와 겹치는 한 글자 이름(납 ↔ 납품·납기)은 질문에서 조사와 함께 단독으로 쓰였을 때만 인정
    if re.search(r"(?<![가-힣])납(?=이|은|는|을|를|과|와|의|도|만|\s|$|\?)", question):
        found.append("7439-92-1")
    return list(dict.fromkeys(found))
