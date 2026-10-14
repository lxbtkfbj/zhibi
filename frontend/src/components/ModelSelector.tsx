import { Check, ChevronDown, Download } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import { Button, inputClass } from './ui'

type Connection = { baseUrl: string; apiKey: string; profileId?: string }
type ModelRequest = Connection & (
  | { status: 'loading' }
  | { status: 'success'; models: string[] }
  | { status: 'error'; message: string }
)

function discoveryErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404 && /^(not found|请求失败（404）)$/i.test(error.message.trim())) {
      return '本地后端缺少模型列表接口（HTTP 404）。请重启执笔后重试；这不是密钥校验失败。'
    }
    if (error.status === 404 && error.message === '模型配置不存在') {
      return '当前模型配置已不存在（HTTP 404），请关闭窗口后重新选择或添加配置。'
    }
    return error.message
  }
  if (error instanceof TypeError) return '无法连接本地后端，请确认执笔服务已启动，再重试获取模型列表。'
  return '获取模型列表失败，请稍后重试；也可以手动填写模型名。'
}

/** A free-text model name, with optional discovery; the list never restricts manual input. */
export function ModelSelector({
  value, onChange, baseUrl, apiKey, profileId,
}: Connection & { value: string; onChange: (value: string) => void }) {
  const id = useId()
  const container = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const list = useRef<HTMLUListElement>(null)
  const controller = useRef<AbortController | null>(null)
  const [request, setRequest] = useState<ModelRequest | null>(null)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)

  // A response belongs only to the exact connection that requested it. Changing
  // credentials immediately hides the old list, even before effect cleanup runs.
  const current = request?.baseUrl === baseUrl && request.apiKey === apiKey && request.profileId === profileId
    ? request : null
  if (request && !current) {
    // Discard the previous connection's state before rendering its children.
    // Returning to that URL/key must not resurrect an aborted loading state.
    setRequest(null)
    setOpen(false)
    setActive(-1)
  }
  const models = current?.status === 'success' ? current.models : []
  const query = value.trim().toLowerCase()
  const filtered = models.filter((model) => model.toLowerCase().includes(query))
  const expanded = open && models.length > 0
  const loading = current?.status === 'loading'

  useEffect(() => () => controller.current?.abort(), [baseUrl, apiKey, profileId])
  useEffect(() => {
    if (expanded) list.current?.parentElement?.scrollIntoView({ block: 'nearest' })
  }, [expanded])
  useEffect(() => {
    if (!expanded) return
    // Wait for the outside click to complete before collapsing the in-flow list.
    // Closing on blur would move the modal's Save button between down and up.
    const dismiss = (event: MouseEvent) => {
      if (event.target instanceof Node && !container.current?.contains(event.target)) setOpen(false)
    }
    document.addEventListener('click', dismiss)
    return () => document.removeEventListener('click', dismiss)
  }, [expanded])
  useEffect(() => {
    if (expanded && active >= 0) list.current?.children[active]?.scrollIntoView({ block: 'nearest' })
  }, [active, expanded])

  const fetchModels = async () => {
    controller.current?.abort()
    const pending = new AbortController()
    controller.current = pending
    const source = { baseUrl, apiKey, profileId }
    setRequest({ ...source, status: 'loading' })
    setOpen(false)
    setActive(-1)
    try {
      const result = await api<{ models: string[] }>('/llm/models', {
        method: 'POST',
        json: { base_url: baseUrl.trim(), api_key: apiKey, profile_id: profileId },
        signal: pending.signal,
      })
      if (pending.signal.aborted || controller.current !== pending) return
      setRequest({ ...source, status: 'success', models: result.models })
      setOpen(true)
      input.current?.focus({ preventScroll: true })
    } catch (error) {
      if (pending.signal.aborted || controller.current !== pending) return
      setRequest({ ...source, status: 'error', message: discoveryErrorMessage(error) })
    }
  }

  const select = (model: string) => {
    onChange(model)
    setOpen(false)
    setActive(-1)
    input.current?.focus({ preventScroll: true })
  }

  return (
    <div ref={container} onKeyDown={(event) => { if (event.key === 'Tab') setOpen(false) }}>
      <div className="mb-1.5 flex items-center justify-between gap-3">
        <label htmlFor={id} className="text-sm font-medium text-ink-2">模型名</label>
        <Button size="sm" className="w-32" style={{ transform: 'none' }} onClick={fetchModels} loading={loading} disabled={!baseUrl.trim()}>
          {!loading && <Download className="size-3.5" />}
          {loading ? '正在获取…' : '获取模型列表'}
        </Button>
      </div>
      <div className="relative">
        <input
          ref={input}
          id={id}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={expanded}
          aria-controls={expanded ? `${id}-list` : undefined}
          aria-activedescendant={expanded && active >= 0 && active < filtered.length ? `${id}-option-${active}` : undefined}
          aria-describedby={`${id}-hint ${id}-status`}
          autoComplete="off"
          value={value}
          onChange={(event) => { onChange(event.target.value); setOpen(true); setActive(-1) }}
          onFocus={() => { setOpen(true); setActive(-1) }}
          onKeyDown={(event) => {
            if (event.nativeEvent.isComposing) return
            if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && filtered.length > 0) {
              event.preventDefault()
              setOpen(true)
              setActive(event.key === 'ArrowDown'
                ? (expanded ? active + 1 : 0) % filtered.length
                : (expanded && active >= 0 ? active - 1 + filtered.length : filtered.length - 1) % filtered.length)
            } else if (event.key === 'Enter' && expanded && filtered[active]) {
              event.preventDefault()
              select(filtered[active])
            } else if (event.key === 'Escape' && expanded) {
              event.preventDefault()
              event.stopPropagation()
              setOpen(false)
            }
          }}
          className={`${inputClass} h-11 pr-11`}
          placeholder="输入模型名，或获取列表后搜索"
        />
        {models.length > 0 && (
          <button
            type="button"
            aria-label={expanded ? '收起模型列表' : '展开模型列表'}
            aria-expanded={expanded}
            aria-controls={expanded ? `${id}-list` : undefined}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => {
              input.current?.focus({ preventScroll: true })
              setOpen(!expanded)
              setActive(-1)
            }}
            className="absolute top-0 right-0 flex h-11 w-11 items-center justify-center rounded-r-xl text-ink-3 hover:text-ink focus-visible:outline-2 focus-visible:outline-seal"
          >
            <ChevronDown className={`size-4 transition-transform ${expanded ? 'rotate-180' : ''}`} />
          </button>
        )}
        {expanded && (
          <div className="mt-2 overflow-hidden rounded-xl border border-line-2 bg-card shadow-[var(--shadow-panel)]">
            <div className="border-b border-line px-3.5 py-2 text-xs text-ink-3">
              {query ? `匹配 ${filtered.length} / ${models.length} 个模型` : `共 ${models.length} 个模型`}
            </div>
            <ul ref={list} id={`${id}-list`} role="listbox" aria-label="可用模型" className="scroll-thin max-h-52 overflow-y-auto py-1">
              {filtered.map((model, index) => (
                <li
                  key={model}
                  id={`${id}-option-${index}`}
                  role="option"
                  aria-selected={model === value}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseMove={() => setActive(index)}
                  onClick={() => select(model)}
                  className={`flex cursor-pointer items-start gap-2 px-3.5 py-2 text-sm ${active === index ? 'bg-paper text-ink' : 'text-ink-2 hover:bg-paper-2'}`}
                >
                  <span className="min-w-0 flex-1 break-all">{model}</span>
                  {model === value && <Check className="mt-0.5 size-4 shrink-0 text-lore" />}
                </li>
              ))}
            </ul>
            {filtered.length === 0 && <p className="px-3.5 pb-3 pt-1 text-sm text-ink-3">没有匹配的模型，可继续手动填写。</p>}
          </div>
        )}
      </div>
      <p id={`${id}-hint`} className="mt-1.5 text-xs leading-5 text-ink-3">输入部分名称筛选，也可直接填写完整模型名。</p>
      <div id={`${id}-status`} aria-live="polite" className="min-h-15 text-xs leading-5">
        {!baseUrl.trim() && <p className="text-ink-3">先填写接口地址，即可获取可用模型。</p>}
        {loading && <p className="text-ink-3">正在获取模型列表，请稍候…</p>}
        {current?.status === 'success' && <p className="text-ink-3">{models.length ? `已获取 ${models.length} 个模型` : '接口未返回可用模型，请手动填写模型名。'}</p>}
        {current?.status === 'error' && <p className="break-words text-seal">{current.message}</p>}
      </div>
    </div>
  )
}
