"""Online incremental speaker clustering for unknown speakers.

Groups unregistered speakers into clusters ("話者A", "話者B", etc.)
using cosine similarity on WeSpeaker embeddings. No additional GPU memory
is needed — all operations are numpy dot products on CPU.
"""

from __future__ import annotations

import logging

import numpy as np
import scipy.linalg

from backend.config import settings

logger = logging.getLogger(__name__)

_CLUSTER_LABELS = ["話者A", "話者B", "話者C", "話者D", "話者E", "話者F", "話者G"]


class AdaptiveThresholdTracker:
    """Track similarity scores and compute adaptive threshold."""

    def __init__(self, default_threshold: float, window: int = 100):
        self._default = default_threshold
        self._window = window
        self._match_scores: list[float] = []
        self._miss_scores: list[float] = []

    def record(self, score: float, matched: bool) -> None:
        """Record a similarity score."""
        if matched:
            self._match_scores.append(score)
            if len(self._match_scores) > self._window:
                self._match_scores.pop(0)
        else:
            self._miss_scores.append(score)
            if len(self._miss_scores) > self._window:
                self._miss_scores.pop(0)

    def get_threshold(self) -> float:
        """Compute adaptive threshold from score distribution."""
        total = len(self._match_scores) + len(self._miss_scores)
        if total < 20:
            return self._default

        if not self._match_scores or not self._miss_scores:
            return self._default

        match_mean = float(np.mean(self._match_scores))
        miss_mean = float(np.mean(self._miss_scores))
        match_std = max(float(np.std(self._match_scores)), 0.01)
        miss_std = max(float(np.std(self._miss_scores)), 0.01)

        # Gaussian intersection approximation
        threshold = (miss_mean * match_std + match_mean * miss_std) / (match_std + miss_std)
        return float(np.clip(threshold, 0.50, 0.75))


class SpeakerCluster:
    """A single cluster of similar-sounding speech segments."""

    MAX_RESERVOIR = 10

    __slots__ = ("cluster_id", "label", "centroid", "count", "total_weight", "reservoir")

    def __init__(self, cluster_id: str, label: str, centroid: np.ndarray):
        self.cluster_id = cluster_id
        self.label = label
        self.centroid = centroid  # L2-normalized 256-dim vector
        self.count = 1
        self.total_weight = 1.0
        self.reservoir: list[np.ndarray] = [centroid.copy()]

    def update(self, embedding: np.ndarray, weight: float = 1.0) -> None:
        """Update centroid and reservoir with a new embedding."""
        self.count += 1
        self.total_weight += weight
        alpha = weight / self.total_weight
        self.centroid = self.centroid * (1 - alpha) + embedding * alpha
        norm = np.linalg.norm(self.centroid)
        if norm > 0:
            self.centroid /= norm

        # Reservoir update
        if len(self.reservoir) < self.MAX_RESERVOIR:
            self.reservoir.append(embedding.copy())
        else:
            dists = [float(np.dot(e, self.centroid)) for e in self.reservoir]
            worst = int(np.argmin(dists))
            if float(np.dot(embedding, self.centroid)) > dists[worst]:
                self.reservoir[worst] = embedding.copy()

    def similarity(self, embedding: np.ndarray) -> float:
        """Compute similarity using reservoir (top-k average) or centroid."""
        if len(self.reservoir) < 3:
            return float(np.dot(embedding, self.centroid))
        scores = sorted([float(np.dot(embedding, e)) for e in self.reservoir], reverse=True)
        k = max(1, int(len(scores) * 0.6))
        return float(np.mean(scores[:k]))


