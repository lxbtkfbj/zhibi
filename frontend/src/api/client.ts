export class ApiError extends Error {
  status: number
  code?: string

  constructor(status: number, message: string, code?: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

function detailMessage(body: unknown, status: number): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object' && 'message' in detail) return String(detail.message)
    if (Array.isArray(detail) && detail.length) {
      const first = detail[0] as { msg?: string; loc?: unknown[] }
      return `参数不正确：${first.loc?.slice(1).join('.') ?? ''} ${first.msg ?? ''}`.trim()
    }
  }
  return `请求失败（${status}）`
}

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {}
  const response = await fetch(`/api${path}`, {
    ...rest,
    headers: { ...(json !== undefined ? { 'Content-Type': 'application/json' } : {}), ...rest.headers },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  })
  if (response.status === 204) return undefined as T
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, detailMessage(body, response.status), body?.detail?.code)
  return body as T
}

export const get = <T>(path: string) => api<T>(path)
export const post = <T>(path: string, json?: unknown) => api<T>(path, { method: 'POST', json: json ?? {} })
export const patch = <T>(path: string, json: unknown) => api<T>(path, { method: 'PATCH', json })
export const put = <T>(path: string, json: unknown) => api<T>(path, { method: 'PUT', json })
export const del = (path: string) => api<void>(path, { method: 'DELETE' })
