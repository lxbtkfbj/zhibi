"""仅给独立验收库灌入前五十章试整理结果，不调用任何模型。"""

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402,F401 Windows 事件循环策略
from app.config import get_settings  # noqa: E402
from app.db import make_engine, make_sessionmaker  # noqa: E402
from app.services.teardown_trial import ensure_trial_database, seed_trial  # noqa: E402


async def main(args):
    ensure_trial_database(get_settings().database_url)
    engine = make_engine()
    try:
        result = await seed_trial(make_sessionmaker(engine), args.book, args.directory)
        print(
            f"灌入完成：{result['cards']} 张试整理角色卡，整理到第 50 章；保护跳过 {len(result['skipped'])} 条。没有调用模型。"
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="只向独立库灌试整理设定，库名 zhibi 一律拒绝")
    parser.add_argument("--book", type=uuid.UUID, required=True)
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "data/拆书试验/逆天邪神前五十章/整理设定",
    )
    try:
        asyncio.run(main(parser.parse_args()))
    except Exception as exc:  # noqa: BLE001 不打印连接串和模型配置
        print(f"没能灌入：{getattr(exc, 'detail', str(exc))}", file=sys.stderr)
        sys.exit(1)
