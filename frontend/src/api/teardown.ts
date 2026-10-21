import { ApiError, del, get, post } from './client'
import { useProfiles, useRoles } from './hooks'
import type { BookDetail, Job } from './types'
import type { TeardownAppendPreview, TeardownFields, TeardownPreview } from '../lib/teardownPreview'
import { teardownModelName } from '../lib/teardownStart'
import { hasEssence, type TeardownEssence } from '../pages/workspace/desk-v2/essenceData'

export type TeardownEncoding = 'auto' | 'utf-8' | 'gb18030' | 'utf-16' | 'big5'

export function useTeardownModel() {
  const profiles = useProfiles()
  const roles = useRoles()
  const ready = !!profiles.data && !!roles.data && !profiles.error && !roles.error
  return {
    ready,
    name: ready ? teardownModelName(profiles.data!, roles.data!) : '正在读取…',
    error: profiles.error || roles.error,
  }
}

/** fetch 没有上传进度；这里用同源 XHR，后台的 detail 保持原样显示。 */
export function uploadTeardown(file: File, onProgress: (percent: number) => void, signal?: AbortSignal): Promise<TeardownPreview> {
  return uploadTeardownFile('/api/teardown', file, onProgress, signal)
}

function uploadTeardownFile<T extends TeardownPreview>(url: string, file: File, onProgress: (percent: number) => void, signal?: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    let complete = false
    const abort = () => request.abort()
    const finish = (callback: () => void) => {
      if (complete) return
      complete = true
      signal?.removeEventListener('abort', abort)
      callback()
    }
    request.open('POST', url)
    request.upload.onprogress = event => {
      if (event.lengthComputable) onProgress(Math.round(event.loaded / event.total * 100))
    }
    request.onload = () => {
      let body: unknown
      try { body = JSON.parse(request.responseText) } catch { body = null }
      if (request.status >= 200 && request.status < 300) {
        finish(() => resolve(body as T))
        return
      }
      const detail = body && typeof body === 'object' && 'detail' in body ? body.detail : null
      const message = typeof detail === 'string' ? detail : `请求失败（${request.status}）`
      finish(() => reject(new ApiError(request.status, message)))
    }
    request.onerror = () => finish(() => reject(new Error('网络连接失败，请重试')))
    request.onabort = () => finish(() => reject(new DOMException('上传已取消', 'AbortError')))
    signal?.addEventListener('abort', abort, { once: true })
    if (signal?.aborted) {
      finish(() => reject(new DOMException('上传已取消', 'AbortError')))
      return
    }
    const form = new FormData()
    form.append('file', file)
    request.send(form)
  })
}

export const getTeardownPreview = (bookId: string) => get<TeardownPreview>(`/teardown/${bookId}/preview`)
export const changeTeardownEncoding = (bookId: string, encoding: TeardownEncoding, t2s?: boolean) => post<TeardownPreview>(`/teardown/${bookId}/encoding`, { encoding, ...(t2s === undefined ? {} : { t2s }) })
export const importTeardown = (bookId: string, fields: TeardownFields, include: number[], start?: { upto: number | null }) => post<BookDetail>(`/teardown/${bookId}/import`, { ...fields, include, ...(start ? { start } : {}) })
export const startTeardown = (bookId: string, upto: number | null) => post<Job>(`/teardown/${bookId}/start`, { upto })
export const stopTeardown = (bookId: string) => post<Job>(`/teardown/${bookId}/stop`)
export const getTeardownEssence = async (bookId: string): Promise<TeardownEssence | null> => {
  const { essence } = await get<{ essence: (Omit<TeardownEssence, 'upto'> & { upto: number | null }) | null }>(`/books/${bookId}/teardown/essence`)
  return hasEssence(essence) ? essence : null
}
export const uploadTeardownAppend = (bookId: string, file: File, onProgress: (percent: number) => void, signal?: AbortSignal) => uploadTeardownFile<TeardownAppendPreview>(`/api/teardown/${bookId}/append`, file, onProgress, signal)
export const getTeardownAppendPreview = (bookId: string) => get<TeardownAppendPreview>(`/teardown/${bookId}/append`)
export const changeTeardownAppendEncoding = (bookId: string, encoding: TeardownEncoding) => post<TeardownAppendPreview>(`/teardown/${bookId}/append/encoding`, { encoding })
export const importTeardownAppend = (bookId: string, include: number[], start?: { upto: number | null }) => post<BookDetail>(`/teardown/${bookId}/append/import`, { include, start: start ?? null })
export const cancelTeardownAppend = (bookId: string) => del(`/teardown/${bookId}/append`)
