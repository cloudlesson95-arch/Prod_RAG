import os
import joblib
import numpy as np
from sklearn.manifold import TSNE
import matplotlib.pyplot as plt

from src.config import CLUSTERS_DIR, GENERATE_VISUALIZATION
from src.core.vectorstore import create_or_get_vectorstore
from src.logging_config import setup_logging

logger = setup_logging(__name__)
CENTROIDS_PATH = os.path.join(CLUSTERS_DIR, "source_centroids.joblib")

def train_clustering(changed_sources: set = None, force_rebuild: bool = False):
    """Calculate and update the mean embedding (centroid) for document sources.
    
    Args:
        changed_sources: Set of filenames that were added, modified, or deleted.
        force_rebuild: If True, recompute centroids for all documents from scratch.
    """
    os.makedirs(CLUSTERS_DIR, exist_ok=True)

    # No changes -> skip
    if changed_sources is not None and len(changed_sources) == 0 and os.path.exists(CENTROIDS_PATH) and not force_rebuild:
        logger.info("No document changes detected. Source centroids are up to date.")
        return

    logger.info("Updating document source centroids...")
    vectorstore = create_or_get_vectorstore()
    collection = vectorstore._collection

    # Full rebuild for all sources
    if force_rebuild or not os.path.exists(CENTROIDS_PATH) or changed_sources is None:
        data = collection.get(include=["embeddings", "metadatas"])
        embeddings = data.get("embeddings")
        metadatas = data.get("metadatas")

        if embeddings is None or len(embeddings) == 0:
            logger.warning("No embeddings found in vectorstore. Cannot compute centroids.")
            return

        source_embeddings = {}
        for i, meta in enumerate(metadatas):
            source = meta.get("source", "unknown")
            if source not in source_embeddings:
                source_embeddings[source] = []
            source_embeddings[source].append(embeddings[i])

        centroids = {}
        for source, emb_list in source_embeddings.items():
            centroids[source] = np.mean(np.array(emb_list), axis=0)
            logger.info(f"Source '{source}': Centroid computed from {len(emb_list)} chunks")

        joblib.dump(centroids, CENTROIDS_PATH)
        logger.info(f"Saved {len(centroids)} source centroids to {CENTROIDS_PATH}")

        if GENERATE_VISUALIZATION:
            sources = [m.get("source", "unknown") for m in metadatas]
            visualize_clusters(np.array(embeddings), sources)
        return

    # Incremental update for changed sources only
    try:
        centroids = joblib.load(CENTROIDS_PATH)
    except Exception:
        centroids = {}

    for source in changed_sources:
        data = collection.get(where={"source": source}, include=["embeddings"])
        embeddings = data.get("embeddings")
        if embeddings is not None and len(embeddings) > 0:
            centroids[source] = np.mean(np.array(embeddings), axis=0)
            logger.info(f"Source '{source}': Updated centroid from {len(embeddings)} chunks")
        else:
            if source in centroids:
                del centroids[source]
                logger.info(f"Source '{source}': Removed centroid (document deleted)")

    joblib.dump(centroids, CENTROIDS_PATH)
    logger.info(f"Updated source centroids saved successfully. Total active sources: {len(centroids)}")
    
    if GENERATE_VISUALIZATION:
        data = collection.get(include=["embeddings", "metadatas"])
        all_embeddings = data.get("embeddings")
        all_metadatas = data.get("metadatas")
        if all_embeddings is not None and len(all_embeddings) > 0:
            sources = [m.get("source", "unknown") for m in all_metadatas]
            visualize_clusters(np.array(all_embeddings), sources)

def visualize_clusters(X, sources):
    """Generate a 2D visualization using t-SNE."""
    logger.info("Generating cluster visualization... (this might take a few seconds)")

    # t-SNE reduces 384-dimensional embeddings down to 2 dimensions for plotting
    tsne = TSNE(n_components=2, random_state=42)
    X_2d = tsne.fit_transform(X)

    # Unique color IDs for plotting
    unique_sources = list(set(sources))
    source_to_id = {src: i for i, src in enumerate(unique_sources)}
    color_ids = [source_to_id[src] for src in sources]

    plt.figure(figsize=(10, 8))
    scatter = plt.scatter(X_2d[:, 0], X_2d[:, 1], c=color_ids, cmap='tab10', alpha=0.6)

    # Add legend
    handles, _ = scatter.legend_elements()
    plt.legend(handles, unique_sources, title="Sources")
    plt.title("Document Embeddings by Source")

    save_path = os.path.join(CLUSTERS_DIR, "cluster_visualization.png")
    plt.savefig(save_path)
    plt.close()
    
    logger.info(f"Visualization saved as {save_path}")

def predict_source(query_embedding):
    """Predict the source for a query by finding the nearest document centroid."""
    if not os.path.exists(CENTROIDS_PATH):
        raise FileNotFoundError("Centroids model not found. Train it first.")

    centroids = joblib.load(CENTROIDS_PATH)
    query_vec = np.array(query_embedding)
    
    # Find the source with minimum Euclidean distance to the query vector
    best_source = None
    min_dist = float("inf")
    
    for source, centroid in centroids.items():
        dist = np.linalg.norm(query_vec - centroid)
        if dist < min_dist:
            min_dist = dist
            best_source = source

    return best_source if best_source else "none"
