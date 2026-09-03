import type { TopicTree as TopicTreeData } from "../../lib/types";
import TopicGraphView from "./TopicGraphView";

interface Props {
  tree: TopicTreeData;
  /** 与えると時刻から再生できる（履歴表示用）。ライブでは省略する。 */
  onSeek?: (seconds: number) => void;
}

/** ライブと履歴で共通利用する論点マップの入口。 */
export default function TopicTreeView({ tree, onSeek }: Props) {
  return <TopicGraphView tree={tree} onSeek={onSeek} />;
}
