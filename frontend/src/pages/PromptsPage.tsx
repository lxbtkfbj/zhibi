import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowLeft, BookOpen, CheckCircle2, ChevronDown, ChevronRight, FileText, History, LoaderCircle, RefreshCw, Search, Settings, XCircle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { get } from '../api/client'
import { keys, useBooks } from '../api/hooks'
import { promptApi, type PromptDetail, type PromptInfo } from '../api/prompts'
import type { BookDetail } from '../api/types'
import { PromptEditor, type PromptEditorHandle } from '../components/PromptEditor'
import { UsedPrompts } from '../components/UsedPrompts'
import { ErrorText } from '../components/ui'
import { SettingsButton } from '../components/settings/SettingsList'
import { CALL_ROLE_KEYS, normalizeCallRole, roleName } from '../lib/callRoles'
import { readPromptDraft, writePromptDraft } from '../lib/promptDrafts'
import { readCollapsedPromptGroups, writeCollapsedPromptGroups } from '../lib/promptDirectory'
import { readPromptReturnContext } from '../lib/promptNavigation'
import { resolvePromptSelection } from '../lib/promptSelection'
import { useSettingsModal } from '../lib/settingsModal'
import { PromptCallDetail } from './PromptCallDetail'
import './prompts.css'

const timestamp = (date: string | null) => date ? new Date(date).toLocaleString('zh-CN', { hour12: false }) : '尚未调用'
const number = (value: number | null) => value == null ? '—' : value.toLocaleString('zh-CN')

function TemplateEditor({ prompt, viewCall, select }: { prompt: PromptDetail; viewCall: (id: number) => void; select: (name: string) => void }) {
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
    if (prompt.name === 'glossary') await cache.invalidateQueries({ queryKey: keys.glossary })
  } })
  const reset = useMutation({ mutationFn: async (_submitted: string) => { await promptApi.reset(prompt.name); return promptApi.detail(prompt.name) }, onSuccess: async (updated, submitted) => {
    if (readPromptDraft(prompt.name) === submitted) writePromptDraft(prompt.name, null)
    setDraft(null); setEditable(false); setNotice('已恢复默认。')
    save.reset()
    cache.setQueryData(['prompt', prompt.name], updated)
    await cache.invalidateQueries({ queryKey: ['prompts'] })
    if (prompt.name === 'glossary') await cache.invalidateQueries({ queryKey: keys.glossary })
  } })
  const busy = save.isPending || reset.isPending
  const changeContent = (next: string) => {
    if (busy) return
    const value = next === prompt.content ? null : next
    setDraft(value)
    writePromptDraft(prompt.name, value)
    setNotice('')
  }
  const cancel = () => {
    if (content !== prompt.content && !window.confirm('改的还没保存，确定不要了吗？')) return
    writePromptDraft(prompt.name, null)
    setDraft(null); setEditable(false); setNotice('')
    save.reset(); reset.reset()
  }
  return <div className="template-editor">
    <div className="template-toolbar">
      <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h2>{prompt.title}</h2>{prompt.customized && <span className="prompt-version is-custom">改过</span>}</div><p>{prompt.when}</p></div>
      <div className="template-actions">
        {editable && prompt.customized && <SettingsButton disabled={busy} onClick={() => {
          if (window.confirm('恢复默认会移除这个提示词的全局自定义内容，确定继续吗？')) reset.mutate(content)
        }}>恢复默认</SettingsButton>}
        {!editable && <SettingsButton disabled={busy} onClick={() => { setEditable(true); setNotice(''); save.reset() }}>修改</SettingsButton>}
        {editable && <><SettingsButton disabled={busy} onClick={cancel}>取消</SettingsButton><SettingsButton primary disabled={busy} onClick={() => save.mutate(content)}>{save.isPending ? '保存中…' : '保存'}</SettingsButton></>}
      </div>
    </div>
    <div className="template-companions">
      <div className="template-companions-heading"><h3>一起发的</h3>{prompt.last_call ? <><span>最近一次：{timestamp(prompt.last_call.created_at)} · {prompt.last_call.purpose}</span><button type="button" className="prompt-text-link" onClick={() => viewCall(prompt.last_call!.id)}>查看这次调用</button></> : <span>还没用过</span>}</div>
      {prompt.last_call?.used_prompts && <UsedPrompts used={prompt.last_call.used_prompts} current={prompt.name} onSelect={select} legacyLabel="用到的" />}
    </div>
    {prompt.default_changed && <div className="template-update-note" role="note">
      <p className="font-medium text-seal">默认模板的变量有变化，当前仍保留你的自定义内容。</p>
      {prompt.new_variables?.length ? <p className="mt-1">新增变量：{prompt.new_variables.map(variable => `${variable.label}（${variable.name}）`).join('、')}。</p> : <p className="mt-1">默认模板的变量与当前自定义版本不同。</p>}
      <p className="mt-1">可以手动合并新增变量，或点击「恢复默认」采用新模板；恢复前请先保留你需要的自定义内容。</p>
    </div>}
    {editable && !!prompt.variables.length && <details className="template-variables"><summary>可用变量 <span>{prompt.variables.length} 个 · 展开查看并插入</span></summary><div>
      {prompt.variables.map(variable => <button type="button" key={variable.name} disabled={busy} title={`插入 {{${variable.name}}}`} className="prompt-variable disabled:cursor-default" onClick={() => editor.current?.insert(variable.name)}>{variable.label}</button>)}
    </div></details>}
    <div className="template-notice" role="status"><ErrorText error={save.error || reset.error} />{notice && <p className="text-lore">{notice}</p>}</div>
    {draft !== null && <p className="template-draft-note">有未保存的本地草稿；切换提示词或分页会保留，点击「保存」才会发给编辑部。</p>}
    <div className="template-reading-label"><span>{editable ? '正在修改' : '提示词正文'}</span>{editable && <span>保存后对所有书生效</span>}</div>
    <PromptEditor ref={editor} value={content} editable={editable && !busy} variables={prompt.variables} onChange={changeContent} />
  </div>
}

