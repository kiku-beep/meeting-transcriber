# 話者識別改善：改善策3 + 改善策4 実装プラン

## プロジェクト構成
```
/e/transcriber/backend/
├── config.py                          (設定)
├── core/
│   ├── speaker_cluster.py             (クラスタ管理 — 改善策3・4の中核)
│   ├── diarizer.py                    (embedding抽出)
│   └── ...
├── models/
│   ├── session.py                     (セッションライフサイクル)
│   └── pipeline.py                    (メイン処理ループ)
└── api/
    └── routes_session.py              (API エンドポイント)
```

---

## 改善策3：小クラスタ統合後処理

### 問題背景
- `match_or_create()` で同じ話者が90+のIDに分裂（閾値が低い or embedding多様性が高い）
- `try_merge_clusters()` は現在 Phase 1（高類似度）+ Phase 2（小クラスタ count<=2） のみ
- **Phase 2.5を追加**：定期的に「小クラスタ」を統合

### 定義：「小クラスタ」
```
count <= 3 AND embedding_count <= 3
```

### 設計：小クラスタ統合後処理 (Phase 2.5)

#### 実行タイミング
1. **定期実行**：pipeline.py の `run()` ループ内で `try_merge_clusters()` 呼び出しの直後
2. **セッション終了時**：session.py の `stop()` → `_offline_recluster()` 前に最終統合

#### 統合先決定ロジック
1. 小クラスタ（count <= 3）を特定
2. 各小クラスタについて「最も類似な大クラスタ」を探索
3. 統合閾値：`merge_threshold - 0.15`（Phase 2より低い）
4. 最も近い大クラスタにマージ（Phase 2と同じロジック）

#### コード変更箇所

**変更ファイル**:
- `speaker_cluster.py`: `SessionClusterManager.try_merge_clusters()` を拡張
- `config.py`: `speaker_small_cluster_threshold` を追加

##### 具体的コード変更

**1. config.py 追加項目**
```python
# Line 47 の後に追加
speaker_small_cluster_count: int = 3  # count <= 3 を「小」と定義
speaker_small_cluster_merge_threshold: float = 0.45  # merge_threshold - 0.15 = 0.60 - 0.15
```

**2. speaker_cluster.py の `try_merge_clusters()` 拡張**
```python
def try_merge_clusters(self) -> int:
    """Merge clusters (3 phases now: high-sim, small clusters, micro clusters)."""

    # ... Phase 1 と Phase 2 は既存コード ...

    # Phase 2.5: Absorb micro clusters (count <= 3, only if > 15 segments)
    if self._total_segments > 15:
        small_threshold = settings.speaker_small_cluster_merge_threshold  # 0.45
        small_clusters = [c for c in self._clusters if c.count <= settings.speaker_small_cluster_count]
        for sc in small_clusters:
            # （Phase 2 と同じロジック）
            # 最も類似な「大」クラスタを探索して統合
```

**エッジケース対応**:
- Phase 2 で small_clusters を定義済み → Phase 2.5 では新規抽出
- Phase 2 実行後に `self._clusters` が変わっているため、Phase 2.5 では独立に実行

---

## 改善策4：eigengap法による話者数自動推定

### 問題背景
- `speaker_max_count = 7` は固定値 → 実際の話者数が不明
- `match_or_create()` で `len(self._clusters) >= 7` になると force-assign
- **eigengap法**：アフィニティ行列の固有値から最適なクラスタ数を推定

### アルゴリズム概要
1. embedding 間のコサイン類似度から **affinity 行列** を構築
2. **グラフラプラシアン** L = D - A を計算（D：次数行列）
3. L の固有値 λ₀ ≤ λ₁ ≤ ... を計算
4. **eigengap = λ_{k+1} - λ_k** の最大値を見つけた k を「最適話者数」とする
5. 推定値を使って `match_or_create()` の `speaker_max_count` を動的に上書き

### 設計：eigengap法の実装

#### 実行タイミング
1. **定期実行**：pipeline.py で 50 entries ごと（autosave と同じタイミング）
2. **セッション終了時**：`stop()` 時に最終推定値を記録

#### エッセンス
```python
# affinity 行列（embedding の cosine similarity）
n = len(embeddings)
affinity = np.dot(embeddings, embeddings.T)  # (n, n)

# グラフラプラシアン
D = np.diag(affinity.sum(axis=1))
L = D - affinity

# 固有値分解
eigenvalues = scipy.linalg.eigvalsh(L)

# eigengap 最大化
eigengaps = np.diff(eigenvalues)
optimal_k = np.argmax(eigengaps) + 1
```

#### 依存ライブラリ
- `scipy.linalg.eigvalsh()` — Hermitian 行列の固有値分解
- **既に requirements.txt に scipy が含まれている**（_offline_recluster で使用中）

#### コード変更箇所

**変更ファイル**:
- `speaker_cluster.py`: 新規メソッド `estimate_optimal_speaker_count()`
- `config.py`: `speaker_count_estimation_enabled`, `speaker_count_min_samples` を追加
- `pipeline.py`: autosave タイミングで定期推定
- `session.py`: セッション終了時に最終推定値をログ

