import { useId } from "react";
import type { ReactNode } from "react";
import type {
  TopicKind,
  TopicLink,
  TopicLinkType,
  TopicNode as TopicNodeData,
  TopicTree as TopicTreeData,
} from "../../lib/types";
import TopicNode, { BOX_HEIGHT, BOX_WIDTH, type TopicNodePosition } from "./TopicNode";

interface Props {
  tree: TopicTreeData;
  /** 与えるとノードの開始時刻からシークできる（履歴表示用）。 */
  onSeek?: (seconds: number) => void;
}

const LANE_KINDS: TopicKind[] = ["question", "claim", "constraint", "decision"];
const LANE_LABELS: Record<TopicKind, string> = {
  question: "問い",
  claim: "案・立場",
  constraint: "制約",
  decision: "合意・保留",
};
const LANE_HEIGHT = 110;
const NODE_X_INTERVAL = 180;
const GRAPH_LEFT = 32;
/** 同一レーン内リンクが箱の下へ張り出す最大量。SVGの高さ余白もこれで決める。 */
const SAME_LANE_SAG_MAX = 48;
/** 「いま」バッジを箱の上端へまたがせるため、最上段レーンの上に空ける余白。 */
const GRAPH_TOP = 14;

const LINK_LABELS: Record<TopicLinkType, string> = {
  supports: "支持",
  objects: "反論",
  constrains: "制約",
  depends: "前提",
};

const LINK_META: Record<TopicLinkType, { stroke: string; dash?: string }> = {
  supports: { stroke: "#16803c" },
  objects: { stroke: "#c53030" },
  constrains: { stroke: "#c53030", dash: "6 4" },
  depends: { stroke: "#6b7280", dash: "6 4" },
};

interface TopicGraphLayout {
  positions: Map<string, TopicNodePosition>;
  width: number;
  height: number;
}

function isTopicKind(value: unknown): value is TopicKind {
  return value === "question" || value === "claim" || value === "constraint" || value === "decision";
}

function isTopicLinkType(value: unknown): value is TopicLinkType {
  return value === "supports" || value === "objects" || value === "constrains" || value === "depends";
}

function nodeKind(node: TopicNodeData): TopicKind {
  return isTopicKind(node.kind) ? node.kind : "question";
}

function finiteStart(node: TopicNodeData): number {
  return Number.isFinite(node.start_sec) ? node.start_sec : 0;
}

function validLinks(tree: TopicTreeData): TopicLink[] {
  const nodeIds = new Set(tree.nodes.map((node) => node.id));
  const rawLinks = Array.isArray(tree.links) ? tree.links : [];
  return rawLinks.filter((link): link is TopicLink => (
    typeof link?.source === "string"
    && typeof link?.target === "string"
    && link.source !== link.target
    && nodeIds.has(link.source)
    && nodeIds.has(link.target)
    && isTopicLinkType(link.type)
  ));
}

function buildLinkNeighbors(nodes: TopicNodeData[], links: TopicLink[]): Map<string, string[]> {
  const neighbors = new Map<string, string[]>();
  nodes.forEach((node) => neighbors.set(node.id, []));
  links.forEach((link) => {
    neighbors.get(link.source)?.push(link.target);
    neighbors.get(link.target)?.push(link.source);
  });
  return neighbors;
}

function findParentRootId(node: TopicNodeData, nodesById: Map<string, TopicNodeData>): string | null {
  const seen = new Set<string>();
  let current: TopicNodeData | undefined = node;
  while (current) {
    if (seen.has(current.id)) return null;
    seen.add(current.id);
    if (current.parent === null) return current.id;
    current = nodesById.get(current.parent);
  }
  return null;
}

function findLinkedQuestionId(
  node: TopicNodeData,
  nodesById: Map<string, TopicNodeData>,
  neighbors: Map<string, string[]>,
  nodeOrder: Map<string, number>,
): string | null {
  const visited = new Set<string>();
  const queue = [node.id];
  const questions: TopicNodeData[] = [];
  while (queue.length > 0) {
    const id = queue.shift();
    if (!id || visited.has(id)) continue;
    visited.add(id);
    const current = nodesById.get(id);
    if (current && nodeKind(current) === "question") questions.push(current);
    (neighbors.get(id) ?? []).forEach((neighborId) => {
      if (!visited.has(neighborId)) queue.push(neighborId);
    });
  }
  questions.sort((left, right) => (nodeOrder.get(left.id) ?? 0) - (nodeOrder.get(right.id) ?? 0));
  return questions[0]?.id ?? null;
}

function clusterIdFor(
  node: TopicNodeData,
  nodesById: Map<string, TopicNodeData>,
  neighbors: Map<string, string[]>,
  nodeOrder: Map<string, number>,
): string {
  return findParentRootId(node, nodesById)
    ?? findLinkedQuestionId(node, nodesById, neighbors, nodeOrder)
    ?? node.id;
}