class SessionClusterManager:
    """Manages speaker clusters within a single transcription session.

    Usage:
        manager = SessionClusterManager()
        cluster_id, label, confidence = manager.match_or_create(embedding)
    """

    def __init__(self):
        self._clusters: list[SpeakerCluster] = []
        self._next_index: int = 0
        self._expected_speakers: list[str] = []
        self._used_expected: set[str] = set()
        self._merge_map: dict[str, str] = {}
        self._total_segments: int = 0
        self._threshold_tracker = AdaptiveThresholdTracker(settings.speaker_cluster_threshold)
        self._estimated_speakers: int | None = None
        self._cannot_links: set[tuple[str, str]] = set()

    def reset(self) -> None:
        """Clear all clusters (call at session start)."""
        self._clusters.clear()
        self._next_index = 0
        self._expected_speakers.clear()
        self._used_expected.clear()
        self._merge_map.clear()
        self._total_segments = 0
        self._threshold_tracker = AdaptiveThresholdTracker(settings.speaker_cluster_threshold)
        self._estimated_speakers = None
        self._cannot_links.clear()

    def set_expected_speakers(self, names: list[str],
                              seed_embeddings: dict[str, np.ndarray] | None = None) -> None:
        """Set expected participant names and optionally seed clusters."""
        self._expected_speakers = [n.strip() for n in names if n.strip()]
        self._used_expected.clear()

        if seed_embeddings:
            for name, emb in seed_embeddings.items():
                cluster_id = f"cluster_{self._next_index}"
                self._next_index += 1
                cluster = SpeakerCluster(cluster_id, name, emb.copy())
                self._clusters.append(cluster)
                self._used_expected.add(name)
                logger.info("Seeded cluster %s with registered speaker '%s'", cluster_id, name)

    def match_or_create(self, embedding: np.ndarray,
                        prev_cluster_id: str | None = None,
                        time_gap: float = 0.0,
                        blocked_clusters: set[str] | None = None) -> tuple[str, str, float]:
        """Match embedding to existing cluster or create a new one.

        Returns:
            (cluster_id, label, confidence)
        """
        self._total_segments += 1

        # Eigengap speaker count estimation
        if (settings.eigengap_enabled
                and self._total_segments >= settings.eigengap_min_segments
                and self._total_segments % settings.eigengap_update_interval == 0
                and len(self._clusters) >= 3):
            self._estimated_speakers = estimate_num_speakers(
                self._clusters, max_speakers=settings.speaker_max_count)
            logger.info("Eigengap: estimated %s speakers (from %d clusters)",
                        self._estimated_speakers, len(self._clusters))

        threshold = self._threshold_tracker.get_threshold()

        # Combine external blocked_clusters with internal cannot-links
        all_blocked = set(blocked_clusters) if blocked_clusters else set()
        if prev_cluster_id:
            for a, b in self._cannot_links:
                if a == prev_cluster_id:
                    all_blocked.add(b)
                elif b == prev_cluster_id:
                    all_blocked.add(a)

        best_cluster: SpeakerCluster | None = None
        best_score = 0.0

        for cluster in self._clusters:
            if all_blocked and cluster.cluster_id in all_blocked:
                continue
            score = cluster.similarity(embedding)
            # Temporal continuity: mild tie-breaking only (not threshold-altering)
            if cluster.cluster_id == prev_cluster_id and time_gap < 2.0:
                score += 0.02
            if score > best_score:
                best_score = score
                best_cluster = cluster

        if best_cluster is not None and best_score >= threshold:
            self._threshold_tracker.record(best_score, matched=True)
            best_cluster.update(embedding)
            return best_cluster.cluster_id, best_cluster.label, best_score

        if best_score > 0:
            self._threshold_tracker.record(best_score, matched=False)

        # Enforce maximum cluster count: force-assign to the most similar
        # existing cluster instead of creating a new one.
        effective_max = (
            min(self._estimated_speakers + 1, settings.speaker_max_count)
            if self._estimated_speakers is not None
            else settings.speaker_max_count
        )
        if len(self._clusters) >= effective_max and best_cluster is not None:
            best_cluster.update(embedding)
            logger.debug("Max clusters reached (%d/%d), force-assigned to %s (score=%.3f)",
                         len(self._clusters), effective_max, best_cluster.cluster_id, best_score)
            return best_cluster.cluster_id, best_cluster.label, best_score

        # Create new cluster
        cluster_id = f"cluster_{self._next_index}"
        label = self._pick_label()
        self._next_index += 1

        cluster = SpeakerCluster(cluster_id, label, embedding.copy())
        self._clusters.append(cluster)
        logger.info("New speaker cluster: %s (%s)", cluster_id, label)
        return cluster_id, label, 1.0

    def add_cannot_link(self, cluster_a: str, cluster_b: str) -> None:
        """Register a cannot-link constraint between two clusters."""
        pair = tuple(sorted([cluster_a, cluster_b]))
        self._cannot_links.add(pair)

    def try_merge_clusters(self) -> int:
        """Merge clusters whose centroids are similar enough.

        Also absorbs small clusters (count <= 2) into the most similar
        larger cluster when similarity exceeds a lower threshold.

        Returns the number of merges performed.
        """
        merge_threshold = settings.speaker_cluster_merge_threshold
        merged = 0

        # Phase 1: standard pairwise merge for high-similarity clusters
        i = 0
        while i < len(self._clusters):
            j = i + 1
            while j < len(self._clusters):
                score = self._cluster_similarity(self._clusters[i], self._clusters[j])
                if score >= merge_threshold:
                    ci, cj = self._clusters[i], self._clusters[j]
                    total = ci.count + cj.count
                    ci.centroid = (ci.centroid * ci.count + cj.centroid * cj.count) / total
                    norm = np.linalg.norm(ci.centroid)
                    if norm > 0:
                        ci.centroid /= norm
                    ci.count = total
                    ci.total_weight += cj.total_weight
                    combined = ci.reservoir + cj.reservoir
                    if len(combined) > SpeakerCluster.MAX_RESERVOIR:
                        scored = sorted(combined, key=lambda e: float(np.dot(e, ci.centroid)), reverse=True)
                        ci.reservoir = scored[:SpeakerCluster.MAX_RESERVOIR]
                    else:
                        ci.reservoir = combined
                    self._merge_map[cj.cluster_id] = ci.cluster_id
                    self._clusters.pop(j)
                    merged += 1
                    logger.info("Merged cluster %s into %s (score=%.3f)",
                                cj.cluster_id, ci.cluster_id, score)
                else:
                    j += 1
            i += 1

        # Phase 2: absorb small clusters (count <= 2, likely noise/fragments)
        # into the most similar larger cluster at a relaxed threshold.
        if self._total_segments > 15:
            small_threshold = merge_threshold - 0.10
            small_clusters = [c for c in self._clusters if c.count <= 2]
            for sc in small_clusters:
                best_target = None
                best_score = 0.0
                for tc in self._clusters:
                    if tc.cluster_id == sc.cluster_id or tc.count <= 2:
                        continue
                    score = self._cluster_similarity(sc, tc)
                    if score > best_score:
                        best_score = score
                        best_target = tc
                if best_target is not None and best_score >= small_threshold:
                    total = best_target.count + sc.count
                    best_target.centroid = (best_target.centroid * best_target.count + sc.centroid * sc.count) / total
                    norm = np.linalg.norm(best_target.centroid)
                    if norm > 0:
                        best_target.centroid /= norm
                    best_target.count = total
                    best_target.total_weight += sc.total_weight
                    combined = best_target.reservoir + sc.reservoir
                    if len(combined) > SpeakerCluster.MAX_RESERVOIR:
                        scored = sorted(combined, key=lambda e: float(np.dot(e, best_target.centroid)), reverse=True)
                        best_target.reservoir = scored[:SpeakerCluster.MAX_RESERVOIR]
                    else:
                        best_target.reservoir = combined
                    self._merge_map[sc.cluster_id] = best_target.cluster_id
                    self._clusters.remove(sc)
                    merged += 1
                    logger.info("Absorbed small cluster %s (count=%d) into %s (score=%.3f)",
                                sc.cluster_id, sc.count, best_target.cluster_id, best_score)

        # Phase 2.5: Absorb small clusters (count <= speaker_small_cluster_count)
        if self._total_segments > 30:
            small_count = settings.speaker_small_cluster_count
            small_merge_threshold = settings.speaker_small_cluster_merge_threshold
            small_clusters = [c for c in self._clusters if c.count <= small_count]
            for sc in small_clusters:
                best_target = None
                best_score = 0.0
                for tc in self._clusters:
                    if tc.cluster_id == sc.cluster_id or tc.count <= small_count:
                        continue
                    score = self._cluster_similarity(sc, tc)
                    if score > best_score:
                        best_score = score
                        best_target = tc
                if best_target is not None and best_score >= small_merge_threshold:
                    total = best_target.count + sc.count
                    best_target.centroid = (
                        best_target.centroid * best_target.count + sc.centroid * sc.count
                    ) / total
                    norm = np.linalg.norm(best_target.centroid)
                    if norm > 0:
                        best_target.centroid /= norm
                    best_target.count = total
                    best_target.total_weight += sc.total_weight
                    combined = best_target.reservoir + sc.reservoir
                    if len(combined) > SpeakerCluster.MAX_RESERVOIR:
                        scored = sorted(combined, key=lambda e: float(np.dot(e, best_target.centroid)), reverse=True)
                        best_target.reservoir = scored[:SpeakerCluster.MAX_RESERVOIR]
                    else:
                        best_target.reservoir = combined
                    self._merge_map[sc.cluster_id] = best_target.cluster_id
                    self._clusters.remove(sc)
                    merged += 1
                    logger.info("Phase 2.5: absorbed %s (count=%d) into %s (score=%.3f)",
                                sc.cluster_id, sc.count, best_target.cluster_id, best_score)

        return merged

    @staticmethod
    def _cluster_similarity(ci: SpeakerCluster, cj: SpeakerCluster) -> float:
        """Compute similarity between two clusters using reservoir cross-comparison."""
        if len(ci.reservoir) < 2 or len(cj.reservoir) < 2:
            return float(np.dot(ci.centroid, cj.centroid))
        scores = []
        for ei in ci.reservoir:
            for ej in cj.reservoir:
                scores.append(float(np.dot(ei, ej)))
        scores.sort(reverse=True)
        k = max(1, len(scores) // 3)
        return float(np.mean(scores[:k]))

    def pop_merge_map(self) -> dict[str, str]:
        """Return and clear the merge map {old_cluster_id: new_cluster_id}."""
        m = dict(self._merge_map)
        self._merge_map.clear()
        return m

    def _pick_label(self) -> str:
        """Pick the next label for a new cluster."""
        # Use expected speaker names first (if available and unused)
        for name in self._expected_speakers:
            if name not in self._used_expected:
                self._used_expected.add(name)
                return name

        # Fall back to generic labels (sequential, skipping none)
        used_labels = {c.label for c in self._clusters}
        for label in _CLUSTER_LABELS:
            if label not in used_labels:
                return label
        return f"話者{len(self._clusters) + 1}"

    def merge_to_speaker(self, cluster_id: str, speaker_id: str) -> None:
        """Remove a cluster after it has been promoted to a registered speaker."""
        self._clusters = [c for c in self._clusters if c.cluster_id != cluster_id]

    def rename_cluster(self, cluster_id: str, new_label: str) -> bool:
        """Rename a cluster's label without promoting it to a registered speaker."""
        for cluster in self._clusters:
            if cluster.cluster_id == cluster_id:
                cluster.label = new_label
                return True
        return False

    def get_cluster_embedding(self, cluster_id: str) -> np.ndarray | None:
        """Get the centroid embedding for a cluster."""
        for cluster in self._clusters:
            if cluster.cluster_id == cluster_id:
                return cluster.centroid
        return None

    def get_cluster_label(self, cluster_id: str) -> str | None:
        """Get the label for a cluster."""
        for cluster in self._clusters:
            if cluster.cluster_id == cluster_id:
                return cluster.label
        return None


# --- Eigengap speaker count estimation ---

def _build_affinity_matrix(clusters: list[SpeakerCluster]) -> np.ndarray:
    n = len(clusters)
    W = np.zeros((n, n), dtype=np.float64)
    for i in range(n):
        for j in range(i + 1, n):
            sim = SessionClusterManager._cluster_similarity(clusters[i], clusters[j])
            W[i, j] = max(sim, 0.0)
            W[j, i] = W[i, j]
    return W


def _compute_eigengap(W: np.ndarray, max_k: int) -> int:
    n = W.shape[0]
    np.fill_diagonal(W, 0.0)
    D = np.diag(W.sum(axis=1))
    L = D - W
    eigenvalues = scipy.linalg.eigvalsh(L)
    eigenvalues = np.sort(eigenvalues)
    gaps = np.diff(eigenvalues[:min(max_k + 1, n)])
    if len(gaps) == 0:
        return 1
    return max(1, min(int(np.argmax(gaps)) + 1, max_k))


def estimate_num_speakers(
    clusters: list[SpeakerCluster],
    max_speakers: int = 7,
    min_clusters: int = 3,
) -> int | None:
    if len(clusters) < min_clusters:
        return None
    W = _build_affinity_matrix(clusters)
    return _compute_eigengap(W, max_speakers)
