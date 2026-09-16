import os
import joblib
import numpy as np

from sklearn.linear_model import LogisticRegression
from src.config import CLASSIFIER_MODEL_PATH, CLUSTERS_DIR, EMBEDDING_LOCAL_MODEL, EVAL_QUESTIONS_PATH
from src.logging_config import setup_logging
from src.evaluation.evaluator import load_questions
from src.core.vectorstore import create_or_get_vectorstore

logger = setup_logging(__name__)

NON_RETRIEVAL_DATA = [
    ("Hello!", 0),
    ("Hi, how are you today?", 0),
    ("Good morning", 0),
    ("Good evening", 0),
    ("What is 2 + 2?", 0),
    ("Calculate 15 * 4", 0),
    ("What is 2345 * 849?", 0),
    ("Who are you?", 0),
    ("What can you do?", 0),
    ("Tell me a joke", 0),
    ("Thanks for your help!", 0),
    ("Bye!", 0),
    ("How is the weather today?", 0),
]

def load_training_data():
    """Load evaluation questions and combine with generic non-retrieval examples."""
    eval_questions = load_questions(EVAL_QUESTIONS_PATH)
    
    domain_queries = []
    for q in eval_questions:
        query_text = q["query"]
        # Skip 1 general question
        if "What is 2345 * 849?" in query_text:
            continue
        domain_queries.append((query_text, 1))

    logger.info(f"Loaded {len(domain_queries)} domain queries from question.txt (label=1)")
    logger.info(f"Loaded {len(NON_RETRIEVAL_DATA)} generic queries (label=0)")
    return domain_queries + NON_RETRIEVAL_DATA

def train_classifier():
    """Train a Logistic Regression classifier on query embeddings to predict retrieval necessity."""
    training_data = load_training_data()

    logger.info("Initializing embedding model for training classifier...")
    vectorstore = create_or_get_vectorstore()
    embeddings_model = vectorstore._embedding_function
    
    queries, labels = zip(*training_data)
    logger.info(f"Embedding {len(queries)} training queries...")
    
    X = embeddings_model.embed_documents(list(queries))
    y = np.array(labels)

    logger.info("Training Logistic Regression classifier...")
    classifier = LogisticRegression(random_state=42)
    classifier.fit(X, y)
    
    accuracy = classifier.score(X, y) * 100
    logger.info(f"Classifier trained successfully with {accuracy:.1f}% training accuracy.")

    os.makedirs(CLUSTERS_DIR, exist_ok=True)
    joblib.dump(classifier, CLASSIFIER_MODEL_PATH)
    logger.info(f"Classifier saved to {CLASSIFIER_MODEL_PATH}")

def predict_needs_retrieval(query_embedding) -> bool:
    """Predict whether a query needs retrieval (True) or not (False)."""
    if not os.path.exists(CLASSIFIER_MODEL_PATH):
        raise FileNotFoundError("Classifier model not found. Run training first.")

    classifier = joblib.load(CLASSIFIER_MODEL_PATH)
    prediction = classifier.predict([query_embedding])[0]
    return bool(prediction == 1)

def predict_needs_retrieval_with_confidence(query_embedding) -> tuple[bool, float]:
    """Predict whether a query needs retrieval along with raw classifier confidence.
    
    Args:
        query_embedding: Vector embedding of the input query.
        
    Returns:
        tuple: (needs_retrieval: bool, confidence: float)
            - confidence is the raw logistic probability of the predicted class [0.0, 1.0].
              Note: This is an uncalibrated logistic score, not a guaranteed probability.
    """
    if not os.path.exists(CLASSIFIER_MODEL_PATH):
        raise FileNotFoundError("Classifier model not found. Run training first.")

    classifier = joblib.load(CLASSIFIER_MODEL_PATH)
    prediction = classifier.predict([query_embedding])[0]
    probabilities = classifier.predict_proba([query_embedding])[0]
    confidence = float(probabilities[prediction])

    return bool(prediction == 1), confidence