function Templates({ viewCall, requested, select, selectionRequest }: { viewCall: (id: number) => void; requested: string | null; select: (name: string) => void; selectionRequest: number }) {
  const list = useQuery({ queryKey: ['prompts'], queryFn: promptApi.list })
  const [search, setSearch] = useState('')
  const directory = useRef<HTMLElement>(null)
  const selected = resolvePromptSelection(list.data, requested)
  const selectedGroup = list.data?.find(prompt => prompt.name === selected)?.group
  const [directoryState, setDirectoryState] = useState(() => ({ collapsed: readCollapsedPromptGroups(), revealed: '' }))
  const { collapsed } = directoryState
  const revealSelection = `${selectedGroup ?? ''}\0${selected ?? ''}\0${selectionRequest}`
  // A new selection reveals its group once; the author can still collapse that group afterwards.
  if (selectedGroup && directoryState.revealed !== revealSelection) {
    setDirectoryState({ collapsed: { ...collapsed, [selectedGroup]: false }, revealed: revealSelection })
  }
  const detail = useQuery({ queryKey: ['prompt', selected], queryFn: () => promptApi.detail(selected!), enabled: selected !== null })
  const groups = new Map<string, PromptInfo[]>()
  for (const prompt of list.data ?? []) groups.set(prompt.group, [...(groups.get(prompt.group) ?? []), prompt])
  const needle = search.trim().toLocaleLowerCase()
  const filtered = Array.from(groups, ([group, prompts]) => [group, prompts.filter(prompt => `${prompt.title} ${prompt.name} ${group} ${roleName(prompt.role)}`.toLocaleLowerCase().includes(needle))] as const).filter(([, prompts]) => prompts.length)
  useEffect(() => { writeCollapsedPromptGroups(collapsed) }, [collapsed])
  const selectedGroupCollapsed = selectedGroup ? collapsed[selectedGroup] : false
  useEffect(() => {
    const item = directory.current?.querySelector<HTMLElement>('[aria-current="page"]')
    item?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [selected, selectedGroupCollapsed, needle, selectionRequest])
  const selectPrompt = (name: string) => { setSearch(''); select(name) }
  return <div className="prompts-workspace">
    <aside className="prompt-directory">
      <div className="prompt-directory-heading"><span>提示词目录</span><span>{list.data?.length ?? '—'} 项</span></div>
      <label className="prompt-search"><Search className="size-4 shrink-0" /><input aria-label="搜索提示词" value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索名称、角色…" /></label>
      <nav ref={directory} className="prompt-nav scroll-thin" aria-label="提示词列表">
        {filtered.map(([group, prompts]) => {
          const expanded = !!needle || !collapsed[group]
          return <section key={group} data-prompt-group={group}><h3><button type="button" className="prompt-group-toggle" aria-expanded={expanded} onClick={() => { if (!needle) setDirectoryState(previous => ({ ...previous, collapsed: { ...previous.collapsed, [group]: !previous.collapsed[group] } })) }}>{expanded ? <ChevronDown aria-hidden="true" /> : <ChevronRight aria-hidden="true" />}<span>{group}</span><span className="prompt-group-count">{groups.get(group)!.length}</span></button></h3>{expanded && prompts.map(prompt => <button type="button" key={prompt.name} aria-current={selected === prompt.name ? 'page' : undefined} onClick={() => select(prompt.name)} className={clsx('prompt-nav-item', selected === prompt.name && 'is-selected')}>
            <span className="min-w-0 flex-1"><span className="block break-words">{prompt.title}</span>{prompt.default_changed && <span className="prompt-nav-update">变量有更新</span>}</span>{prompt.customized && <span className="prompt-custom-dot" aria-label="改过" title="改过" />}
          </button>)}</section>
        })}
        {list.isSuccess && !!list.data.length && !filtered.length && <p className="prompt-search-empty">没有找到匹配的提示词，试试其他关键词。</p>}
      </nav>
    </aside>
    <div className="prompt-edit-pane">
      {!!list.data?.length && <label className="prompt-mobile-picker">选择提示词<select aria-label="选择提示词" value={selected ?? ''} onChange={event => select(event.target.value)}>{Array.from(groups, ([group, prompts]) => <optgroup key={group} label={group}>{prompts.map(prompt => <option key={prompt.name} value={prompt.name}>{prompt.title}</option>)}</optgroup>)}</select></label>}
      {list.isPending && <div className="prompt-state" role="status"><LoaderCircle className="size-6 animate-spin" /><p>正在读取提示词目录…</p></div>}
      {list.isError && <div className="prompt-state"><FileText className="size-7" /><p>提示词目录暂时没读出来</p><ErrorText error={list.error} /><button type="button" className="prompt-secondary-button" onClick={() => void list.refetch()}>重新读取目录</button></div>}
      {list.isSuccess && !list.data.length && <div className="prompt-state"><FileText className="size-7" /><p>暂时没有可用的提示词</p><span>目录加载成功，但还没有可展示的模板。</span></div>}
      {selected && detail.isPending && <div className="prompt-state" role="status"><LoaderCircle className="size-6 animate-spin" /><p>正在读取提示词…</p></div>}
      {selected && detail.isError && <div className="prompt-state"><p>这份提示词暂时没读出来</p><ErrorText error={detail.error} /><button type="button" className="prompt-secondary-button" onClick={() => void detail.refetch()}>重试这份提示词</button></div>}
      {selected && detail.data && <TemplateEditor key={detail.data.name} prompt={detail.data} viewCall={viewCall} select={selectPrompt} />}
    </div>
  </div>
}

function Calls({ viewCall, book, role, setFilter, originBook }: { viewCall: (id: number) => void; book: string; role: string; setFilter: (key: string, value: string) => void; originBook: BookDetail | undefined }) {
  const books = useBooks()
  const calls = useInfiniteQuery({ queryKey: ['llm-calls', book, role], queryFn: ({ pageParam }) => promptApi.calls(book, role, pageParam), initialPageParam: undefined as number | undefined, getNextPageParam: page => page.next_before ?? undefined })
  const items = calls.data?.pages.flatMap(page => page.items) ?? []
  return <section className="calls-workspace" aria-label="调用记录列表">
    <div className="calls-toolbar">
      <div className="calls-filter-fields">
        <label>书籍<select aria-label="按书筛选" value={book} onChange={event => setFilter('callBook', event.target.value)}><option value="">全部书</option>{book && !books.data?.some(item => item.id === book) && <option value={book}>{originBook?.id === book ? originBook.title : '所选书籍'}</option>}{books.data?.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
        <label>角色<select aria-label="按角色筛选" value={role} onChange={event => setFilter('callRole', event.target.value)}><option value="">全部角色</option>{CALL_ROLE_KEYS.map(value => <option key={value} value={value}>{roleName(value)}</option>)}</select></label>
      </div>
      <button type="button" className="prompt-secondary-button" onClick={() => void calls.refetch()} disabled={calls.isFetching}><RefreshCw className={clsx('size-4', calls.isFetching && 'animate-spin')} />刷新记录</button>
    </div>
    {books.isError && <p className="calls-filter-note">书籍列表暂时没读出来，当前筛选仍可使用。<button type="button" className="prompt-text-link" onClick={() => void books.refetch()}>重试书籍列表</button></p>}
    <div className="calls-scroll scroll-thin">
      {calls.isError && <div className="prompt-state"><p>调用记录暂时没读出来</p><ErrorText error={calls.error} /><button type="button" className="prompt-secondary-button" onClick={() => void (calls.isFetchNextPageError ? calls.fetchNextPage() : calls.refetch())}>重新读取记录</button></div>}
      {!!items.length && <table className="calls-table">
        <thead><tr><th>时间</th><th>书籍 / 做什么</th><th>角色</th><th>模型</th><th className="call-metric">Token · 输入 / 输出</th><th className="call-metric">耗时</th><th className="call-metric">状态</th><th><span className="sr-only">详情</span></th></tr></thead>
        <tbody>{items.map(call => <tr key={call.id}>
          <td data-label="时间" className="call-time"><time dateTime={call.created_at}>{new Date(call.created_at).toLocaleDateString('zh-CN')}<small>{new Date(call.created_at).toLocaleTimeString('zh-CN', { hour12: false })}</small></time></td>
          <td data-label="书籍 / 做什么" className="call-purpose"><span>{call.purpose}</span><small>{call.book_title || '未关联书籍'}</small></td>
          <td data-label="角色" className="call-role">{roleName(call.role)}</td>
          <td data-label="模型" className="call-model"><span>{call.model}</span><small>{call.profile_name || '未记录配置名称'}</small></td>
          <td data-label="输入 / 输出 Token" className="call-metric"><span className="call-metric-value">{number(call.prompt_tokens)} <span className="text-ink-3">/</span> {number(call.completion_tokens)}</span></td>
          <td data-label="耗时" className="call-metric"><span className="call-metric-value">{call.latency_ms == null ? '—' : `${(call.latency_ms / 1000).toFixed(2)} 秒`}</span></td>
          <td data-label="状态" className="call-metric"><span className={clsx('call-status', call.ok ? 'is-ok' : 'is-failed')}>{call.ok ? <CheckCircle2 className="size-3.5" /> : <XCircle className="size-3.5" />}{call.ok ? '成功' : '失败'}</span></td>
          <td className="call-view"><button type="button" className="prompt-secondary-button" onClick={() => viewCall(call.id)}>查看</button></td>
        </tr>)}</tbody>
      </table>}
      {calls.isPending && <div className="prompt-state" role="status"><LoaderCircle className="size-6 animate-spin" /><p>正在读取调用记录…</p></div>}
      {calls.isSuccess && !items.length && <div className="prompt-state"><History className="size-8" /><p>还没有符合条件的调用记录</p><span>编辑部调用模型后会记在这里，也可以换一个筛选条件。</span></div>}
      {calls.hasNextPage && <div className="calls-load-more"><button type="button" className="prompt-secondary-button" disabled={calls.isFetchingNextPage} onClick={() => void calls.fetchNextPage()}>{calls.isFetchingNextPage ? '加载中…' : '加载更早的记录'}</button></div>}
    </div>
    <footer className="calls-footer">按时间由近到远排列 · 每本书保留最近 2000 次调用的完整内容，较早记录仍保留统计信息。</footer>
  </section>
}

export function PromptsPage() {
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const { returnTo, bookId } = readPromptReturnContext(location.search)
  const origin = useQuery({ queryKey: keys.book(bookId ?? ''), queryFn: () => get<BookDetail>(`/books/${bookId}`), enabled: bookId !== null, retry: false })
  const { openSettings } = useSettingsModal()
  const tab = params.get('tab') === 'calls' ? 'calls' : 'prompts'
  const [call, setCall] = useState<number | null>(null)
  const [selectionRequest, setSelectionRequest] = useState(0)
  const [callSelectionRequest, setCallSelectionRequest] = useState(0)
  const update = (key: string, value: string) => setParams(previous => { const next = new URLSearchParams(previous); next.set(key, value); return next }, { replace: true })
  const selectTemplate = (name: string, fromCall = false) => {
    setSelectionRequest(value => value + 1)
    setParams(previous => { const next = new URLSearchParams(previous); if (fromCall) next.set('tab', 'prompts'); next.set('template', name); return next }, { replace: true })
  }
  const selectFromCall = (name: string) => {
    setCall(null)
    setCallSelectionRequest(value => value + 1)
    selectTemplate(name, true)
  }
  const role = normalizeCallRole(params.get('callRole'))
  return <div className="prompts-page desk-zoom">
    <header className="prompts-topbar">
      <Link to={returnTo} className="prompts-return" title={bookId ? `返回${origin.data?.title ? `《${origin.data.title}》` : '进入时的书页'}` : '返回书房'}><ArrowLeft className="size-4 shrink-0" /><span>{bookId ? '返回当前书' : '返回书房'}</span></Link>
      <span className="prompts-topbar-divider" />
      <span className="prompts-book-context"><BookOpen className="size-4 shrink-0" /><span>{bookId ? origin.data?.title || '这本书的工作台' : '执笔 · 书房'}</span></span>
      <button type="button" className="prompt-icon-button ml-auto" aria-label="系统设置" title="系统设置" onClick={openSettings}><Settings className="size-5" /></button>
    </header>
    <main className="prompts-main">
      <div className="prompts-page-heading">
        <div><h1>提示词与调用记录</h1>{tab === 'prompts' && <p>查看编辑部的工作指令。改了点「保存」才生效，所有书都用同一份。</p>}</div>
        <div className="prompts-tabs" role="tablist" aria-label="提示词与调用记录">{(['prompts', 'calls'] as const).map(value => <button key={value} type="button" id={`prompts-tab-${value}`} role="tab" aria-selected={tab === value} aria-controls="prompts-panel" tabIndex={tab === value ? 0 : -1} onKeyDown={event => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { event.preventDefault(); const next = event.key === 'Home' ? 'prompts' : event.key === 'End' ? 'calls' : value === 'calls' ? 'prompts' : 'calls'; update('tab', next); document.getElementById(`prompts-tab-${next}`)?.focus() } }} onClick={() => update('tab', value)}>{value === 'prompts' ? <FileText className="size-4" /> : <History className="size-4" />}{value === 'prompts' ? '提示词' : '调用记录'}</button>)}</div>
      </div>
      <div id="prompts-panel" className="prompts-panel" role="tabpanel" aria-labelledby={`prompts-tab-${tab}`}>
        {tab === 'prompts' ? <Templates key={callSelectionRequest} viewCall={setCall} requested={params.get('template')} select={selectTemplate} selectionRequest={selectionRequest} /> : <Calls viewCall={setCall} book={params.get('callBook') ?? bookId ?? ''} role={role} setFilter={update} originBook={origin.data} />}
      </div>
    </main>
    {call !== null && <PromptCallDetail id={call} onClose={() => setCall(null)} selectPrompt={selectFromCall} />}
  </div>
}
