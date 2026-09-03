# 論点ツリー → 議論マップ（argument map）化

## 目的

会議中の画面に「今どの論点を議論しているか」だけでなく、
**「どの案が、どの制約によって潰れたか」** を矢印付きの図で残す。

現状は `parent` 1本の木しか持てないため、
「Aにすべきでは？」「いや制約Bがあるから無理」という**関係の種類**が図に残らない。

## スコープ外（今回やらない）

- 更新間隔・遅延（中央値81秒）の改善
- ラベル長 `MAX_LABEL_LEN = 15` の変更
- Google Meet 実機テスト

## 1. データモデル（backend/core/topic_tree.py）

```python
VALID_KINDS = ("question", "claim", "constraint", "decision")
VALID_LINK_TYPES = ("supports", "objects", "constrains", "depends")

class TopicNode(BaseModel):
    id: str
    parent: str | None = None
    label: str
    kind: str = "question"          # 追加
    status: str = "open"
    start_sec: float = 0.0
    end_sec: float = 0.0

class TopicLink(BaseModel):         # 追加
    source: str
    target: str
    type: str = "objects"

class TopicTree(BaseModel):
    nodes: list[TopicNode] = []
    links: list[TopicLink] = []     # 追加
    active: str | None = None

class TopicPatch(BaseModel):
    add: list[TopicNode] = []
    add_links: list[TopicLink] = [] # 追加
    update: list[dict] = []
    active: str | None = None
```

`from` / `to` は Python 予約語と紛らわしいので **`source` / `target` を使う**。

`parent` は削除しない。保存済みセッションの後方互換と、描画のレーン内クラスタ計算に使う。

### 意味づけ

| kind | 意味 | 例 |
|---|---|---|
| `question` | 問い | 「見積PDFをGASで続けるか」 |
| `claim` | 案・立場 | 「楽楽のネイティブPDFに寄せる」 |
| `constraint` | 動かせない事実 | 「処理用アドレスが未配送」 |
| `decision` | 合意・保留 | 「A案採用、ただしC2解消が前提」 |

| link type | 意味 | 典型的な向き |
|---|---|---|
| `supports` | 根拠として支える | claim → claim / claim → decision |
| `objects` | 反論する | claim → claim |
| `constrains` | 制約で縛る | constraint → claim |
| `depends` | 前提として依存する | decision → constraint |

## 2. プロンプト（build_patch_prompt）

現行スキーマ例に `kind` と `add_links` を足す。既存の注意書き（`parent` は null か既存id、
空文字禁止、深さ最大3、話の順に繋げない、文字起こしにない内容を補わない）は**すべて残す**。

追加で指示する内容:

- 「〜すべきか」という問いは `kind:"question"`、案・立場は `"claim"`、
  動かせない条件・コスト・仕様・人員の話は `"constraint"`、合意・保留は `"decision"`。
- 反論・制約は**必ず別ノードにして `add_links` で繋ぐ**。claim の label に
  「〜だが難しい」と押し込まない。
- `add_links` の `source` / `target` は既存idか同じパッチ内の新規idのみ。
- リンクが1本も無い更新では `add_links` を `[]` にする。

`schema` 文字列の例も同じ形に更新すること。

## 3. パース・適用

### parse_patch

- `add_links` を寛容にパースする。`dict` 以外、`source`/`target` が非空文字列でないものは捨てる。
- `type` が `VALID_LINK_TYPES` に無いリンクは**捨てる**（status のように既定値へ丸めない。
  誤った種類の矢印は、矢印が無いことより有害）。

### _normalize_node

- `kind` が `VALID_KINDS` に無ければ `"question"` に丸める（status と同じ扱い）。

### apply_patch

既存のノード採用ロジックはそのまま。そのあとリンクを検証する:

1. `source == target` は捨てる
2. `source` / `target` のどちらかが最終ノード集合に存在しなければ捨てる
   （親不明で捨てられたノードに繋がるリンクが残らないこと）
3. `(source, target, type)` が既存リンクと重複したら捨てる
4. 生き残ったリンクを `existing_links + accepted` の順で返す

### reserve_ids

`add_links` の `source` / `target` にも `remapped_ids` を適用する。
ここを忘れると採番衝突時にリンクが宙に浮く。

### select_tree_for_prompt

返すツリーの `links` は、**選ばれたノード集合の内側で両端が閉じているものだけ**にする。

