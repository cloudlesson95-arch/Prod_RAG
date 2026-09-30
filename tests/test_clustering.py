import numpy as np

from src.routing import clustering


def test_visualize_clusters_handles_tiny_corpus(tmp_path, monkeypatch):
    """Verify tiny corpora get a chart (or a clean skip) instead of failing indexing."""
    monkeypatch.setattr(clustering, "CLUSTERS_DIR", str(tmp_path))
    X = np.random.default_rng(0).random((2, 8))

    clustering.visualize_clusters(X, ["a.txt", "b.txt"])
    assert (tmp_path / "cluster_visualization.png").exists()

    clustering.visualize_clusters(X[:1], ["a.txt"])  # skipped, must not raise
