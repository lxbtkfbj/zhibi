import asyncio
import socket
from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pymilvus import MilvusClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep, get_redis
from app.config import get_settings

router = APIRouter(tags=["health"])


def _check_milvus() -> str:
    uri = urlparse(get_settings().milvus_uri)
    # 先快速探测端口，Milvus 没启动时不必等客户端超时
    with socket.create_connection((uri.hostname or "127.0.0.1", uri.port or 19530), timeout=0.5):
        pass
    client = MilvusClient(uri=get_settings().milvus_uri, timeout=3)
    try:
        return client.get_server_version()
    finally:
        client.close()


@router.get("/health")
async def health(session: AsyncSession = SessionDep, redis: Redis = Depends(get_redis)) -> JSONResponse:
    components: dict[str, dict] = {}
    try:
        version = await session.scalar(text("SHOW server_version"))
        components["postgres"] = {"ok": True, "detail": version}
    except Exception as exc:  # noqa: BLE001
        components["postgres"] = {"ok": False, "detail": str(exc)}
    try:
        await redis.ping()
        components["redis"] = {"ok": True, "detail": "PONG"}
    except Exception as exc:  # noqa: BLE001
        components["redis"] = {"ok": False, "detail": str(exc)}
    try:
        version = await asyncio.wait_for(asyncio.to_thread(_check_milvus), timeout=5)
        components["milvus"] = {"ok": True, "detail": version}
    except Exception as exc:  # noqa: BLE001  第 3 步之前 Milvus 可以不启动
        components["milvus"] = {"ok": False, "detail": f"未连接（第 3 步原文检索才需要）：{type(exc).__name__}"}
    core_ok = components["postgres"]["ok"] and components["redis"]["ok"]
    return JSONResponse(
        {"status": "ok" if core_ok else "error", "components": components}, status_code=200 if core_ok else 503
    )
