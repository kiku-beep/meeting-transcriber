# 論点ノードのクリック詳細（design）

設計担当が確定した仕様。実装担当はこの文書だけを根拠に変更する。

## 目的

議論マップの四角をクリックしたら、その論点の中身が読めるようにする。ユーザーの要求は
2つに分かれる。

- status が `open`（未決）: **何が争点か** と **何が決まれば決着するか**
- status が `decided`（決定）: **どう決定したか**（結論と理由）

ラベルは15字上限なので、この情報は既存フィールドからは復元できない。LLMに別フィールドを
書かせる。

## データモデル（backend/core/topic_tree.py）

- `TopicNode` に `detail: str = ""` を足す。既定を空文字にすることで、既存の保存済み
  ツリー（detail を持たない）をそのまま読めること。
- `MAX_DETAIL_LEN = 120` を新設する。`MAX_LABEL_LEN` の隣に置く。

### 正規化 `_normalize_node`

- `detail` が str でなければ `""` に落とす。
- `strip()` してから `[:MAX_DETAIL_LEN]` で切る。
- 返す `TopicNode(...)` に `detail=` を必ず渡す（現在の実装はフィールドを明示列挙して
  再構築しているため、追記しないと detail が捨てられる）。

### 更新 `apply_patch` の update ループ

- `change` に `"detail"` があり、str かつ `strip()` が非空のときだけ
  `node.detail = stripped[:MAX_DETAIL_LEN]` で上書きする。
- **空文字や非strでは既存の detail を消さない。** LLMは update で detail を省略・空送信
  しがちで、消してしまうと「決定したのに理由が消える」挙動になる。

## プロンプト（build_patch_prompt）

schema 文字列を次のとおり拡張する。

- `add` の要素へ `"detail":"補足(120字以内)"` を追加。
- `update` の要素へ `"detail":"補足(120字以内)"` を追加。

指示文へ次を追加する（既存の指示は消さない。最後の「文字起こしにない内容を補わないで
ください。」の直前へ入れる）。

```
detail には label に入り切らない中身を1〜2文で書いてください。
status が open の detail は、何が対立点かと、何が決まれば決着するかを書いてください。
status が decided の detail は、何にどう決めたかと、その理由を書いてください。
status が parked の detail は、なぜ保留かと、再開の条件を書いてください。
status を open から decided へ update するときは、detail も決定内容へ書き換えてください。
detail は120字以内にしてください。文字起こしから読み取れないなら空文字にしてください。
```

## 型（tauri-app/src/lib/types.ts）

`TopicNode` に `detail?: string;` を足す。**optional にする**（古い保存ツリーとモックが
detail を持たないため、必須にすると型が実データと合わない）。

## ノード（tauri-app/src/components/topics/TopicNode.tsx）

- props へ `onSelect?: (nodeId: string) => void` と `selected?: boolean` を足す。
- クリック／Enter／Space で `onSelect?.(node.id)` と `onSeek?.(node.start_sec)` の両方を
  呼ぶ。onSeek が無くても選択は動くこと（ライブ画面は onSeek を渡さない）。
- `tabIndex` と `aria-disabled` の条件を `onSeek ? ... : ...` から
  `onSelect || onSeek` を持つかどうかに変える。ライブでもキーボードで選べるようにする。
- 選択中は `topic-node--selected` クラスと `data-topic-selected="true"` を付ける。
  `topic-node--active`（＝いま話している）とは別概念なので混ぜない。
- 選択中の rect は `stroke` を `#7c3aed`、`strokeWidth` を 3 にする。ただし
  `active` の金色（`#b7791f`）が優先。active かつ selected なら金色のまま。
- `aria-label` は `${label}（開始時刻 X:XX）` のまま変えない（E2Eが参照している）。

## 図（tauri-app/src/components/topics/TopicGraphView.tsx）

- `useState<string | null>` で `selectedId` を持つ。
- `renderNode` に `selectedId` と `onSelect` を渡す（引数追加）。
- ツリーが更新されても選択は保つ。選択中のidが `tree.nodes` から消えたらパネルを出さない
  （state のリセットは不要。描画時に `nodes.find` が undefined なら出さないだけにする。
  render中に setState してはいけない。StrictModeで二重描画されるため）。
- `<svg>` の空白クリックで選択解除する。`<svg onClick={() => setSelectedId(null)}>` を置く
  （TopicNode 側は既に `event.stopPropagation()` している）。
