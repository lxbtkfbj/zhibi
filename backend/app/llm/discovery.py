"""只读获取 OpenAI 兼容接口的模型列表，不创建或修改模型配置。"""

import asyncio
import json
from urllib.parse import urlsplit

import httpx
from httpx import AsyncClient

from app.llm.router import LOCAL_HOSTS

REQUEST_TIMEOUT_S = 20
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class ModelDiscoveryError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


def normalize_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    try:
        parsed = urlsplit(normalized)
        url = httpx.URL(normalized)
        if (
            url.scheme not in {"http", "https"}
            or not url.host
            or parsed.username is not None
            or parsed.password is not None
            or "?" in normalized
            or "#" in normalized
            or "\\" in normalized
            or any(char.isspace() or ord(char) < 32 for char in normalized)
        ):
            raise ValueError
    except (ValueError, httpx.InvalidURL) as exc:
        raise ModelDiscoveryError("请填写有效的 HTTP / HTTPS 接口地址，不要包含账号、查询参数或片段", 422) from exc
    return normalized


def _parse_models(raw: bytes, status_code: int) -> list[str]:
    prefix = f"模型服务返回 HTTP {status_code}，但"
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ModelDiscoveryError(
            f"{prefix}内容不是有效 JSON，请检查接口地址是否指向 API；也可以手动填写模型名"
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ModelDiscoveryError(f"{prefix}模型列表格式不兼容（应包含 data 数组）；也可以手动填写模型名")
    models = list(
        dict.fromkeys(
            item["id"].strip()
            for item in payload["data"]
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
        )
    )
    if payload["data"] and not models:
        raise ModelDiscoveryError(f"{prefix}模型列表中没有有效模型名（id）；请手动填写模型名")
    return models


def _upstream_http_error(status_code: int) -> ModelDiscoveryError:
    # 只显示确定的 HTTP 状态及本地建议，不能将上游正文或重定向地址直接展示出来。
    reasons = {
        400: "模型列表请求被拒绝，请确认接口地址为 OpenAI 兼容 API 地址；也可以手动填写模型名",
        401: "认证失败，请检查 API Key 是否正确、是否过期，以及是否属于当前服务商",
        402: "请在服务商处检查账号额度或付费状态；也可以手动填写模型名",
        403: "访问被拒绝，当前 API Key、账号权限或访问策略不允许读取模型列表；请检查服务商的权限设置",
        404: "未找到 /models 接口，请检查接口地址及是否需要 /v1；该服务也可能不支持模型列表，可手动填写模型名",
        405: "该接口不允许 GET /models 请求，可能不支持模型列表查询；请手动填写模型名",
        408: "模型服务处理请求超时，请稍后重试；也可以手动填写模型名",
        422: "模型列表请求格式被拒绝，请确认接口支持 OpenAI 兼容的 GET /models；也可以手动填写模型名",
        429: "请求过于频繁或额度不足，请检查服务商限额并稍后重试；也可以手动填写模型名",
        501: "模型服务尚未实现模型列表接口，请手动填写模型名",
    }
    if 300 <= status_code < 400:
        reason = "接口要求重定向，为保护 API Key 未自动跳转；请填写最终的 API 接口地址"
    elif status_code in reasons:
        reason = reasons[status_code]
    elif status_code >= 500:
        reason = "模型服务或网关暂时无法处理请求，请稍后重试；也可以手动填写模型名"
    else:
        reason = "模型列表请求未成功，请检查接口地址及服务商的接口支持情况；也可以手动填写模型名"
    # 上游 404 等状态不能直接透传，否则前端无法区分本地旧版本缺少路由和上游不支持列表。
    return ModelDiscoveryError(f"模型服务返回 HTTP {status_code}：{reason}")


async def fetch_models(base_url: str, api_key: str = "") -> list[str]:
    base_url = normalize_base_url(base_url)
    # 不把 Key 放进 URL，也不将上游错误正文回传，避免泄漏凭据。
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with (
            asyncio.timeout(REQUEST_TIMEOUT_S),
            AsyncClient(
                timeout=httpx.Timeout(15, connect=5),
                follow_redirects=False,
                trust_env=urlsplit(base_url).hostname not in LOCAL_HOSTS,
            ) as client,
            client.stream("GET", f"{base_url}/models", headers=headers) as response,
        ):
            if not response.is_success:
                raise _upstream_http_error(response.status_code)
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ModelDiscoveryError(
                        f"模型服务返回 HTTP {response.status_code}，但模型列表过大，请手动填写模型名"
                    )
    except (TimeoutError, httpx.TimeoutException) as exc:
        raise ModelDiscoveryError("获取模型列表超时，请检查接口地址或稍后重试", 504) from exc
    except httpx.ProxyError as exc:
        raise ModelDiscoveryError("连接代理失败，尚未收到模型服务的有效响应；请检查系统代理设置") from exc
    except httpx.ConnectError as exc:
        raise ModelDiscoveryError(
            "无法建立模型服务连接，尚未收到 HTTP 响应；请检查接口域名、端口、网络/代理和 TLS 证书"
        ) from exc
    except httpx.RemoteProtocolError as exc:
        raise ModelDiscoveryError("模型服务连接中断或返回无效 HTTP 响应，请检查接口地址或稍后重试") from exc
    except (httpx.HTTPError, UnicodeError, ValueError) as exc:
        raise ModelDiscoveryError("无法连接模型服务，请检查接口地址、API Key 和网络连接") from exc
    return _parse_models(bytes(raw), response.status_code)
