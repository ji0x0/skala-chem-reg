"""Before(LLM 단독) vs After(v2) 평가 — 같은 질문·같은 입력(관보 스냅샷)으로 비교한다.

    uv run python scripts/run_eval.py                          # .env의 LLM (fake면 파이프라인 동작 확인용)
    LLM_BACKEND=ollama uv run python scripts/run_eval.py --judge
    uv run python scripts/run_eval.py --ids B1 B2 --pipelines v2
    uv run python scripts/run_eval.py --judge --langsmith      # LangSmith Dataset + evaluate() 실험도 기록
    uv run python scripts/run_eval.py --langsmith --skip-local --ids B1 B5 L1 L4   # LangSmith 실험만 (일부 문항)

- 관보는 FEED_MODE=snapshot으로 고정 (실시간 관보는 날마다 달라 재현이 안 됨)
- 제품은 products.csv로 새로 채운 임시 DB (화면에서 추가한 제품이 섞이지 않게)
- Before는 briefing 경로만 다르므로 briefing 질문(B*)만 비교. lookup·chat은 v2 회귀 확인
- 결과: docs/experiments/<날짜>-<LLM>.md / .json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["FEED_MODE"] = "snapshot"            # MCP 서버 모듈을 불러오기 전에 설정해야 반영된다

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
os.environ["FEED_MODE"] = "snapshot"            # .env의 FEED_MODE=live가 덮어쓰지 않게 다시

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from app.agents.baseline import build_baseline_graph  # noqa: E402
from app.agents.deps import AgentDeps  # noqa: E402
from app.agents.graph import build_graph  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.tracing import langsmith_enabled, project_name  # noqa: E402
from app.eval.metrics import score_answer  # noqa: E402
from app.eval.runner import QUESTIONS_PATH, load_corpus, load_questions, run_question  # noqa: E402
from app.llm.langchain_llm import build_llm  # noqa: E402
from app.repositories.product_db import ProductDB  # noqa: E402
from app.repositories.reg_db import RegDB  # noqa: E402
from app.tools.provider import InMemoryToolProvider  # noqa: E402

OUT_DIR = ROOT / "docs" / "experiments"
DATASET = "chem-reg-eval"


# ── 준비 ────────────────────────────────────────────────────────────────────
async def setup(tmp: Path):
    get_settings.cache_clear()
    settings = get_settings().model_copy(update={"app_db_path": tmp / "app.db"})
    products = ProductDB(settings.app_db_path)
    products.seed_if_empty(settings.products_path)
    from mcp_servers import product_server, reg_db_server, reg_feed_server
    regdb = RegDB(settings.reg_db_path, products)
    for module in (product_server, reg_db_server, reg_feed_server):
        module.db = regdb                                   # MCP 서버도 임시 제품 DB를 보게
    tools = InMemoryToolProvider()
    await tools.start()
    deps = AgentDeps(settings, build_llm(settings), tools)
    await deps.load_catalog()
    graphs = {"baseline": build_baseline_graph(deps, checkpointer=InMemorySaver()),
              "v2": build_graph(deps, checkpointer=InMemorySaver())}
    return settings, deps, tools, graphs


def reference_text(item: dict, label_basis: dict) -> str:
    """LLM-as-Judge에게 Before·After 똑같이 주는 참조 자료 (정답표 + 라벨 근거)."""
    exp = item["expect"]
    lines = [f"- {k}: {v}" for k, v in label_basis.items()]
    lines.append(f"- 정답 영향 제품: {', '.join(exp.get('impacted_products', [])) or '없음'}")
    if exp.get("required_dates"):
        lines.append(f"- 반드시 맞아야 하는 날짜: {', '.join(exp['required_dates'])}")
    if item.get("note"):
        lines.append(f"- 참고: {item['note']}")
    return "\n".join(lines)


async def judge(deps, item: dict, answer: str, label_basis: dict) -> dict:
    """LLM-as-Judge (R43 두 번째 채점기). 실패하면 빈 값 — 코드 점수는 그대로 남는다."""
    try:
        j, _ = await deps.llm.judge(item["question"], answer or "(빈 답변)",
                                    reference_text(item, label_basis), "(평가 모드 — 코드 검사 결과는 주지 않음)")
        return {"relevance": j.relevance, "completeness": j.completeness, "faithfulness": j.faithfulness,
                "clarity": j.clarity, "acceptable": j.is_acceptable}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}"}


# ── 실행 ────────────────────────────────────────────────────────────────────
async def run_pipeline(name, graph, items, corpus, deps, use_judge, label_basis) -> list[dict]:
    rows = []
    for item in items:
        out = await run_question(graph, item["question"], pipeline=name, qid=item["id"])
        route = out["route"] if name == "v2" else None          # Before는 라우팅을 비교하지 않음
        score = score_answer(item, out["answer"], out["citations"], route, corpus).to_dict()
        if use_judge:
            score["judge"] = await judge(deps, item, out["answer"], label_basis)
        row = {**score, **{k: out[k] for k in ("latency_s", "tokens", "usd", "asked_approval", "error")},
               "answer": out["answer"]}
        rows.append(row)
        fp = row["products"]["false_positives"]
        print(f"  [{name}] {item['id']} {row['latency_s']:>6}s 제품P/R {row['products']['precision']}/"
              f"{row['products']['recall']}{' 오탐 ' + ','.join(fp) if fp else ''} · 날짜 {row['dates']} · "
              f"지어낸 CAS·날짜 {len(row['invented']['cas']) + len(row['invented']['dates'])} · 근거 "
              f"{row['citations']['verified']}/{row['citations']['count']}"
              + (f" · Judge {row['judge'].get('faithfulness')}" if use_judge else "")
              + (f" · 오류 {row['error']}" if row["error"] else ""), flush=True)
    return rows


def summarize(rows: list[dict]) -> dict:
    if not rows:
        return {}
    avg = lambda xs: round(mean(xs), 3) if xs else None          # noqa: E731
    judged = [r["judge"] for r in rows if r.get("judge") and "error" not in r["judge"]]
    routed = [r["route_ok"] for r in rows if r["route_ok"] is not None]
    return {
        "n": len(rows),
        "route_acc": avg([float(x) for x in routed]),
        "product_precision": avg([r["products"]["precision"] for r in rows]),
        "product_recall": avg([r["products"]["recall"] for r in rows]),
        "false_positive_products": sum(len(r["products"]["false_positives"]) for r in rows),
        "date_recall": avg([r["dates"] for r in rows]),
        "invented_cas": sum(len(r["invented"]["cas"]) for r in rows),
        "invented_dates": sum(len(r["invented"]["dates"]) for r in rows),
        "keyword": avg([r["keyword"] for r in rows]),
        "forbidden_hits": sum(len(r["forbidden"]) for r in rows),
        "citations_avg": avg([r["citations"]["count"] for r in rows]),
        "citations_verified": sum(r["citations"]["verified"] for r in rows),
        "citations_total": sum(r["citations"]["count"] for r in rows),
        "cite_ok_rate": avg([float(r["cite_ok"]) for r in rows]),
        "judge_faithfulness": avg([j["faithfulness"] for j in judged]),
        "judge_completeness": avg([j["completeness"] for j in judged]),
        "judge_acceptable": avg([float(j["acceptable"]) for j in judged]),
        "latency_s": avg([r["latency_s"] for r in rows]),
        "tokens": avg([r["tokens"] for r in rows]),
        "usd": avg([r["usd"] for r in rows]),
        "errors": sum(1 for r in rows if r["error"]),
    }


# ── 보고서 ──────────────────────────────────────────────────────────────────
METRICS = [("product_precision", "영향 제품 정밀도 (↑)"), ("product_recall", "영향 제품 재현율 (↑)"),
           ("false_positive_products", "무관한 제품 지목 수 (↓)"), ("date_recall", "핵심 날짜 재현율 (↑)"),
           ("invented_cas", "지어낸 CAS (↓)"), ("invented_dates", "지어낸 날짜 (↓)"),
           ("keyword", "키워드 점수 (↑)"), ("citations_avg", "답변당 근거 수"),
           ("cite_ok_rate", "근거 요건 충족률 (↑)"), ("judge_faithfulness", "Judge 근거 충실성 1~5 (↑)"),
           ("judge_completeness", "Judge 완전성 1~5 (↑)"), ("judge_acceptable", "Judge 합격률 (↑)"),
           ("latency_s", "평균 시간 (초)"), ("tokens", "평균 토큰"), ("errors", "실행 오류")]


def fmt(v):
    if v is None:
        return "—"
    if isinstance(v, int) or (isinstance(v, float) and v >= 100):     # 토큰 등 큰 값은 정수로
        return f"{round(v):,}"
    return f"{v:g}"


def write_report(meta: dict, results: dict[str, list[dict]], out_dir: Path = OUT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now():%Y-%m-%d-%H%M}-{meta['llm']}"
    brief = {p: summarize([r for r in rows if r["category"] == "briefing"]) for p, rows in results.items()}
    v2_all = summarize(results.get("v2", []))
    lines = [f"# 평가 결과 — {meta['llm']} ({meta['started']})", "",
             f"- 질문 세트: `{QUESTIONS_PATH.relative_to(ROOT)}` · 관보 입력: 스냅샷 고정 · LLM-as-Judge: {meta['judge']}",
             f"- 비교 범위: briefing 질문 {brief.get('v2', {}).get('n', 0)}개 (Before는 briefing 경로만 다름)", "",
             "## Before(LLM 단독) vs After(v2) — briefing", "",
             "| 지표 | Before | After |", "| --- | --- | --- |"]
    for key, label in METRICS:
        lines.append(f"| {label} | {fmt(brief.get('baseline', {}).get(key))} | {fmt(brief.get('v2', {}).get(key))} |")
    lines += ["", "## v2 전체 회귀 (briefing + lookup + chat)", "",
              f"라우팅 정확도 {fmt(v2_all.get('route_acc'))} · 영향 제품 정밀도 {fmt(v2_all.get('product_precision'))} · "
              f"재현율 {fmt(v2_all.get('product_recall'))} · 금지 표현 {fmt(v2_all.get('forbidden_hits'))} · "
              f"키워드 {fmt(v2_all.get('keyword'))} · 오류 {fmt(v2_all.get('errors'))}", "",
              "## 문항별", "", "| 파이프라인 | ID | 제품 P/R | 오탐 | 날짜 | 지어낸 CAS·날짜 | 근거(검증/전체) | 키워드 | Judge 충실성 | 시간 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for p, rows in results.items():
        for r in rows:
            inv = r["invented"]["cas"] + r["invented"]["dates"]
            lines.append(f"| {p} | {r['id']} | {r['products']['precision']}/{r['products']['recall']} | "
                         f"{', '.join(r['products']['false_positives']) or '—'} | {r['dates']} | {', '.join(inv) or '—'} | "
                         f"{r['citations']['verified']}/{r['citations']['count']} | {r['keyword']} | "
                         f"{r.get('judge', {}).get('faithfulness', '—')} | {r['latency_s']}s |")
    lines += ["", "## 채점 방법과 한계", "",
              "- 코드 채점기(`app/eval/metrics.py`): 답변 텍스트만 보고 Before·After를 같은 함수로 채점",
              "- 영향 제품 = 제품 ID가 나온 줄 중 '영향 없음·해당 없음' 같은 부정 표현이 없는 줄. 문장 구조에 따라 틀릴 수 있음",
              "- 지어낸 사실 = 답변의 CAS·날짜 중 관보 본문·규제 DB·제품 배합 어디에도 없는 것 (오늘 날짜는 허용)",
              "- 키워드 점수는 표현만 본다 → 맞는 단어를 틀린 맥락에 써도 점수를 받는다. LLM-as-Judge와 함께 본다",
              "- LLM-as-Judge는 Before·After에 같은 참조 자료(라벨 근거·정답표)를 준다. 같은 모델이 쓰고 채점하면 관대할 수 있다"]
    md = out_dir / f"{stem}.md"
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / f"{stem}.json").write_text(json.dumps({"meta": meta, "summary": {"briefing": brief, "v2_all": v2_all},
                                                     "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    return md


# ── LangSmith Dataset + evaluate() (R42) ────────────────────────────────────
async def langsmith_experiment(items, graphs, corpus, llm_name: str) -> list[str]:
    """회귀 질문을 Dataset으로 올리고, 파이프라인마다 evaluate() 실험을 남긴다. 실험 URL 목록을 돌려준다."""
    from langsmith import Client, aevaluate

    client = Client()
    if client.has_dataset(dataset_name=DATASET):
        dataset = client.read_dataset(dataset_name=DATASET)
    else:
        dataset = client.create_dataset(DATASET, description="국내외 화학물질 규제 브리핑 회귀 질문 (정답: 영향 제품·날짜·키워드)")
    existing = {e.metadata.get("id") for e in client.list_examples(dataset_id=dataset.id)}
    all_items = load_questions()                    # Dataset에는 항상 전체 문항 (실험은 고른 문항만)
    new = [q for q in all_items if q["id"] not in existing]
    if new:
        client.create_examples(dataset_id=dataset.id,
                               inputs=[{"question": q["question"]} for q in new],
                               outputs=[q["expect"] for q in new],
                               metadata=[{"id": q["id"], "category": q["category"]} for q in new])
    by_question = {q["question"]: q for q in all_items}

    def code_evaluator(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
        item = by_question[inputs["question"]]
        s = score_answer(item, outputs["answer"], outputs["citations"], outputs.get("route"), corpus)
        return {"results": [
            {"key": "product_precision", "score": s.products["precision"]},
            {"key": "product_recall", "score": s.products["recall"]},
            {"key": "date_recall", "score": s.dates},
            {"key": "invented_facts", "score": len(s.invented["cas"]) + len(s.invented["dates"])},
            {"key": "keyword", "score": s.keyword},
            {"key": "cite_ok", "score": float(s.cite_ok)},
        ]}

    urls = []
    for name, graph in graphs.items():
        ids = {q["id"] for q in items if name == "v2" or q["category"] == "briefing"}
        examples = [e for e in client.list_examples(dataset_id=dataset.id) if e.metadata.get("id") in ids]

        async def target(inputs: dict, _graph=graph, _name=name) -> dict:
            qid = by_question[inputs["question"]]["id"]
            out = await run_question(_graph, inputs["question"], pipeline=_name, qid=qid)
            print(f"  [LangSmith {_name}] {qid} {out['latency_s']}s" + (f" 오류 {out['error']}" if out["error"] else ""),
                  flush=True)                       # aevaluate는 문항별 진행을 출력하지 않으므로 직접
            return {k: out[k] for k in ("answer", "citations", "route")}

        # 같은 이벤트 루프에서 실행 (메모리 MCP 연결이 이 루프에 묶여 있음)
        result = await aevaluate(target, data=examples, evaluators=[code_evaluator],
                                 experiment_prefix=f"{name}-{llm_name}", max_concurrency=1,
                                 metadata={"pipeline": name, "llm": llm_name})
        urls.append(getattr(result, "url", None) or f"{name}: LangSmith 프로젝트 {project_name()}의 Experiments 탭")
    return urls


# ── 진입점 ──────────────────────────────────────────────────────────────────
async def main(args) -> Path:
    label_basis = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))["label_basis"]
    items = load_questions(args.ids)
    with tempfile.TemporaryDirectory() as tmp:
        settings, deps, tools, graphs = await setup(Path(tmp))
        corpus = load_corpus(settings)
        llm = deps.llm.quality_name if settings.llm_backend != "fake" else "fake"   # 예: ollama:qwen3:8b
        meta = {"llm": llm.replace(":", "-").replace("/", "-"), "started": f"{datetime.now():%Y-%m-%d %H:%M}",
                "judge": "on" if args.judge else "off", "questions": [q["id"] for q in items]}
        print(f"평가 시작 — LLM {llm} · 질문 {len(items)}개 · 관보 스냅샷 고정", flush=True)
        results, report = {}, None
        try:
            if not args.skip_local:
                for name in args.pipelines:
                    subset = [q for q in items if name == "v2" or q["category"] == "briefing"]
                    results[name] = await run_pipeline(name, graphs[name], subset, corpus, deps, args.judge, label_basis)
                report = write_report(meta, results, args.out)
                print(f"\n보고서: {report}")
            if args.langsmith:
                if not langsmith_enabled():
                    print("LangSmith 건너뜀 — .env에 LANGSMITH_TRACING=true, LANGSMITH_API_KEY 설정 필요")
                else:
                    urls = await langsmith_experiment(items, {n: graphs[n] for n in args.pipelines}, corpus, meta["llm"])
                    print("LangSmith 실험:", *urls, sep="\n  ")
        finally:
            await tools.stop()
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pipelines", nargs="+", default=["baseline", "v2"], choices=["baseline", "v2"])
    parser.add_argument("--ids", nargs="+", help="질문 ID만 골라 실행 (예: B1 L1)")
    parser.add_argument("--judge", action="store_true", help="LLM-as-Judge 채점도 실행 (LLM 호출 추가)")
    parser.add_argument("--langsmith", action="store_true", help="LangSmith Dataset + evaluate() 실험 기록")
    parser.add_argument("--skip-local", action="store_true", help="로컬 보고서 없이 LangSmith 실험만")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="보고서 폴더 (기본 docs/experiments)")
    asyncio.run(main(parser.parse_args()))
