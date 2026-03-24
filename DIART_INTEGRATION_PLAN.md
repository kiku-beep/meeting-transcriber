# Diart ライブラリ統合設計プラン

**作成日**: 2026-02-22
**対象プロジェクト**: Transcriber (E:\transcriber)
**バージョン**: 1.0 - 設計段階

---

## エグゼクティブサマリ

### 現状
- 独自クラスタリング実装（speaker_cluster.py）：cosine 類似度ベースの incremental clustering
- ECAPA-TDNN 埋め込み + Adaptive Threshold Tracker で話者識別
- オンラインマージと事後 HAC 統合の2段階処理

### 検討対象
**diart ライブラリ** の採用により、以下を実現可能：
- Cannot-Link 制約による精度向上（重複話者環境で誤マージ削減）
- ストリーミング対応の既存実装（保守負荷軽減）
- 複数埋め込みモデルのサポート（ECAPA-TDNN, WeSpeaker など）

### 提案パターン
1. **パターンA: 完全置換** — diart.SpeakerDiarization に移行
2. **パターンB: 部分採用** — Cannot-Link 制約ロジックのみ移植

---

## 現在のアーキテクチャ詳細

### フロー図
```
Audio Input → VAD (Silero) → Embedding (ECAPA-TDNN)
                                          ↓
                    SessionClusterManager
                   /  (Incremental Clustering)
              Registered Speaker / New Cluster
                          ↓
                   Pipeline → Transcript Entry
                          ↓
                   [Session終了]
                          ↓
                  Offline HAC Re-clustering
```

### 現在のパラメータ

| 設定項目 | 値 | 説明 |
|---------|-----|-----|
| `speaker_similarity_threshold` | 0.60 | 登録話者との照合閾値 |
| `speaker_cluster_threshold` | 0.55 | 新規クラスタ作成閾値 |
| `speaker_cluster_merge_threshold` | 0.60 | マージ対象の閾値 |
| `speaker_max_count` | 7 | 最大クラスタ数制限 |
| VAD min_silence_ms | 500 | 沈黙検出時間 |
| VAD max_segment_s | 10.0 | 最大セグメント長 |

### 主要ファイル
- **core/speaker_cluster.py** (323 行): AdaptiveThresholdTracker, SpeakerCluster, SessionClusterManager
- **core/diarizer.py** (183 行): ECAPA-TDNN 埋め込み抽出、登録話者照合
- **models/pipeline.py** (253 行): VAD → Whisper → 埋め込み抽出 → クラスタマッチング
- **models/session.py** (493 行): セッション状態管理、事後 HAC 再クラスタリング

### VRAM 使用量（現在）
- ECAPA-TDNN：~100MB
- Silero VAD：~20MB (CPU)
- 合計：~120MB GPU

---

## 検討パターン

### パターンA: 完全置換 — diart.SpeakerDiarization への移行

#### 概要
speaker_cluster.py と diarizer.py を **diart.SpeakerDiarization** で統一。
VAD もセグメンテーション段階に組み込み、Cannot-Link 制約を活用。

#### 変更ファイル

| ファイル | 変更内容 |
|----------|--------|
| `core/diarizer.py` | 削除（diart.SpeakerDiarization に統合） |
| `core/speaker_cluster.py` | 削除（diart.SpeakerDiarization に統合） |
| `models/pipeline.py` | **大幅修正**：diart インスタンス生成、ストリーミングループ実装 |
| `models/session.py` | **修正**：diarizer, cluster_manager の削除、diart パイプライン統合 |
| `api/routes_speaker.py` | **修正**：diart の埋め込みモデルと互換性確認 |
| `config.py` | **修正**：diart パラメータ（latency, threshold 等）追加 |
| `pyproject.toml` | 依存関係追加：`diart>=0.2` |

#### 実装ステップ

1. **diart 初期化**
   ```python
   from diart import SpeakerDiarization
   from diart.sources import MicrophoneSource

   diarizer = SpeakerDiarization(
       segmentation="pyannote/segmentation-3.0",  # VAD + セグメンテーション
       embedding="speechbrain/spkrec-ecapa-voxceleb",  # ECAPA-TDNN
       embedding_batch_size=64,
       clustering="AgglomerativeClustering",
       distance_metric="cosine"
   )
   ```

