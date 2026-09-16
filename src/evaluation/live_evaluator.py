import requests
from src.evaluation.evaluator import load_questions, judge_answer
from src.evaluation.eval_db import save_eval_run
from src.config import EVAL_QUESTIONS_PATH, DB_PATH, EVAL_LLM_MODEL, K_EVALUATION, ROUTING_METHOD
from src.core.utils import create_llm
from src.logging_config import setup_logging

logger = setup_logging(__name__)


def run_live_evaluation(target_url: str, revision: str | None = None) -> tuple[int, float, bool]:
    """Run evaluation against a deployed endpoint via HTTP POST /query.
    
    Args:
        target_url: Base URL of the target RAG API endpoint (e.g. http://localhost:8000).
        revision: Optional git SHA or deployment release version.
        
    Returns:
        tuple: (run_id: int, precision_score: float, passed_threshold: bool)
    """
    questions = load_questions(EVAL_QUESTIONS_PATH)
    logger.info(f"Running live evaluation against '{target_url}' ({len(questions)} test questions)...")

    judge_llm = create_llm(EVAL_LLM_MODEL)
    successful_retrievals = 0
    question_results = []
    endpoint = f"{target_url.rstrip('/')}/query"

    for i, q in enumerate(questions):
        logger.info(f"[{i+1}/{len(questions)}] Live Testing: '{q['query']}'")
        try:
            response = requests.post(endpoint, json={"question": q["query"]}, timeout=60)
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
        run_type="live",
        revision=revision,
    )
    logger.info(f"Saved live evaluation metrics to DB (Run ID #{run_id})")
    return run_id, precision, passed_threshold
