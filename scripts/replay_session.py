"""Replay a saved session's transcript through TopicTracker for acceptance checks.

保存済みセッションの transcript.json を会議の進行順に TopicTracker へ流し込み、
実際のLLM応答で論点ツリーが育つかを確認する読み取り専用スクリプト。

モックでは「LLMが本当に論点を追えるか」が分からないため、受入検証はこれで行う。
セッションのファイルは読むだけで、書き込みは --out で指定したレポートのみ。

使い方:
    .venv\\Scripts\\python.exe scripts/replay_session.py <session_dir> [--window-sec 120]
        [--limit-sec 0] [--engine codex-cli] [--effort low] [--out report.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import Settings  # noqa: E402
from backend.core.topic_tracker import TopicTracker  # noqa: E402
from backend.core.topic_tree import tree_to_dict  # noqa: E402


def load_entries(session_dir: Path) -> list[dict]:
    path = session_dir / "transcript.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise SystemExit(f"unexpected transcript shape: {path}")
    return entries


def build_settings(args: argparse.Namespace) -> Settings:
    settings = Settings()
    settings.topic_tree_enabled = True
    # リプレイでは周期ループを使わず refresh_now を手で回すため interval は無関係
    settings.topic_tree_interval_s = 1.0
    settings.topic_tree_min_new_entries = args.min_new_entries
    settings.topic_tree_engine = args.engine
    settings.topic_tree_codex_reasoning_effort = args.effort
    return settings


async def replay(args: argparse.Namespace) -> dict:
    session_dir = Path(args.session_dir)
    all_entries = load_entries(session_dir)
    meta_path = session_dir / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    settings = build_settings(args)
    tracker = TopicTracker(settings)

    # refresh_now() は失敗を内部で飲んで False を返すため、戻り値だけでは
    # 「新規発話が足りない」と「LLMが壊れている」を区別できない。
    # リプレイが偽陰性（1回も回っていないのに成功に見える）にならないよう、
    # 先にプロバイダへ素の1回を投げて疎通を確かめる。
    try:
        await tracker._get_generator()("次の1語だけ返してください: OK")
    except Exception as exc:
        raise SystemExit(
            f"プロバイダに到達できません: {type(exc).__name__}: {exc}"
        ) from exc

    # 共有リスト。実運用では pipeline が append するのと同じ形
    live: list[dict] = []
    # start() は entries の登録と同時に周期ループも起動する。リプレイでは
    # refresh_now を手で回すため、起動直後に stop() でループだけ止める
    # （stop() は _entries と cursor を保持する）。両方走らせると同じ lock を
    # 奪い合い、どちらが更新したのか分からなくなる。
    tracker.start(live)
    await tracker.stop()

    duration = max(float(e.get("timestamp_end", 0) or 0) for e in all_entries)
    horizon = duration if args.limit_sec <= 0 else min(duration, args.limit_sec)

    print(
        f"session={meta.get('session_name') or session_dir.name} "
        f"entries={len(all_entries)} duration={duration / 60:.1f}min "
        f"replay_to={horizon / 60:.1f}min window={args.window_sec}s "
        f"engine={args.engine} effort={args.effort}",
        flush=True,
    )

    iterations: list[dict] = []
    fed = 0
    window_end = float(args.window_sec)
    total_wall = 0.0

    while window_end <= horizon + args.window_sec:
        batch = [
            e for e in all_entries[fed:]
            if float(e.get("timestamp_end", 0) or 0) <= window_end
        ]
        live.extend(batch)
        fed += len(batch)

        t0 = time.monotonic()
        try:
            updated = await tracker.refresh_now()
            error = None
        except Exception as exc:  # リプレイは1回の失敗で止めない
            updated = False
            error = f"{type(exc).__name__}: {exc}"
        wall = time.monotonic() - t0
        total_wall += wall

        tree = tracker.tree
        top_level = [n.label for n in tree.nodes if n.parent is None]
        active = next((n.label for n in tree.nodes if n.id == tree.active), None)
        row = {
            "at_min": round(window_end / 60, 1),
            "new_entries": len(batch),
            "updated": bool(updated),
            "wall_s": round(wall, 1),
            "nodes": len(tree.nodes),
            "top_level": len(top_level),
            "decided": sum(1 for n in tree.nodes if n.status == "decided"),
            "active": active,
            "error": error,
        }
        iterations.append(row)
        print(
            f"[{row['at_min']:>5.1f}min] +{row['new_entries']:>3d}発話 "
            f"updated={str(row['updated']):5s} {row['wall_s']:>5.1f}s "
            f"nodes={row['nodes']:>3d} top={row['top_level']:>2d} "
            f"decided={row['decided']:>2d} active={active}"
            + (f" ERROR {error}" if error else ""),
            flush=True,
        )
        window_end += args.window_sec

    await tracker.stop()

    tree = tracker.tree
    failures = [r for r in iterations if r["error"]]
    llm_rounds = [r for r in iterations if r["updated"] or r["error"]]
    walls = [r["wall_s"] for r in llm_rounds] or [0.0]
    report = {
        "session_id": meta.get("session_id") or session_dir.name,
        "session_name": meta.get("session_name"),
        "entry_count": len(all_entries),
        "duration_min": round(duration / 60, 1),
        "window_sec": args.window_sec,
        "engine": args.engine,
        "effort": args.effort,
        "iterations": iterations,
        "llm_rounds": len(llm_rounds),
        "failures": len(failures),
        "wall_total_s": round(total_wall, 1),
        "wall_max_s": round(max(walls), 1),
        "wall_mean_s": round(sum(walls) / len(walls), 1),
        "final_tree": tree_to_dict(tree),
    }

    if not report["llm_rounds"]:
        print(
            "\n*** 警告: LLMが1回も回っていない。この結果で合否を判断しないこと ***",
            flush=True,
        )
    print(
        f"\nrounds={report['llm_rounds']} failures={report['failures']} "
        f"nodes={len(tree.nodes)} wall_max={report['wall_max_s']}s "
        f"wall_mean={report['wall_mean_s']}s total={report['wall_total_s']}s",
        flush=True,
    )
    print("\n--- 最終ツリー（トップレベル） ---", flush=True)
    for node in tree.nodes:
        if node.parent is None:
            children = sum(1 for n in tree.nodes if n.parent == node.id)
            print(
                f"  [{node.status}] {node.label} "
                f"({node.start_sec / 60:.0f}-{node.end_sec / 60:.0f}min, 子{children})",
                flush=True,
            )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir")
    parser.add_argument("--window-sec", type=float, default=120.0)
    parser.add_argument("--limit-sec", type=float, default=0.0)
    parser.add_argument("--min-new-entries", type=int, default=5)
    parser.add_argument("--engine", default="codex-cli")
    parser.add_argument("--effort", default="low")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    report = asyncio.run(replay(args))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nreport -> {out}", flush=True)


if __name__ == "__main__":
    main()