2. **ストリーミングループ**
   ```python
   # パイプライン内でストリーミング推論
   async def process_stream(self):
       async for output in diarizer.stream(audio_source):
           # output.speakers → {speaker_id: confidence, ...}
           # output.segmentation → timing info
           await self._process_diarization_output(output)
   ```

3. **Cannot-Link 制約の利用**
   ```python
   # diarizer が自動的に cannot-link 制約を導出・適用
   # → 重複話者検出から制約を生成し、マージ防止
   ```

4. **登録話者との統合**
   ```python
   # diart の embedding を取得し、登録話者DB と照合
   embedding = diarizer.embedding_model.embed(audio_segment)
   match = self._match_with_registered(embedding)
   ```

#### メリット
- ✅ **Cannot-Link 制約** による精度向上（重複環境で顕著）
- ✅ **保守負荷軽減**：自社実装 350+ 行の削減
- ✅ **ストリーミング実装** が公式で保証
- ✅ **複数埋め込みモデル対応**：WeSpeaker, TitaNet への切り替え容易
- ✅ **研究成果の直接活用**：論文で検証済みのアルゴリズム

#### デメリット・リスク
- ❌ **大幅なコード書き換え**：pipeline.py, session.py が複雑化
  - ストリーミング出力形式の学習曲線
  - diart.RxPY（リアクティブプログラミング）の導入
- ❌ **Adaptive Threshold** が失われる
  - 代替案：diart の `distance_threshold` で固定値利用
- ❌ **既存パラメータ互換性喪失**
  - `speaker_cluster_threshold` 等は使用不可
  - diart ネイティブパラメータへの再調整が必要
- ❌ **VRAM増加の可能性**
  - セグメンテーションモデル（20～100MB）が追加
  - 合計：~200MB～250MB
- ❌ **依存バージョン競合**
  - diart が要求する pyannote-audio バージョン確認必須
  - 現在：pyannote-audio>=3.3

#### テスト戦略
- [ ] diart 単体テスト（ユニット）
- [ ] 登録話者マッチング精度テスト（既存 API との互換性）
- [ ] ストリーミング遅延測定（目標：<500ms）
- [ ] VRAM 使用量監視
- [ ] Cannot-Link 効果測定（重複話者環境での精度向上確認）
- [ ] セッション終了後の再クラスタリング動作確認

#### 実装予定工数
- **研究・設定**: 4 時間
- **コード実装**: 12～16 時間
- **テスト・調整**: 8～12 時間
- **合計**: 24～32 時間

---

### パターンB: 部分採用 — Cannot-Link 制約ロジックのみ移植

#### 概要
現在の speaker_cluster.py を基盤として維持し、diart から **Cannot-Link 制約生成ロジック** のみを採用。
セグメンテーションと埋め込みはそのまま。

#### 変更ファイル

| ファイル | 変更内容 |
|----------|--------|
| `core/speaker_cluster.py` | **修正**：Cannot-Link 制約マトリックス追加（100～150 行） |
| `core/segmentation.py` | **新規作成**：pyannote-audio-3.3 セグメンテーションモデル統合（150～200 行） |
| `models/pipeline.py` | **修正**：Cannot-Link 制約をマッチング時に適用（50 行） |
| `models/session.py` | **軽微修正**：segmentation_model の初期化 |
| `pyproject.toml` | 依存関係：diart 不要（pyannote-audio 既に存在） |

#### 実装ステップ

1. **セグメンテーションモデル統合**
   ```python
   # core/segmentation.py（新規）
   from pyannote.audio import Model

   class SpeakerSegmenter:
       def __init__(self):
           self.model = Model.from_pretrained("pyannote/segmentation-3.0")

       def get_overlap_windows(self, audio, sample_rate):
           """時間窓ごとに複数話者の重複箇所を検出"""
           # → {(start, end): speaker_indices}
   ```

2. **Cannot-Link 制約マトリックス**
   ```python
   # core/speaker_cluster.py に追加
   class CannotLinkConstraints:
       def __init__(self):
           self.constraints: set[tuple[str, str]] = set()

       def add_constraint(self, cluster_id_1, cluster_id_2):
           """2つのクラスタを強制的に異なる話者として扱う"""
           self.constraints.add((cluster_id_1, cluster_id_2))

       def is_forbidden_merge(self, cluster_id_1, cluster_id_2) -> bool:
           return (cluster_id_1, cluster_id_2) in self.constraints
   ```