- パネルは `.topic-graph__canvas` の直後、`.topic-graph__legend` の直前へ置く。

### パネルの中身（`<aside className="topic-graph__detail" aria-label="論点の詳細">`）

1. ヘッダ行: kind のレーン名（問い／案・立場／制約／合意・保留）、status の文言
   （未決／決定／保留）、時刻範囲 `M:SS〜M:SS`（end が start 以下なら開始のみ）。
   右端に「閉じる」ボタン（`type="button"`、`onClick` で `setSelectedId(null)`）。
2. `<h3>` にラベル全文。
3. 本文: `detail` があればそれを表示。無ければ status に応じた案内を出す。
   - open: `まだ争点と決着条件を抽出できていません。`
   - decided: `決定の理由をまだ抽出できていません。`
   - parked: `保留の理由をまだ抽出できていません。`
4. 関係の一覧: この論点に繋がるリンクと親子を箇条書きにする。0件なら節ごと出さない。
   - 出ていくリンク: supports=`◯◯ を支持`、objects=`◯◯ に反論`、
     constrains=`◯◯ を制約`、depends=`◯◯ が前提`
   - 入ってくるリンク: supports=`◯◯ から支持されている`、objects=`◯◯ から反論されている`、
     constrains=`◯◯ に制約されている`、depends=`◯◯ の前提になっている`
   - 親: `◯◯ の中の論点`、子: `下位の論点: ◯◯`
   - `◯◯` は相手ノードの label。
   - 各項目はクリックでその論点へ選択を移せるボタンにする。

## CSS（tauri-app/src/App.css）

`.topic-graph__guard` の行の直後へ追加する。既存の変数（`--workspace-*`）を使う。

```
.topic-graph__detail { margin: 4px 4px 10px; padding: 10px 12px; border: 1px solid var(--workspace-border); border-radius: 8px; background: var(--workspace-bg); }
.topic-graph__detail-head { display: flex; align-items: center; gap: 8px; color: var(--workspace-muted); font-size: 11px; }
.topic-graph__detail-head button { margin-left: auto; }
.topic-graph__detail h3 { margin: 6px 0 4px; font-size: 14px; }
.topic-graph__detail-body { margin: 0; color: var(--workspace-text); font-size: 12px; line-height: 1.6; }
.topic-graph__detail-body--empty { color: var(--workspace-muted); }
.topic-graph__detail-relations { margin: 8px 0 0; padding: 0; list-style: none; display: grid; gap: 4px; font-size: 12px; }
.topic-graph__detail-relations button { padding: 0; border: 0; background: none; color: var(--workspace-accent); font: inherit; text-align: left; cursor: pointer; }
.topic-node--selected rect { stroke-dasharray: none; }
```

`--workspace-text` / `--workspace-accent` が定義済みか確認し、無ければ既存の近い変数へ
置き換えること（勝手に新しい変数を定義しない）。

## テスト

### backend（tests/）

既存の topic_tree のテストファイルへ追記する。新規ファイルは作らない。

1. `detail` を含む add がパースされ、120字超が切られること。
2. `detail` が非strのとき `""` になること。
3. update で `detail` を送ると上書きされること。
4. update で `detail` に空文字を送っても既存の detail が消えないこと。
5. `tree_from_dict` が detail の無い古いdictを読めて、detail が `""` になること。

### frontend E2E（tauri-app/e2e/topics.spec.ts）

`installApiRoutes` のモックツリーへ detail を持つノードと持たないノードを混ぜる。
テストを1本足す。

- 名前: `四角をクリックすると詳細が出る`
- 手順: 論点タブ → ノードのラベルをクリック → detail 本文が見えること →
  detail が無いノードをクリックすると案内文が出ること → 「閉じる」でパネルが消えること。

**注意**: E2Eの `page.getByText` は SVG の text も拾う。パネル内テキストと図のラベルが
衝突するので、パネル側は `page.getByRole("complementary")` などパネルへスコープしてから
探すこと。

## 禁止事項

- グラフライブラリ（mermaid / reactflow など）を入れない。依存追加は承認が要る。
- 既存のレイアウト計算（`calculateLayout` / `edgePath`）を変更しない。
- `MAX_LABEL_LEN` と既存プロンプト指示を消さない。
- 既存E2Eの選択子（`data-topic-node-id`、`topic-node--active`、`aria-label`）を壊さない。
