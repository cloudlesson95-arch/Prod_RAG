import argparse
import os
import shutil
from dotenv import load_dotenv
from src.logging_config import setup_logging
from src.config import MAIN_LLM_MODEL, CHROMA_PERSIST_DIR
 
load_dotenv()
logger = setup_logging(__name__)

def main():
    parser = argparse.ArgumentParser(description="RAG System")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Index command
    index_parser = subparsers.add_parser("index", help="Build/update document index")
    index_parser.add_argument("--rebuild", action="store_true", help="Force rebuild of index")
    
    # Query command  
    query_parser = subparsers.add_parser("query", help="Query the RAG system")
    query_parser.add_argument("question", help="Question to ask")
    
    # Evaluate command
    eval_parser = subparsers.add_parser("evaluate", help="Run evaluation tests")

    # API commands
    serve_parser = subparsers.add_parser("serve", help="Run the FastAPI REST API server")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")

    history_parser = subparsers.add_parser("history", help="View past evaluation runs")
    history_parser.add_argument("--limit", type=int, default=10, help="Number of past runs to display")
    
    args = parser.parse_args() 

    if args.command == "index":
        from src.core.vectorstore import sync_incremental_index
        from src.routing.clustering import train_clustering
        from src.routing.classifier import train_classifier
        
        logger.info(f"Running document index sync (rebuild={args.rebuild})...")
        vectorstore, changed_sources = sync_incremental_index(force_rebuild=args.rebuild)
        
        logger.info("Updating classical ML routing models...")
        train_clustering(changed_sources=changed_sources, force_rebuild=args.rebuild)
        train_classifier()
        logger.info("Index sync and ML model update completed.")
        
    elif args.command == "query":
        from src.core.vectorstore import create_or_get_vectorstore
        from src.core.rag_agent import setup_router, answer_question
        from src.core.utils import create_llm
        router = setup_router()
        vectorstore = create_or_get_vectorstore()
        answer_llm = create_llm(MAIN_LLM_MODEL)
        answer = answer_question(args.question, router, vectorstore, answer_llm)
        print(answer)
            
    elif args.command == "evaluate":
        from src.evaluation.evaluator import run_evaluation
        run_evaluation()

    elif args.command == "serve":
        import uvicorn
        logger.info(f"Starting API server on {args.host}:{args.port}")
        uvicorn.run("src.core.api:app", host=args.host, port=args.port, reload=False)

    elif args.command == "history":
        from src.evaluation.eval_db import get_eval_history
        from src.config import DB_PATH
        history = get_eval_history(DB_PATH, limit=args.limit)
        if not history:
            print("No evaluation runs found in history.")
        else:
            print(f"\n--- Last {len(history)} Evaluation Runs ---")
            print(f"{'ID':<4} {'Timestamp':<25} {'Model':<20} {'Routing':<10} {'Score':<8} {'Passed':<6}")
            print("-" * 78)
            for run in history:
                ts = run['timestamp'][:19].replace('T', ' ')
                score = f"{run['precision_score']:.1f}%"
                passed = "YES" if run['passed_threshold'] else "NO"
                print(f"{run['id']:<4} {ts:<25} {run['main_model']:<20} {run['routing_method']:<10} {score:<8} {passed:<6}")    
            
    else:
        parser.print_help()

if __name__ == "__main__":
    main()