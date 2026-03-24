#!/usr/bin/env python3
"""Merge Transcriber dictionary entries into Aqua Dictation dictionary.

Usage:
    python merge_dictionaries.py           # Dry-run (report only)
    python merge_dictionaries.py --apply   # Actually merge
"""

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

TRANSCRIBER_DICT = Path(r"E:\transcriber\data\dictionary.json")
AQUA_DICT = Path(r"C:\Users\faker\AppData\Roaming\aqua-dictation\dictionary.json")


def load_dict(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_dict(path: Path, data: dict) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    apply = "--apply" in sys.argv

    if not TRANSCRIBER_DICT.exists():
        print(f"ERROR: Transcriber dictionary not found: {TRANSCRIBER_DICT}")
        sys.exit(1)
    if not AQUA_DICT.exists():
        print(f"ERROR: Aqua Dictation dictionary not found: {AQUA_DICT}")
        sys.exit(1)

    trans = load_dict(TRANSCRIBER_DICT)
    aqua = load_dict(AQUA_DICT)

    trans_replacements = trans.get("replacements", [])
    aqua_replacements = aqua.get("replacements", [])

    print(f"Transcriber: {len(trans_replacements)} replacements")
    print(f"Aqua Dictation: {len(aqua_replacements)} replacements")
    print()

    aqua_pairs = {(r["from"], r["to"]) for r in aqua_replacements}
    aqua_froms = {r["from"] for r in aqua_replacements}

    unique = []
    conflicts = []
    already_exists = []

    for r in trans_replacements:
        pair = (r["from"], r["to"])
        if pair in aqua_pairs:
            already_exists.append(r)
        elif r["from"] in aqua_froms:
            aqua_tos = [ar["to"] for ar in aqua_replacements if ar["from"] == r["from"]]
            conflicts.append((r, aqua_tos))
        else:
            unique.append(r)

    print(f"Already in Aqua (exact match): {len(already_exists)}")
    print(f"Unique to Transcriber: {len(unique)}")
    print(f"Conflicts (same from, different to): {len(conflicts)}")
    print()

    if unique:
        print("=== Unique entries to add ===")
        for r in unique:
            print(f"  {r['from']} -> {r['to']}")
        print()

    if conflicts:
        print("=== Conflicts (NOT merged, review manually) ===")
        for r, aqua_tos in conflicts:
            print(f"  {r['from']}: Transcriber={r['to']} | Aqua={aqua_tos}")
        print()

    if not unique:
        print("Nothing to merge. All Transcriber entries exist in Aqua.")
        return

    if not apply:
        print(f"Dry-run complete. Use --apply to add {len(unique)} entries.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = AQUA_DICT.with_name(f"dictionary_backup_{timestamp}.json")
    shutil.copy2(AQUA_DICT, backup_path)
    print(f"Backup created: {backup_path}")

    for r in unique:
        entry = {
            "from": r["from"],
            "to": r["to"],
            "case_sensitive": r.get("case_sensitive", False),
            "enabled": r.get("enabled", True),
            "is_regex": r.get("is_regex", False),
            "note": r.get("note", ""),
            "auto_learned": r.get("auto_learned", False),
            "confidence": r.get("confidence", 1.0),
            "occurrence_count": r.get("occurrence_count", 0),
        }
        aqua_replacements.append(entry)

    aqua["replacements"] = aqua_replacements
    save_dict(AQUA_DICT, aqua)
    print(f"Merged {len(unique)} entries. Aqua now has {len(aqua_replacements)} replacements.")


if __name__ == "__main__":
    main()