function calculateLayout(tree: TopicTreeData): TopicGraphLayout {
  const nodesById = new Map(tree.nodes.map((node) => [node.id, node]));
  const nodeOrder = new Map(tree.nodes.map((node, index) => [node.id, index]));
  const links = validLinks(tree);
  const neighbors = buildLinkNeighbors(tree.nodes, links);
  const buckets = new Map<TopicKind, TopicNodeData[]>(LANE_KINDS.map((kind) => [kind, []]));

  tree.nodes.forEach((node) => {
    buckets.get(nodeKind(node))?.push(node);
  });

  // クラスタごとに横帯を確保し、帯の中で各レーンの行を中央寄せする。
  // レーンごとに左詰めすると、論点とその案・制約が横へズレて塊として読めない
  // （実装前のレイアウトモックで確認済み）。
  const clusterOf = new Map<string, string>();
  const clusterIds: string[] = [];
  tree.nodes.forEach((node) => {
    const clusterId = clusterIdFor(node, nodesById, neighbors, nodeOrder);
    clusterOf.set(node.id, clusterId);
    if (!clusterIds.includes(clusterId)) clusterIds.push(clusterId);
  });

  const positions = new Map<string, TopicNodePosition>();
  let columns = 0;
  clusterIds.forEach((clusterId) => {
    const lanes = LANE_KINDS.map((kind) => (
      (buckets.get(kind) ?? [])
        .filter((node) => clusterOf.get(node.id) === clusterId)
        .sort((left, right) => finiteStart(left) - finiteStart(right))
    ));
    const bandWidth = Math.max(1, ...lanes.map((list) => list.length));
    lanes.forEach((list, lane) => {
      const offset = (bandWidth - list.length) / 2;
      list.forEach((node, index) => {
        positions.set(node.id, {
          x: GRAPH_LEFT + (columns + offset + index) * NODE_X_INTERVAL,
          y: GRAPH_TOP + lane * LANE_HEIGHT,
        });
      });
    });
    columns += bandWidth;
  });

  return {
    positions,
    width: GRAPH_LEFT + Math.max(BOX_WIDTH, columns * NODE_X_INTERVAL) + 16,
    // 最下段レーン内のリンクは箱の下へ弧を張るため、その分の余白を残す。
    height: GRAPH_TOP + (LANE_KINDS.length - 1) * LANE_HEIGHT + BOX_HEIGHT + SAME_LANE_SAG_MAX + 8,
  };
}

function buildChildrenByParent(nodes: TopicNodeData[]): Map<string, TopicNodeData[]> {
  const childrenByParent = new Map<string, TopicNodeData[]>();
  nodes.forEach((node) => {
    if (node.parent === null) return;
    const children = childrenByParent.get(node.parent) ?? [];
    children.push(node);
    childrenByParent.set(node.parent, children);
  });
  return childrenByParent;
}

function findRenderRoots(nodes: TopicNodeData[], childrenByParent: Map<string, TopicNodeData[]>): TopicNodeData[] {
  const nodeIds = new Set(nodes.map((node) => node.id));
  const roots = nodes.filter((node) => node.parent === null || !nodeIds.has(node.parent));
  const reachable = new Set<string>();
  const markReachable = (start: TopicNodeData) => {
    const stack = [start.id];
    while (stack.length > 0) {
      const id = stack.pop();
      if (!id || reachable.has(id)) continue;
      reachable.add(id);
      (childrenByParent.get(id) ?? []).forEach((child) => stack.push(child.id));
    }
  };
  roots.forEach(markReachable);

  const detachedSeen = new Set<string>();
  const detached: TopicNodeData[] = [];
  nodes.forEach((node) => {
    if (reachable.has(node.id) || detachedSeen.has(node.id)) return;
    detached.push(node);
    const stack = [node.id];
    while (stack.length > 0) {
      const id = stack.pop();
      if (!id || detachedSeen.has(id)) continue;
      detachedSeen.add(id);
      (childrenByParent.get(id) ?? []).forEach((child) => stack.push(child.id));
    }
  });
  return [...roots, ...detached];
}

function hasParentCycle(nodes: TopicNodeData[]): boolean {
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  return nodes.some((node) => findParentRootId(node, nodesById) === null && nodesById.has(node.parent ?? ""));
}

