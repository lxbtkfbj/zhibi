"""把真书分章，取前 N 章正文写成 json，给 run_read.py 用。

用 `python -I prep_chapters.py <TXT 路径> <章数> <输出 json>` 运行。
章号是拆的书里从 1 起的顺序号（不像正文、空的章不算），原书标题里的「第X章」只留章名（设计说明第 14.1 节第 4 条）。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "分章试验"))
from split_txt import split  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    source, count, out = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
    result = split(source.read_bytes())
    story = [p for p in result["chapters"] if not {"不像正文", "空的"} & set(p.flags)]
    skipped = [p.raw for p in result["chapters"][: len(story[:count]) + 10] if {"不像正文", "空的"} & set(p.flags)]
    rows = [{"index": i, "title": p.title, "raw": p.raw, "text": p.text} for i, p in enumerate(story[:count], start=1)]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"book": source.stem, "chapters": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    sizes = [len(r["text"]) for r in rows]
    print(f"全书 {len(result['chapters'])} 段，正文 {len(story)} 章；取前 {len(rows)} 章，共 {sum(sizes):,} 字，最长 {max(sizes):,}，最短 {min(sizes):,}")
    print("跳过的：", skipped)
    print("最后一章：", rows[-1]["raw"])


if __name__ == "__main__":
    main()