3. **セグメンテーション → 制約への変換**
   ```python
   # models/pipeline.py
   overlap_windows = self._segmenter.get_overlap_windows(audio)
   for start, end in overlap_windows:
       # この時間窓で複数話者が重複 → 関連するクラスタに cannot-link 追加
       for cid_pair in overlapped_clusters:
           self._cluster_manager.add_constraint(cid_pair[0], cid_pair[1])
   ```

4. **マージ時に制約チェック**
   ```python
   # speaker_cluster.py の try_merge_clusters() 修正
   for ci, cj in candidate_pairs:
       if self._constraints.is_forbidden_merge(ci.cluster_id, cj.cluster_id):
           continue  # マージ候補から除外
       # 通常のマージ処理
   ```

#### メリット
- ✅ **保守性維持**：既存コード構造の大部分を保持
- ✅ **低リスク**：100～200 行の追加で実装可能
- ✅ **段階的導入**：現在の adaptive threshold と並行運用可能
- ✅ **デバッグ容易**：従来の SessionClusterManager で既知の動作を把握
- ✅ **VRAM増加最小限**：セグメンテーションモデルのみ追加（~30MB）

#### デメリット・リスク
- ❌ **Cannot-Link 効果が限定的**
  - diart の Cannot-Link は統計的・動的に導出
  - パターンB は「セグメンテーション → 重複 → 制約」の単純な変換のみ
  - 重複ウィンドウ外の誤マージは防止不可
- ❌ **セグメンテーションモデルの追加学習コスト**
  - pyannote-3.0 API の習得が必要
  - 既存 ECAPA-TDNN との統合ロジック確認
- ❌ **時間計算量増加**
  - セグメンテーション: ～500ms～1s per session
  - 制約マトリックス管理: O(n²)（n = クラスタ数）
- ❌ **Cannot-Link の効果測定が困難**
  - 「制約がなかった場合との比較」が難しい
  - ABテストが必須

#### テスト戦略
- [ ] セグメンテーションモデルの重複検出精度確認
- [ ] Cannot-Link 制約が正しく適用されているか（ユニット）
- [ ] 既存のマージ動作との互換性確認
- [ ] 時間計算量増加の実測（session の処理時間）
- [ ] 誤マージ率低下の検証（テストコーパスでの比較）
- [ ] Adaptive Threshold と Cannot-Link の相互作用確認

#### 実装予定工数
- **研究・設定**: 2 時間
- **コード実装**: 6～8 時間
- **テスト・調整**: 6～8 時間
- **合計**: 14～18 時間

---

## パターン選定ガイド

### パターンA を選ぶべき場合
- ✅ Cannot-Link 効果を最大化したい
- ✅ 複数埋め込みモデルの切り替えが頻繁
- ✅ 保守負荷削減を優先（長期的にはコスト削減）
- ✅ リアルタイム精度が最優先
- ❌ 短期的な実装リスクを受容できる

### パターンB を選ぶべき場合
- ✅ 現在の speaker_cluster.py の安定性を維持したい
- ✅ 段階的改善が望ましい
- ✅ 既存テストスイートを最大限再利用したい
- ✅ チームの学習曲線を最小化したい
- ❌ 最大精度よりは安定性・予測可能性を優先

---

## 推奨案

### **パターンB（部分採用）を初期段階で推奨**

#### 根拠
1. **最小限の技術的破壊**
   - 既存の SessionClusterManager は動作実績あり
   - Cannot-Link は「追加の制約」として機能 → 既存ロジックに干渉しない

2. **段階的リスク軽減**
   - パターンB で Cannot-Link 効果を測定
   - 効果が大きければ段階的にパターンA へ移行

3. **現在の課題への対応**
   - 重複話者環境での誤マージが主な課題 → Cannot-Link が直接対処
   - コスト（実装 14～18h）に対して効果が見込める

#### パターンB → パターンA の移行ロードマップ（将来）
```
Sprint 1 (現在)    : パターンB 実装 + Cannot-Link 効果測定 (2週間)
  ↓
Sprint 2 (1ヶ月後) : Cannot-Link 精度検証、ユーザーフィードバック収集
  ↓
Sprint 3 (2ヶ月後) : 必要に応じてパターンA への段階的移行
                     （diart.SpeakerDiarization の試験実装）
  ↓
Sprint 4 (3ヶ月後) : パターンA への完全切り替え（利益が確認された場合）
```

---

## 依存関係と互換性