function edgePath(source: TopicNodePosition, target: TopicNodePosition): string {
  const sourceCenterX = source.x + BOX_WIDTH / 2;
  const targetCenterX = target.x + BOX_WIDTH / 2;

  if (source.y === target.y) {
    // 同一レーン（案どうしの反論など）は箱の下を回る弧にする。直線だと間の箱を
    // 貫き、縦ベジェだと潰れて線が見えない（レイアウトモックで確認済み）。
    const baseY = source.y + BOX_HEIGHT;
    const sag = Math.min(SAME_LANE_SAG_MAX, 20 + Math.abs(targetCenterX - sourceCenterX) * 0.1);
    return `M ${sourceCenterX} ${baseY} C ${sourceCenterX} ${baseY + sag}, ${targetCenterX} ${baseY + sag}, ${targetCenterX} ${baseY}`;
  }

  const downward = target.y > source.y;
  const startY = downward ? source.y + BOX_HEIGHT : source.y;
  const endY = downward ? target.y : target.y + BOX_HEIGHT;
  // 2レーン以上跨ぐ線は制御点を横へ膨らませ、間のレーンの箱を貫かせない。
  const laneSpan = Math.abs(target.y - source.y) / LANE_HEIGHT;
  const bow = laneSpan > 1 ? (targetCenterX >= sourceCenterX ? 1 : -1) * (BOX_WIDTH / 2 + 26) : 0;
  const halfDy = (endY - startY) * 0.5;
  return `M ${sourceCenterX} ${startY} C ${sourceCenterX + bow} ${startY + halfDy}, ${targetCenterX + bow} ${endY - halfDy}, ${targetCenterX} ${endY}`;
}

function renderNode(
  node: TopicNodeData,
  childrenByParent: Map<string, TopicNodeData[]>,
  layout: TopicGraphLayout,
  activeId: string | null,
  onSeek: Props["onSeek"],
  path: Set<string> = new Set(),
): ReactNode {
  const position = layout.positions.get(node.id);
  if (!position || path.has(node.id)) return null;
  const nextPath = new Set(path);
  nextPath.add(node.id);
  return (
    <TopicNode
      key={node.id}
      node={node}
      position={position}
      active={activeId === node.id}
      onSeek={onSeek}
    >
      {(childrenByParent.get(node.id) ?? []).map((child) => renderNode(
        child,
        childrenByParent,
        layout,
        activeId,
        onSeek,
        nextPath,
      ))}
    </TopicNode>
  );
}

export default function TopicGraphView({ tree, onSeek }: Props) {
  const markerId = `topic-arrow-${useId().replace(/:/g, "")}`;
  const layout = calculateLayout(tree);
  const links = validLinks(tree);
  const childrenByParent = buildChildrenByParent(tree.nodes);
  const roots = findRenderRoots(tree.nodes, childrenByParent);
  const cycleDetected = hasParentCycle(tree.nodes);

  return (
    <div className="topic-graph" role="tree" aria-label="論点マップ">
      {cycleDetected && <div className="topic-graph__guard" role="note">循環を検出しました</div>}
      <div className="topic-graph__canvas">
        <svg
          className="topic-graph__svg"
          width={layout.width}
          height={layout.height}
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          aria-label="論点の関係図"
        >
          <defs>
            <marker
              id={markerId}
              markerWidth="8"
              markerHeight="8"
              refX="7"
              refY="4"
              orient="auto"
              markerUnits="strokeWidth"
            >
              <path d="M 0 0 L 8 4 L 0 8 z" fill="context-stroke" />
            </marker>
          </defs>
          <g className="topic-graph__lanes" aria-hidden="true">
            {LANE_KINDS.map((kind, lane) => (
              <text
                key={kind}
                x={4}
                y={GRAPH_TOP + lane * LANE_HEIGHT + 16}
                className="topic-graph__lane-label"
              >
                {LANE_LABELS[kind]}
              </text>
            ))}
          </g>
          <g className="topic-graph__edges" aria-hidden="true">
            {links.map((link, index) => {
              const source = layout.positions.get(link.source);
              const target = layout.positions.get(link.target);
              if (!source || !target) return null;
              const meta = LINK_META[link.type];
              return (
                <path
                  key={`${link.source}-${link.target}-${link.type}-${index}`}
                  d={edgePath(source, target)}
                  fill="none"
                  stroke={meta.stroke}
                  strokeDasharray={meta.dash}
                  strokeWidth="1.7"
                  markerEnd={`url(#${markerId})`}
                />
              );
            })}
          </g>
          <g className="topic-graph__nodes">
            {roots.map((node) => renderNode(node, childrenByParent, layout, tree.active, onSeek))}
          </g>
        </svg>
      </div>
      <div className="topic-graph__legend" aria-label="論点マップの凡例">
        {LANE_KINDS.map((kind) => <span key={kind}><i className={`topic-graph__legend-dot topic-graph__legend-dot--${kind}`} />{LANE_LABELS[kind]}</span>)}
        {(Object.keys(LINK_META) as TopicLinkType[]).map((type) => (
          <span key={type}>
            <i className={`topic-graph__legend-line topic-graph__legend-line--${type}`} />
            {LINK_LABELS[type]}
          </span>
        ))}
      </div>
    </div>
  );
}

export { calculateLayout, validLinks };
