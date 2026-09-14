import os
import sys
import json
from src.config import (
    K_EVALUATION, MAIN_LLM_MODEL, EVAL_LLM_MODEL, ROUTING_METHOD,
    ENABLE_SEMANTIC_CACHE, EVAL_QUESTIONS_PATH, DB_PATH
)
from src.core.utils import create_llm
from src.core.vectorstore import create_or_get_vectorstore
from src.core.rag_agent import setup_router, answer_question
from src.retrieval.semantic_cache import remove_cache_entry
from src.evaluation.eval_db import save_eval_run

from src.logging_config import setup_logging
logger = setup_logging(__name__)

def load_questions(filepath: str) -> list[dict]:
    """Parse JSON baseline file into a list of question dictionaries.
    
    Args:
        filepath: Path to the questions file.
        
    Returns:
        list[dict]: List of question dictionaries with 'query', 'expected_context', 
                   and 'expected_answer' keys.
    """
    questions = []
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

def run_evaluation():
    logger.info("Loading vector database")
    vectorstore = create_or_get_vectorstore()
    router = setup_router()
    answer_llm = create_llm(MAIN_LLM_MODEL)

    questions = load_questions(EVAL_QUESTIONS_PATH)
    logger.info(f"Loaded {len(questions)} test questions.\n")

    successful_retrievals = 0
    judge_llm = create_llm(EVAL_LLM_MODEL)
    question_results = []
    
    for i,q in enumerate(questions):
        logger.info(f"\n[{i+1}/{len(questions)}] Testing: '{q['query']}'")

        try:
            answer = answer_question(q['query'], router, vectorstore, answer_llm)
            logger.info(f"\tThe user asked: {q['query']}")
            logger.info(f"\tLLM answer: {answer}")            

            judge_prompt = f"""You are an impartial judge evaluating an AI search engine response against ground truth reference answers.

User Question: {q['query']}
Reference Ground Truth Answer: {q['expected_answer']}
Generated Model Answer: {answer}

Does the Generated Model Answer factually agree with the Reference Ground Truth Answer?
- Answer YES if the core facts match the reference answer.
- Answer NO if the generated answer is factually wrong, contradicts the reference answer, or says "I don't know".

Reply ONLY with "YES" or "NO". Do not explain."""

            response = judge_llm.invoke(judge_prompt)
            decision = response.content.strip().upper()
            is_passed = "YES" in decision

            question_results.append({
                "id": q.get("id"),
                "query": q["query"],
                "passed": is_passed,
                "llm_answer": answer
            })

            if is_passed:
                logger.info("\tSUCCESS: LLM confirmed.")
                successful_retrievals += 1
            else:
                logger.info("\tFAIL: LLM denied")
                logger.info(f"\tExpected to find: {q['expected_answer'][:100]}...")
                logger.info("-" * 30)
                
                if ENABLE_SEMANTIC_CACHE:
                    remove_cache_entry(q['query'])

        except Exception as e:
            logger.error(f"\tERROR: {str(e)}")
            question_results.append({
                "id": q.get("id"),
                "query": q["query"],
                "passed": False,
                "llm_answer": f"ERROR: {str(e)}"
            })

    precision = (successful_retrievals / len(questions)) * 100 if questions else 0.0
    threshold = 80.0
    passed_threshold = precision >= threshold

    logger.info(f"\nFinal score: Precision@4 - {precision:.1f}%")
    logger.info(f"({successful_retrievals} out of {len(questions)} retrieved correctly)")
    
    run_id = save_eval_run(
        db_path=DB_PATH,
        main_model=MAIN_LLM_MODEL,
        eval_model=EVAL_LLM_MODEL,
        routing_method=ROUTING_METHOD,
        k_retrieval=K_EVALUATION,
        precision_score=precision,
        total_questions=len(questions),
        successful_questions=successful_retrievals,
        passed_threshold=passed_threshold,
        question_results=question_results
    )
    logger.info(f"Saved evaluation metrics to DB (Run ID #{run_id} at '{DB_PATH}')")

    # Write evaluation summary report to a local markdown file
    summary_path = "baseline/summary.md"
    try:
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(f"## 📊 RAG Pipeline Evaluation Summary\n\n")
            f.write(f"- **Precision@4 Score:** `{precision:.1f}%`\n")
            f.write(f"- **Main Model:** `{MAIN_LLM_MODEL}`\n")
            f.write(f"- **Routing Method:** `{ROUTING_METHOD}`\n")
            f.write(f"- **Status:** `{'Passed ✅' if passed_threshold else 'Failed ❌'}`\n\n")
            
            f.write("| ID | Query | Status |\n")
            f.write("|---|---|---|\n")
            for res in question_results:
                status = "✅ PASS" if res["passed"] else "❌ FAIL"
                f.write(f"| {res.get('id', '-')} | {res['query']} | {status} |\n")
        logger.info(f"Wrote evaluation summary to '{summary_path}'.")
    except Exception as e:
        logger.warning(f"Could not write summary file: {e}")

    if not passed_threshold:
        logger.error(f"Evaluation failed! Precision {precision:.1f}% is below the {threshold}% threshold.")
        sys.exit(1)
    else:
        logger.info(f"Evaluation passed the {threshold}% threshold.")
        sys.exit(0)
