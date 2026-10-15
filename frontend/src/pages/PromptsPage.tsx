import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { useRef, useState } from 'react'
import { useBooks } from '../api/hooks'
import { promptApi, type PromptDetail, type PromptInfo } from '../api/prompts'
import { PromptEditor, type PromptEditorHandle } from '../components/PromptEditor'
import { ErrorText, Sheet } from '../components/ui'
import { SettingsButton } from '../components/settings/SettingsList'
import { ROLE_META } from '../lib/roles'
import { readPromptDraft, writePromptDraft } from '../lib/promptDrafts'
import './prompts.css'

const roleName = (role: string) => role === 'all' ? '全体成员' : role.split(',').map(name => ROLE_META[name as keyof typeof ROLE_META]?.name ?? name).join('、')
const timestamp = (date: string | null) => date ? new Date(date).toLocaleString('zh-CN', { hour12: false }) : '尚未调用'
const number = (value: number | null) => value == null ? '—' : value.toLocaleString('zh-CN')

function CallDetail({ id, onClose }: { id: number | null; onClose: () => void }) {
  const query = useQuery({ queryKey: ['llm-call', id], queryFn: () => promptApi.call(id!), enabled: id !== null })
  const call = query.data
  return <Sheet open={id !== null} onClose={onClose} title="调用详情">
    <ErrorText error={query.error} />
    {query.isLoading && <p className="text-sm text-ink-2">正在读取调用记录…</p>}
    {call && <div className="call-detail space-y-5">
      <p className="text-xs leading-relaxed text-ink-2">{timestamp(call.created_at)} · {roleName(call.role)} · {call.purpose}<br />{call.model} · {call.request?.method ?? '历史记录'}</p>
      {!call.request && <p className="text-sm text-ink-2">这次调用的完整内容未留存（历史记录或已超出最近 2000 次）。统计信息仍保留。</p>}
      <section><h3>系统提示</h3><pre>{call.request?.system ?? '—'}</pre></section>
      <section><h3>用户提示</h3><pre>{call.request?.user ?? '—'}</pre></section>
      <details><summary>结构说明（模型要按什么 JSON 结构输出）</summary><p className="my-2 text-xs text-ink-2">{call.request?.schema_name ?? '无结构化输出要求'}</p><pre>{call.request?.schema ? JSON.stringify(call.request.schema, null, 2) : '—'}</pre></details>
      <section><h3>模型的原样回复</h3><pre>{call.response ?? '—'}</pre></section>
      <section><h3>错误信息</h3><pre className={call.error ? 'text-seal' : ''}>{call.error || '无'}</pre></section>
    </div>}
  </Sheet>
}