##### 具体的コード変更

**1. config.py 追加項目**
```python
# Line 47 の後に追加
speaker_count_estimation_enabled: bool = True  # eigengap法を有効化
speaker_count_estimation_min_samples: int = 20  # 推定に必要な最小embedding数
```

**2. speaker_cluster.py に新規メソッド追加**
```python
def estimate_optimal_speaker_count(self) -> int | None:
    """Estimate optimal speaker count using eigengap method.

    Returns:
        Optimal k (2..n) or None if conditions not met.
    """
    if len(self._clusters) < settings.speaker_count_estimation_min_samples:
        return None

    # Collect all embeddings from reservoirs
    embeddings = []
    for cluster in self._clusters:
        embeddings.extend(cluster.reservoir)

    if len(embeddings) < settings.speaker_count_estimation_min_samples:
        return None

    embeddings = np.array(embeddings)  # (m, 192)

    # Affinity matrix (cosine similarity)
    affinity = np.dot(embeddings, embeddings.T)

    # Graph Laplacian
    try:
        from scipy import linalg
        D = np.diag(affinity.sum(axis=1))
        L = D - affinity

        # Eigenvalue decomposition
        eigenvalues = linalg.eigvalsh(L)

        # Find eigengap
        eigengaps = np.diff(eigenvalues)
        optimal_k = np.argmax(eigengaps) + 1

        # Clip to reasonable range
        optimal_k = max(2, min(optimal_k, 15))

        logger.info("Eigengap estimation: optimal_k=%d (clusters=%d, embeddings=%d)",
                    optimal_k, len(self._clusters), len(embeddings))
        return int(optimal_k)
    except Exception:
        logger.exception("Eigengap estimation failed")
        return None
```

**3. pipeline.py の autosave 箇所に推定を追加**
```python
# Line 232 の autosave 処理で：
if entries_since >= AUTOSAVE_INTERVAL_ENTRIES:
    # 既存のautosave コード

    # 新規：speaker count 推定（50 entries ごと）
    if settings.speaker_count_estimation_enabled:
        estimated_k = self._cluster_manager.estimate_optimal_speaker_count()
        if estimated_k is not None and estimated_k != settings.speaker_max_count:
            logger.info("Updating speaker_max_count: %d → %d",
                        settings.speaker_max_count, estimated_k)
            settings.speaker_max_count = estimated_k
```

**4. session.py の `stop()` に最終推定を追加**
```python
# Line 208 の `_offline_recluster()` の前に：
estimated_k = self._cluster_manager.estimate_optimal_speaker_count()
if estimated_k is not None:
    logger.info("Final speaker count estimation: %d speakers", estimated_k)
```

---

## 実装順序

### Phase 1：改善策3（小クラスタ統合）
1. config.py に `speaker_small_cluster_count`, `speaker_small_cluster_merge_threshold` 追加
2. speaker_cluster.py の `try_merge_clusters()` に Phase 2.5 を追加
3. 動作確認：20+ segments でマージログが出る

### Phase 2：改善策4（eigengap法）
1. config.py に `speaker_count_estimation_enabled`, `speaker_count_estimation_min_samples` 追加
2. speaker_cluster.py に `estimate_optimal_speaker_count()` メソッド追加
3. pipeline.py で定期推定を実装
4. session.py で最終推定を実装
5. 動作確認：推定値がログに出力される

---

## リスク・注意点

### 改善策3
- **リスク**：小クラスタ統合の過程で同一話者のクラスタが誤ってマージされる可能性
- **対策**：`merge_threshold - 0.15 = 0.45` は十分に低い；段階的に検証

### 改善策4
- **リスク**：embedding 数が少ないと固有値が不安定（eigengap が信頼できない）
- **対策**：`speaker_count_estimation_min_samples = 20` 以上で推定実行
- **固有値計算**：scipy.linalg.eigvalsh() は Hermitian 行列専用；L は実対称行列なので OK
- **パフォーマンス**：eigenlsh() は O(n³) だが、embedding 数 ~100 なら無視可能

### 両方に共通
- **設定変更のリバート不可**：実行時に設定変更したら手動で戻す必要がある
- **テスト**：実際の長時間セッションで試行錯誤が必要（20分以上推奨）

---

## ビルド・テスト確認チェック
- [ ] config.py にセッティング追加後、`python -c "from backend.config import settings; print(settings)"` で確認
- [ ] speaker_cluster.py を修正後、`python -m pytest backend/core/test_speaker_cluster.py` があればテスト実行
- [ ] pipeline.py + session.py 修正後、フロントエンド経由で実際に10+ 分のセッション実行して動作確認
- [ ] ログに "Eigengap estimation:" と "Phase 2.5:" が出力されることを確認

---

## 現在の状態

**完成**：
- config.py 設定： speaker_cluster_threshold (0.55), speaker_cluster_merge_threshold (0.60), speaker_max_count (7)
- speaker_cluster.py：Phase 1 + Phase 2 実装済み
- pipeline.py：try_merge_clusters() を 50 entries ごと呼び出し中

**未実装**：
- Phase 2.5（小クラスタ統合後処理）
- eigengap法推定機能
- 両者の統合テスト