### パターンA の依存関係追加
```toml
# pyproject.toml に追加
diart = ">=0.2"
# 既に存在：pyannote-audio>=3.3, scipy>=1.14
```

### バージョン確認項目
- [ ] diart>=0.2 が pyannote-audio>=3.3 と互換性あるか
- [ ] diart が SpeechBrain ECAPA-TDNN と互換性あるか
- [ ] Python 3.10～3.12 での動作確認

### パターンB の依存関係追加
```toml
# 追加なし（pyannote-audio は既に依存）
```

---

## VRAM と パフォーマンスへの影響

### 現在（ベースライン）
- Whisper (kotoba-v2.0): 2500MB
- ECAPA-TDNN: 100MB
- Silero VAD: 20MB (CPU)
- **合計**: ~2620MB

### パターンA 導入後
- Whisper: 2500MB (変わらず)
- Diart (セグメンテーション + 埋め込み): 200～250MB
- Silero VAD: 削除（diart に統合）
- **合計**: ~2700～2750MB (**+80～130MB**)

### パターンB 導入後
- Whisper: 2500MB (変わらず)
- ECAPA-TDNN: 100MB (変わらず)
- Silero VAD: 20MB (変わらず)
- セグメンテーションモデル（新）: 30MB
- **合計**: ~2650MB (**+30MB**)

### 処理時間への影響

| 処理ステップ | 現在 | パターンA | パターンB |
|-----------|-----|---------|---------|
| VAD | 15ms | (integrated) | 15ms |
| 埋め込み抽出 | 50ms | 50ms | 50ms |
| クラスタマッチング | 5ms | (integrated) | 5ms |
| **Cannot-Link 制約適用** | - | (auto) | 10～20ms |
| **セグメンテーション** | - | (integrated) | 500～1000ms (session開始時のみ) |
| **合計（per segment）** | ~70ms | ~150ms | ~80ms |

---

## 実装計画（パターンB 推奨）

### フェーズ 1: 準備（2日）
- [ ] pyannote-audio-3.0 API ドキュメント精読
- [ ] セグメンテーションモデル (pyannote/segmentation-3.0) の動作確認
- [ ] テストコーパス（重複話者ケース）の準備

### フェーズ 2: 実装（1週間）
- [ ] `core/segmentation.py` 新規作成（セグメンテーション + 重複検出）
- [ ] `core/speaker_cluster.py` 修正（Cannot-Link マトリックス追加）
- [ ] `models/pipeline.py` 修正（制約適用ロジック）
- [ ] `config.py` 修正（Cannot-Link パラメータ追加）

### フェーズ 3: テスト・検証（1週間）
- [ ] ユニットテスト：セグメンテーション精度
- [ ] ユニットテスト：Cannot-Link 制約の動作
- [ ] インテグレーションテスト：既存話者登録機能との互換性
- [ ] 性能テスト：VRAM, レイテンシ
- [ ] Aテスト：重複話者シナリオでの誤マージ削減確認

### フェーズ 4: デプロイ・モニタリング（1週間）
- [ ] パターンB をステージング環境にデプロイ
- [ ] ユーザーフィードバック収集（Cannot-Link 効果の実感）
- [ ] 本番環境への段階的ロールアウト

---

## まとめ：推奨事項

| 項目 | パターンA | パターンB |
|-----|---------|---------|
| **Cannot-Link 効果** | ★★★★★ | ★★★☆☆ |
| **実装リスク** | ★★★★☆ (高) | ★☆☆☆☆ (低) |
| **保守コスト** | ★☆☆☆☆ (低) | ★★☆☆☆ (中) |
| **実装工数** | 24～32h | 14～18h |
| **学習曲線** | 急 | 緩 |
| **推奨度（現在）** | ⭐ 将来的 | ⭐⭐⭐ **即推奨** |

### 結論
**パターンB（部分採用）から開始し、Cannot-Link 効果の実測を通じて、段階的にパターンA への移行を検討する** ことが、技術的リスク・保守負荷・チーム学習のバランスが最適。

---

## 参考資料

- Diart GitHub: https://github.com/juanmc2005/diart
- Diart Paper: "Overlap-aware low-latency online speaker diarization based on end-to-end local segmentation"
- pyannote-audio: https://github.com/pyannote/pyannote-audio
- SpeechBrain ECAPA-TDNN: https://github.com/speechbrain/speechbrain