function TemplateEditor({ prompt, viewCall }: { prompt: PromptDetail; viewCall: (id: number) => void }) {
  const cache = useQueryClient()
  const editor = useRef<PromptEditorHandle>(null)
  const [draft, setDraft] = useState(() => readPromptDraft(prompt.name))
  const content = draft ?? prompt.content
  const [editable, setEditable] = useState(draft !== null)
  const [notice, setNotice] = useState('')
  const save = useMutation({ mutationFn: (submitted: string) => promptApi.save(prompt.name, submitted), onSuccess: async (updated, submitted) => {
    cache.setQueryData(['prompt', prompt.name], updated)
    // Another mounted editor may have resumed typing while this request was in flight.
    if (readPromptDraft(prompt.name) === submitted) writePromptDraft(prompt.name, null)
    setDraft(null); setEditable(false); setNotice('已保存，从下一步调用起对所有书生效。')
    await cache.invalidateQueries({ queryKey: ['prompts'] })
  } })
  const reset = useMutation({ mutationFn: async (_submitted: string) => { await promptApi.reset(prompt.name); return promptApi.detail(prompt.name) }, onSuccess: async (updated, submitted) => {
    if (readPromptDraft(prompt.name) === submitted) writePromptDraft(prompt.name, null)
    setDraft(null); setEditable(false); setNotice('已恢复默认。')
    save.reset()
    cache.setQueryData(['prompt', prompt.name], updated)
    await cache.invalidateQueries({ queryKey: ['prompts'] })
  } })
  const busy = save.isPending || reset.isPending
  const changeContent = (next: string) => {
    if (busy) return
    const value = next === prompt.content ? null : next
    setDraft(value)
    writePromptDraft(prompt.name, value)
    setNotice('')
  }
  return <div className="flex min-h-0 min-w-0 flex-1 flex-col">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-settings-divider px-5 py-3">
      <h2 className="text-base font-medium">{prompt.title}</h2>
      <div className="flex gap-2">
        <SettingsButton disabled={busy || (!prompt.customized && content === prompt.default_content)} onClick={() => {
          if (window.confirm('恢复默认会移除这个提示词的全局自定义内容，确定继续吗？')) reset.mutate(content)
        }}>恢复默认</SettingsButton>
        {!editable && <SettingsButton danger disabled={busy} onClick={() => { setEditable(true); setNotice(''); save.reset() }}>自定义</SettingsButton>}
        <SettingsButton primary disabled={!editable || save.isPending || reset.isPending} onClick={() => save.mutate(content)}>{save.isPending ? '保存中…' : '保存'}</SettingsButton>
      </div>
    </div>
    <div className="border-b border-settings-divider px-5 py-3 text-xs leading-6 text-ink-2">
      {roleName(prompt.role)} · {prompt.when} · {prompt.customized ? '已自定义' : '默认版本'} · 最近一次发出：{timestamp(prompt.last_call?.created_at ?? null)}
      {prompt.last_call && <button className="ml-2 text-chief hover:underline" onClick={() => viewCall(prompt.last_call!.id)}>查看 →</button>}
    </div>
    <div className="flex flex-wrap items-center gap-2 border-b border-settings-divider px-5 py-3">
      <span className="text-xs text-ink-2">可用变量</span>
      {prompt.variables.map(variable => <button key={variable.name} disabled={!editable || busy} title={`插入 {{${variable.name}}}`} className="prompt-variable disabled:cursor-default" onClick={() => editor.current?.insert(variable.name)}>{variable.label}</button>)}
      {!prompt.variables.length && <span className="text-xs text-ink-3">无变量</span>}
    </div>
    <div className="px-5" role="status"><ErrorText error={save.error || reset.error} />{notice && <p className="py-2 text-xs text-lore">{notice}</p>}</div>
    {draft !== null && <p className="px-5 pt-2 text-xs text-seal">有未保存的本地草稿；切换提示词或分页会保留，点击「保存」才会发给编辑部。</p>}
    {!editable && <p className="px-5 pt-3 text-xs text-ink-3">当前只读。点「自定义」后可编辑；变量是一个整体，不能只删除一部分。</p>}
    <PromptEditor ref={editor} value={content} editable={editable && !busy} variables={prompt.variables} onChange={changeContent} />
  </div>
}

function Templates({ viewCall }: { viewCall: (id: number) => void }) {
  const list = useQuery({ queryKey: ['prompts'], queryFn: promptApi.list })
  const [selected, setSelected] = useState('setup_interview')
  const detail = useQuery({ queryKey: ['prompt', selected], queryFn: () => promptApi.detail(selected) })
  const groups = new Map<string, PromptInfo[]>()
  for (const prompt of list.data ?? []) groups.set(prompt.group, [...(groups.get(prompt.group) ?? []), prompt])
  return <div className="prompts-workspace settings-panel">
    <nav className="prompt-nav scroll-thin" aria-label="提示词列表">
      <ErrorText error={list.error} />
      {Array.from(groups, ([group, prompts]) => <section key={group}><h3>{group}</h3>{prompts.map(prompt => <button key={prompt.name} aria-current={selected === prompt.name ? 'page' : undefined} onClick={() => setSelected(prompt.name)} className={clsx('prompt-nav-item', selected === prompt.name && 'is-selected')}>
        <span className="truncate">{prompt.title}</span>{prompt.customized && <span className="size-1.5 shrink-0 rounded-full bg-seal" aria-label="已自定义" />}
      </button>)}</section>)}
    </nav>
    <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-card">
      {detail.isLoading && <p className="p-5 text-sm text-ink-2">正在读取提示词…</p>}
      <div className="px-5"><ErrorText error={detail.error} /></div>
      {detail.data && <TemplateEditor key={detail.data.name} prompt={detail.data} viewCall={viewCall} />}
    </div>
  </div>
}

