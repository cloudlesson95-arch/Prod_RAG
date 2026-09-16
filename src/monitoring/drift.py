import numpy as np
from src.logging_config import setup_logging

logger = setup_logging(__name__)


def population_stability_index(
    expected: dict[str, int],
    actual: dict[str, int],
    epsilon: float = 1e-4,
) -> float:
    """Compute Population Stability Index (PSI) between two category-count distributions.
    
    Args:
        expected: Baseline/reference distribution as {category: count}.
        actual: Observed distribution as {category: count}.
        epsilon: Small constant added to avoid log(0) or division-by-zero.
        
    Returns:
        float: Calculated PSI value.
               PSI < 0.1 -> No significant drift.
               0.1 <= PSI < 0.25 -> Moderate drift.
               PSI >= 0.25 -> Significant drift.
    """
    all_categories = set(expected) | set(actual)

    exp_total = sum(expected.values())
    act_total = sum(actual.values())

    if exp_total == 0 or act_total == 0:
        logger.warning("Cannot compute PSI with zero-total distribution.")
        return float("inf")

    psi = 0.0
    for cat in sorted(all_categories):
        exp_prop = (expected.get(cat, 0) / exp_total) + epsilon
        act_prop = (actual.get(cat, 0) / act_total) + epsilon
        psi += (act_prop - exp_prop) * np.log(act_prop / exp_prop)

    return float(psi)
