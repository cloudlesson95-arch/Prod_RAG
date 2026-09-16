import pytest
import math
from src.monitoring.drift import population_stability_index


def test_psi_identical_distributions():
    expected = {"cat": 100, "pydantic": 100, "fictional": 100}
    actual = {"cat": 100, "pydantic": 100, "fictional": 100}
    psi = population_stability_index(expected, actual)
    assert psi < 0.05


def test_psi_slight_drift():
    expected = {"cat": 100, "pydantic": 100, "fictional": 100}
    actual = {"cat": 120, "pydantic": 90, "fictional": 90}
    psi = population_stability_index(expected, actual)
    assert psi < 0.1  # No significant drift


def test_psi_significant_drift():
    expected = {"cat": 100, "pydantic": 100, "fictional": 100}
    actual = {"cat": 10, "pydantic": 250, "fictional": 40}
    psi = population_stability_index(expected, actual)
    assert psi >= 0.25  # Significant drift


def test_psi_missing_category_handling():
    expected = {"cat": 100, "pydantic": 100}
    actual = {"cat": 100, "pydantic": 100, "new_source": 50}
    psi = population_stability_index(expected, actual)
    assert isinstance(psi, float)
    assert not math.isnan(psi)


def test_psi_zero_total_distribution():
    expected = {"cat": 0, "pydantic": 0}
    actual = {"cat": 10, "pydantic": 10}
    psi = population_stability_index(expected, actual)
    assert math.isinf(psi)
