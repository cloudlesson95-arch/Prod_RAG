import os
import pytest
import numpy as np
from unittest.mock import patch, MagicMock

from src.routing.classifier import predict_needs_retrieval_with_confidence


def test_predict_confidence_missing_model():
    with patch("os.path.exists", return_value=False):
        with pytest.raises(FileNotFoundError, match="Classifier model not found"):
            predict_needs_retrieval_with_confidence([0.1] * 384)


def test_predict_confidence_mocked_model():
    mock_classifier = MagicMock()
    mock_classifier.predict.return_value = [1]
    mock_classifier.predict_proba.return_value = np.array([[0.15, 0.85]])

    with patch("os.path.exists", return_value=True), patch("joblib.load", return_value=mock_classifier):
        needs_retrieval, confidence = predict_needs_retrieval_with_confidence([0.1] * 384)
        assert needs_retrieval is True
        assert pytest.approx(confidence, 0.01) == 0.85
        assert 0.0 <= confidence <= 1.0
