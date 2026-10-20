"""用法：uv run python scripts/teardown_rerun.py units --book <书 id>。"""

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402,F401 Windows psycopg 事件循环策略
from app.db import make_engine, make_sessionmaker  # noqa: E402
from app.services.job_runner import execute_job  # noqa: E402
from app.services.teardown_rerun import plan, prepare  # noqa: E402


async def main(args):
    engine = make_engine()
    sm = make_sessionmaker(engine)
    try:
        async with sm() as session:
            info = await plan(session, args.book, args.step, args.first, args.last)
        print(f"《{info['title']}》重跑 {args.step}，预计首轮调用 {info['calls']} 次模型。")
        print("格式修复、限流重试、未收尾的单元或卷会增加实际次数；只运行所选步骤。")
        if await asyncio.to_thread(input, "继续吗（输入「继续」）：") != "继续":
            print("已取消，没有改动。")
            return
        async with sm() as session:
            job = await prepare(session, args.book, args.step, args.first, args.last)
            job_id = job.id
        await execute_job(job_id)
        async with sm() as session:
            from app.models import Job

            result = await session.get(Job, job_id)
            if result.status != "succeeded":
                raise RuntimeError(f"重跑未完成：{result.error or result.status}")
        print(f"重跑完成，已存档「重跑：{args.step}」。")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="单独重跑拆书的一步（使用当前环境的数据库和拆书模型）")
    parser.add_argument("step", choices=("read", "units", "volumes", "settings", "merits"))
    parser.add_argument("--book", type=uuid.UUID, required=True)
    parser.add_argument("--from", dest="first", type=int)
    parser.add_argument("--to", dest="last", type=int)
    try:
        asyncio.run(main(parser.parse_args()))
    except Exception as exc:  # noqa: BLE001 命令行只给出一句原因，不吐连接参数或密钥
        print(f"没能重跑：{getattr(exc, 'detail', str(exc))}", file=sys.stderr)
        sys.exit(1)