### tree_from_dict / tree_to_dict

- `links` が無い保存データ（既存セッション）は `links: []` として読む。**404にしない**。
- `kind` が無いノードは `"question"` として読む。
- `tree_to_dict` は `nodes` / `links` / `active` を返す。

## 4. フロントエンド

### types.ts

`TopicKind`, `TopicLinkType`, `TopicLink` を追加。`TopicNode.kind`、`TopicTree.links` を追加。

### 描画: topics/TopicGraphView.tsx（新規）

`TopicNode.tsx` の入れ子div再帰は**捨てる**（矢印を描けないため）。SVGで描く。
**図ライブラリは追加しない。**

レイアウトは kind ごとの固定レーン:

| レーン | kind | y |
|---|---|---|
| 0 | question | 0 |
| 1 | claim | 110 |
| 2 | constraint | 220 |
| 3 | decision | 330 |

- ノード箱は幅170 / 高さ46、x 間隔190。

**レイアウトは実装前にモックで検証済み（下記が検証後の確定版）。素朴に
「レーンごとに左から詰める」だと論点とその主張群がズレて塊が読めない。**

1. クラスタ = `parent` を辿って到達する最上位ノードのid。辿れなければ
   リンクで繋がる相手のクラスタ。それも無ければ自分。
2. クラスタを `start_sec` 昇順に横へ並べ、**各クラスタに横帯を確保する**。
   帯の幅 = そのクラスタ内で最も人数の多いレーンの人数。
3. 帯の中で各レーンの行を**中央寄せ**する（`offset = (帯幅 - そのレーンの人数) / 2`）。
   これで論点の真下にその主張・制約・決着が来る。
4. クラスタ帯は詰めて隣に置く。

エッジは3次ベジェ、矢尻は `<marker>`。**向きで場合分けする**:

- **同一レーン内**（claim→claim の `objects` など）は、両端の**下辺から出して箱の下を回る弧**。
  縦ベジェのままだと潰れて線が見えない（モックで確認）。
  たわみ `sag = min(48, 20 + |x2-x1| * 0.10)`。
- **レーンをまたぐ**場合は縦ベジェ。ただし**2レーン以上跨ぐ線は制御点を横へ
  `±(BW/2 + 26)` 膨らませ**、間のレーンの箱を貫かせない。
- 色分け: `question` 濃紺地/白字、`claim` 青、`constraint` 赤、`decision` 緑。
- リンク: `supports` 緑実線 / `objects` 赤実線 / `constrains` 赤破線 / `depends` 灰破線。
  凡例を図の外に出す。
- `active` ノードは太枠 + 「いま」バッジ。
- SVG は `overflow-x: auto` のコンテナに入れ、横スクロールさせる。ページ本体は横スクロールさせない。

### 必ず保つもの（既存E2Eが依存）

- 各ノードに `data-topic-node-id={node.id}` と `data-topic-active={"true"|"false"}` を残す。
- 時刻ボタンの挙動（`onSeek` があれば押せる、無ければ disabled）を残す。SVG内は `<g>` +
  `role="button"` + `tabIndex` で実装してよい。
- ライブ（`TopicTree.tsx`）と履歴の両方が同じ描画コンポーネントを使う一本化を崩さない。

### React StrictMode の禁止事項

**レンダー中に共有stateを書き換えない。** 到達可能性・クラスタ計算・レイアウトは
すべて純関数としてレンダー内で完結させる。過去に共有 `Set` をレンダー中に書き換えて
二重レンダー時に全ノードが消える不具合を出している。`tsc` は通ってしまう。

## 5. 検証

- `pytest tests/` 全通過（`test_topic_tree.py` / `test_routes_topics.py` /
  `test_file_store_topics.py` / `test_topic_tracker.py` にリンクのケースを追加）
- 追加すべきテスト: リンクの重複排除 / 端点欠落で捨てられる / `reserve_ids` の端点remap /
  `links` 無しの旧JSONが読める / 不正 `type` が捨てられる / `select_tree_for_prompt` が
  端点の閉じたリンクだけ返す
- `npx tsc --noEmit` clean
- `tauri-app/e2e/topics.spec.ts` 全通過（必要ならリンク描画の assertion を追加）
- 既知の別件failure `live-ai.spec.ts` の speaker list retry は今回の対象外
