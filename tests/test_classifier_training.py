from types import SimpleNamespace

import joblib

from src.routing import classifier


def test_training_data_adds_current_questions_and_both_negative_sets(monkeypatch):
    """Verify stored questions join the benchmark as label 1, and chit-chat plus general knowledge form label 0."""
    stored = [{"source": "ingested/batch/quokkas.md", "question": "Where do quokkas live?",
               "answer": "On Rottnest Island.", "context": "..."}]
    monkeypatch.setattr(classifier, "get_current_questions", lambda: stored)

    data = classifier.load_training_data()

    positives = [text for text, label in data if label == 1]
    negatives = [text for text, label in data if label == 0]
    assert "Where do quokkas live?" in positives
    assert "What is 2345 * 849?" not in positives  # the benchmark's general question
    assert len(positives) == 10  # 9 benchmark questions + 1 stored
    assert set(negatives) == {text for text, _ in classifier.NON_RETRIEVAL_DATA + classifier.GENERAL_KNOWLEDGE_DATA}


def test_train_classifier_balances_classes_and_saves_the_model(tmp_path, monkeypatch):
    """Verify an 8-to-2 imbalance is trained with balanced class weights and the model lands where routing loads it."""
    vectors = {"corpus question": [1.0, 0.0], "small talk": [0.0, 1.0]}
    embedder = SimpleNamespace(embed_documents=lambda texts: [vectors[text] for text in texts])
    monkeypatch.setattr(classifier, "load_training_data", lambda: [("corpus question", 1)] * 8 + [("small talk", 0)] * 2)
    monkeypatch.setattr(classifier, "create_or_get_vectorstore", lambda: SimpleNamespace(_embedding_function=embedder))
    monkeypatch.setattr(classifier, "CLUSTERS_DIR", str(tmp_path))
    monkeypatch.setattr(classifier, "CLASSIFIER_MODEL_PATH", str(tmp_path / "retrieval_classifier.joblib"))

    classifier.train_classifier()

    model = joblib.load(tmp_path / "retrieval_classifier.joblib")
    assert model.class_weight == "balanced"
    assert list(model.predict([[1.0, 0.0], [0.0, 1.0]])) == [1, 0]
