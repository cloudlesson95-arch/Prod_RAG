import os
from collections import Counter
import joblib
import numpy as np

from sklearn.linear_model import LogisticRegression
from src.config import CLASSIFIER_MODEL_PATH, CLUSTERS_DIR, EMBEDDING_LOCAL_MODEL, EVAL_QUESTIONS_PATH
from src.logging_config import setup_logging
from src.evaluation.evaluator import load_questions
from src.core.vectorstore import create_or_get_vectorstore
from src.storage.question_store import get_current_questions

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

# Questions the corpus doesn't cover, so the classifier learns "general knowledge" as well as chit-chat.
# Keep them unlike the off_corpus group in baseline/routing_probe.json (other facts and other phrasings),
# or that measurement would test the training data.
GENERAL_KNOWLEDGE_DATA = [
    ("Who discovered penicillin?", 0),
    ("When did World War II end?", 0),
    ("Who built the pyramids of Giza?", 0),
    ("Why is the sky blue?", 0),
    ("What is photosynthesis?", 0),
    ("How do vaccines work?", 0),
    ("What causes the seasons on Earth?", 0),
    ("Which countries border Switzerland?", 0),
    ("Who composed The Four Seasons?", 0),
    ("What is the plot of Hamlet?", 0),
    ("How does scoring work in tennis?", 0),
    ("How long should I boil pasta?", 0),
    ("Is 97 a prime number?", 0),
    ("Convert 100 kilometers to miles.", 0),
    ("Tell me a fun fact about the Roman Empire.", 0),
    ("Good afternoon!", 0),
    ("I'm bored, entertain me.", 0),
    ("Can you help me plan my weekend?", 0),
    ("What is the opposite of generous?", 0),
    ("How do interest rates affect mortgages?", 0),
    ("How much water should I drink per day?", 0),
    ("What is the difference between weather and climate?", 0),
    ("Translate good night into Spanish.", 0),
    ("Recommend a good science fiction novel.", 0),
    ("What does DNA stand for?", 0),
]

def load_training_data():
    """Combine retrieval examples (label 1) with non-retrieval examples (label 0).

    Label 1: the benchmark questions (without the general one) and the generated questions of every document
    still indexed in the version they were written for, so retraining after an ingest learns the new documents.
    Label 0: chit-chat and general-knowledge questions.
    """
    benchmark = [(q["query"], 1) for q in load_questions(EVAL_QUESTIONS_PATH) if q.get("source_doc") != "general"]
    stored = get_current_questions()
    generated = [(q["question"], 1) for q in stored]
    negatives = NON_RETRIEVAL_DATA + GENERAL_KNOWLEDGE_DATA

    per_source = dict(Counter(q["source"] for q in stored))
    logger.info(f"Loaded {len(benchmark)} benchmark and {len(generated)} generated questions (label=1); "
                f"generated per source: {per_source or 'none'}")
    logger.info(f"Loaded {len(negatives)} chit-chat and general-knowledge questions (label=0)")
    return benchmark + generated + negatives


def training_source_mix() -> dict[str, int]:
    """Training questions per source, with "none" for the ones that need no retrieval: the routing mix the classifier
    was built for, which the dashboard's drift check compares real traffic with. Same questions as load_training_data."""
    mix = Counter(q["source_doc"] for q in load_questions(EVAL_QUESTIONS_PATH) if q.get("source_doc") != "general")
    mix.update(q["source"] for q in get_current_questions())
    mix["none"] += len(NON_RETRIEVAL_DATA) + len(GENERAL_KNOWLEDGE_DATA)
    return dict(mix)

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
    # Balanced: generated questions soon outnumber the fixed negatives (and before any exist, the negatives
    # outnumber the benchmark), so without weights the decision would drift with the counts alone.
    classifier = LogisticRegression(class_weight="balanced", random_state=42)
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