function Calls({ viewCall }: { viewCall: (id: number) => void }) {
  const [book, setBook] = useState('')
  const [role, setRole] = useState('')
  const books = useBooks()
  const calls = useInfiniteQuery({ queryKey: ['llm-calls', book, role], queryFn: ({ pageParam }) => promptApi.calls(book, role, pageParam), initialPageParam: undefined as number | undefined, getNextPageParam: page => page.next_before ?? undefined })
  const items = calls.data?.pages.flatMap(page => page.items) ?? []
  return <section>
    <div className="mb-3 flex flex-wrap items-center justify-end gap-3">
      <label className="flex items-center gap-2 text-xs text-ink-2">书<select aria-label="按书筛选" className="settings-input max-w-64" value={book} onChange={event => setBook(event.target.value)}><option value="">全部书</option>{books.data?.map(book => <option key={book.id} value={book.id}>{book.title}</option>)}</select></label>
      <label className="flex items-center gap-2 text-xs text-ink-2">角色<select aria-label="按角色筛选" className="settings-input" value={role} onChange={event => setRole(event.target.value)}><option value="">全部角色</option>{['chief', 'lorekeeper', 'writer', 'reviewer'].map(role => <option key={role} value={role}>{roleName(role)}</option>)}</select></label>
      <SettingsButton onClick={() => void calls.refetch()} disabled={calls.isFetching}>刷新</SettingsButton>
    </div>
    <ErrorText error={calls.error} />
    <div className="settings-panel overflow-x-auto"><table className="calls-table w-full text-sm">
      <thead><tr>{['时间', '角色', '做什么', '模型', '输入 token', '输出 token', '耗时', ''].map((title, i) => <th className={i >= 4 && i <= 6 ? 'number' : ''} key={i}>{title}</th>)}</tr></thead>
      <tbody>{items.map(call => <tr key={call.id}><td className="whitespace-nowrap text-xs">{timestamp(call.created_at)}</td><td className="whitespace-nowrap">{roleName(call.role)}</td><td>{call.purpose}</td><td title={call.profile_name ?? undefined}>{call.model}</td><td className="number">{number(call.prompt_tokens)}</td><td className="number">{number(call.completion_tokens)}</td><td className="number">{call.ok ? call.latency_ms == null ? '—' : `${(call.latency_ms / 1000).toFixed(2)} 秒` : <span className="text-seal">失败</span>}</td><td><button className="whitespace-nowrap text-chief hover:underline" onClick={() => viewCall(call.id)}>查看</button></td></tr>)}</tbody>
    </table>{!items.length && <p className="py-12 text-center text-sm text-ink-2">{calls.isLoading ? '正在读取调用记录…' : '还没有符合条件的调用记录'}</p>}</div>
    {calls.hasNextPage && <div className="mt-4 text-center"><SettingsButton disabled={calls.isFetchingNextPage} onClick={() => void calls.fetchNextPage()}>{calls.isFetchingNextPage ? '加载中…' : '加载更早的记录'}</SettingsButton></div>}
  </section>
}

export function PromptsPage() {
  const [tab, setTab] = useState<'prompts' | 'calls'>('prompts')
  const [call, setCall] = useState<number | null>(null)
  return <div className="mx-auto max-w-7xl px-5 pt-5 pb-10 sm:px-8">
    <div className="mb-5 flex items-center justify-between gap-4 border-b border-divider">
      <div className="flex gap-7" role="tablist" aria-label="提示词与调用记录">{(['prompts', 'calls'] as const).map(value => <button key={value} role="tab" aria-selected={tab === value} onClick={() => setTab(value)} className={clsx('border-b-2 px-1 pt-2 pb-3 text-sm', tab === value ? 'border-seal text-ink' : 'border-transparent text-ink-2')}>{value === 'prompts' ? '提示词' : '调用记录'}</button>)}</div>
      <span className="text-xs text-ink-3">提示词的改动对所有书生效</span>
    </div>
    {tab === 'prompts' ? <Templates viewCall={setCall} /> : <Calls viewCall={setCall} />}
    <CallDetail id={call} onClose={() => setCall(null)} />
  </div>
}
