import type { TopicNode as TopicNodeData, TopicTree as TopicTreeData } from "../../lib/types";
import TopicNode from "./TopicNode";

interface Props {
  tree: TopicTreeData;
  /** 与えると時刻ボタンからシークできる（履歴表示用）。ライブでは省略する。 */
  onSeek?: (seconds: number) => void;
}

/**
 * 論点ツリーの描画のみを担う。ライブ（TopicTree）と履歴（History）の両方から使う。
 *
 * 到達可能性の計算はここ1か所に集約する。以前これを子コンポーネント側の
 * レンダー中の共有 Set 書き換えで済ませていたため、React StrictMode の
 * 二重レンダーで2回目に何も描画されない不具合を出した。
 */
export default function TopicTreeView({ tree, onSeek }: Props) {
  const nodesById = new Set(tree.nodes.map((node) => node.id));
  const childrenByParent = new Map<string, TopicNodeData[]>();
  tree.nodes.forEach((node) => {
    if (node.parent === null) return;
    const children = childrenByParent.get(node.parent) ?? [];
    children.push(node);
    childrenByParent.set(node.parent, children);
  });
  const roots = tree.nodes.filter((node) => node.parent === null || !nodesById.has(node.parent));

  const reachable = new Set<string>();
  const stack = roots.map((node) => node.id);
  while (stack.length > 0) {
    const id = stack.pop() as string;
    if (reachable.has(id)) continue;
    reachable.add(id);
    (childrenByParent.get(id) ?? []).forEach((child) => stack.push(child.id));
  }

  // 循環だけで構成され roots から辿れないノードも取りこぼさず出す。
  // ただし各連結成分の入口だけを出す（全部を並べると子として描いたものが
  // もう一度トップレベルにも出て二重表示になる）。
  const detachedSeen = new Set<string>();
  const detached: TopicNodeData[] = [];
  tree.nodes.forEach((node) => {
    if (reachable.has(node.id) || detachedSeen.has(node.id)) return;
    detached.push(node);
    const walk = [node.id];
    while (walk.length > 0) {
      const id = walk.pop() as string;
      if (detachedSeen.has(id)) continue;
      detachedSeen.add(id);
      (childrenByParent.get(id) ?? []).forEach((child) => walk.push(child.id));
    }
  });

  return (
    <div className="topic-tree" role="tree" aria-label="論点ツリー">
      {[...roots, ...detached].map((node) => (
        <TopicNode
          key={node.id}
          node={node}
          childrenByParent={childrenByParent}
          activeId={tree.active}
          path={new Set()}
          onSeek={onSeek}
        />
      ))}
    </div>
  );
}
