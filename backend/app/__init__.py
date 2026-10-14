"""执笔后端。"""

import asyncio
import sys

# psycopg 的异步模式在 Windows 上需要 SelectorEventLoop（Docker/Linux 环境不受影响）
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
