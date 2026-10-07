import requests
from src.evaluation.evaluator import load_questions, judge_answer
from src.evaluation.eval_db import save_eval_run
from src.config import EVAL_QUESTIONS_PATH, DB_PATH, EVAL_LLM_MODEL, K_EVALUATION, ROUTING_METHOD, LIVE_EVAL_CLIENT
from src.core.utils import create_llm
from src.storage.question_store import get_current_questions
from src.storage.event_store import get_event_store
from src.logging_config import setup_logging

logger = setup_logging(__name__)


def run_live_evaluation(target_url: str, revision: str | None = None, questions_path: str = EVAL_QUESTIONS_PATH,
                        run_type: str = "live") -> tuple[int, float, bool]:
    """Run evaluation against a deployed endpoint via HTTP POST /query.

    Args:
        target_url: Base URL of the target RAG API endpoint (e.g. http://localhost:8000).
        revision: Optional git SHA or deployment release version.
        questions_path: Question file in baseline/questions.json format (default: the benchmark).
        run_type: Stored with the run: "live" for the benchmark gate, "synthetic" for generated questions.

    Returns:
        tuple: (run_id: int, precision_score: float, passed_threshold: bool)
    """
    questions = load_questions(questions_path)
    logger.info(f"Running live evaluation against '{target_url}' ({len(questions)} test questions)...")

    judge_llm = create_llm(EVAL_LLM_MODEL)
    successful_retrievals = 0
    question_results = []
    endpoint = f"{target_url.rstrip('/')}/query"

    for i, q in enumerate(questions):
        logger.info(f"[{i+1}/{len(questions)}] Live Testing: '{q['query']}'")
        try:
            response = requests.post(endpoint, json={"question": q["query"]}, headers={"X-RAG-Client": LIVE_EVAL_CLIENT},
                                     timeout=60)
            response.raise_for_status()
            answer = response.json().get("answer", "")

            is_passed = judge_answer(q["query"], q["expected_answer"], answer, judge_llm)

            question_results.append({
                "id": q.get("id"),
                "query": q["query"],
                "passed": is_passed,
                "llm_answer": answer,
            })

            if is_passed:
                logger.info("\tSUCCESS: LLM confirmed.")
                successful_retrievals += 1
            else:
                logger.info("\tFAIL: LLM denied.")

        except Exception as e:
            logger.error(f"\tERROR querying live endpoint: {e}")
            question_results.append({
                "id": q.get("id"),
                "query": q["query"],
                "passed": False,
                "llm_answer": f"ERROR: {str(e)}",
            })

    precision = (successful_retrievals / len(questions)) * 100 if questions else 0.0
    threshold = 80.0
    passed_threshold = precision >= threshold

    logger.info(f"\nLive evaluation final score: Precision@{K_EVALUATION} - {precision:.1f}%")

    run_id = save_eval_run(
        db_path=DB_PATH,
        main_model="live-endpoint",
        eval_model=EVAL_LLM_MODEL,
        routing_method=ROUTING_METHOD,
        k_retrieval=K_EVALUATION,
        precision_score=precision,
        total_questions=len(questions),
        successful_questions=successful_retrievals,
        passed_threshold=passed_threshold,
        question_results=question_results,
        run_type=run_type,
        revision=revision,
    )
    logger.info(f"Saved live evaluation metrics to DB (Run ID #{run_id})")
    record_eval_run({
        "run_type": run_type, "revision": revision, "target_url": target_url, "eval_model": EVAL_LLM_MODEL,
        "precision_score": precision, "total_questions": len(questions),
        "successful_questions": successful_retrievals, "passed_threshold": passed_threshold,
        "results": question_results,
    })
    return run_id, precision, passed_threshold


def record_eval_run(record: dict) -> None:
    """Store a run in the event store next to the configured state, so the dashboard can show it after this machine
    is gone: in the CI gates, that's the target cloud's store. Never changes the run's result."""
    try:
        get_event_store().put("eval_run", record)
        logger.info("Stored the run as an eval_run event")
    except Exception as e:
        logger.warning(f"[Events] Eval run not stored: {e}")


def synthetic_questions(sources: list[str] | None = None) -> list[dict]:
    """Stored generated questions in the baseline/questions.json format, optionally for some sources only.

    Each comes with an expected answer and the chunk it was written from, so live-eval can ask and judge them
    like the benchmark: an eval set for documents nobody wrote test questions for.
    """
    rows = [row for row in get_current_questions() if not sources or row["source"] in sources]
    return [{"id": i, "source_doc": row["source"], "query": row["question"], "expected_context": row["context"],
             "expected_answer": row["answer"], "is_adversarial": False} for i, row in enumerate(rows, 1)]
