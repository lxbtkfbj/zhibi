import clsx from 'clsx'
import { BookMarked, BookOpenText, GitBranch, Globe2, LayoutDashboard, Lightbulb, Network, Route, ScrollText, Settings, Users } from 'lucide-react'
import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { useBible, useChapters, useThreads } from '../../api/hooks'
import type { Conversation } from '../../api/types'
import { ROLE_META } from '../../lib/roles'
import { cleanVolumeTitle } from '../../lib/status'
import { TEAM, teamStatus } from '../../lib/team'
import { useBookContext } from './context'
import { RoleAvatar } from './MeetingFeed'

function Item({ to, icon, label, count, end, onNavigate }: { to: string; icon: ReactNode; label: ReactNode; count?: number; end?: boolean; onNavigate?: () => void }) {
  return <NavLink to={to} end={end} onClick={onNavigate} className={({ isActive }) => clsx(
    'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors',
    isActive ? 'bg-card font-medium text-ink ring-1 ring-line' : 'text-ink-2 hover:bg-card/50',
  )}>
    <span className="shrink-0 text-ink-2">{icon}</span><span className="min-w-0 flex-1 truncate">{label}</span>
    {count !== undefined && <span className="text-xs text-ink-2">{count}</span>}
  </NavLink>
}
function Group({ title, children }: { title: string; children: ReactNode }) {
  return <div className="mt-5"><p className="mb-2 px-2.5 text-xs tracking-[0.2em] text-ink-2">{title}</p><div className="space-y-0.5">{children}</div></div>
}
function Unread({ count }: { count: number }) {
  return count > 0 ? <span aria-label={`${count} 条未读`} className="min-w-4 rounded-full bg-seal px-1 text-center text-xs leading-4 text-on-role">{count > 99 ? '99+' : count}</span> : null
}

export function ConversationList({ compact, onSelect }: { compact?: boolean; onSelect?: () => void }) {
  const { conversation, setConversation, messages, working, unread } = useBookContext()
  const statuses = teamStatus(messages, working)
  const latest = messages.at(-1)
  const summary = latest?.payload?.thread ? (latest.speaker === 'author' ? '你发出了一条私聊' : `${latest.speaker_name}回复了你`) : latest?.content || '一起把故事写好'
  return <div className={clsx('space-y-1', compact ? 'px-2' : 'px-3')}>
    {(['group', ...TEAM] as Conversation[]).map(role => {
      const name = role === 'group' ? '编辑部群聊' : ROLE_META[role].name
      const state = role === 'group' ? summary : statuses[role].text
      return <button key={role} type="button" data-conversation={role} aria-pressed={conversation === role} aria-label={name}
        title={compact ? `${name} · ${state}` : undefined}
        onClick={() => { setConversation(role); onSelect?.() }}
        className={clsx('relative flex w-full items-center rounded-lg text-left transition-colors', compact ? 'justify-center py-2' : 'gap-2.5 px-2.5 py-2',
          conversation === role ? 'bg-card/85 shadow-sm ring-1 ring-line' : 'hover:bg-card/45')}>
        <RoleAvatar speaker={role} working={role !== 'group' && statuses[role].state === 'working'} />
        {!compact && <div className="min-w-0 flex-1"><p className="text-sm font-medium">{name}</p><p className="mt-0.5 truncate text-xs text-ink-2" title={state}>{state}</p></div>}
        <span className={compact ? 'absolute -top-0.5 -right-0.5' : 'shrink-0'}><Unread count={unread[role]} /></span>
      </button>
    })}
  </div>
}

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { bookId, book, job, draft, outline, working } = useBookContext()
  const { data: bible } = useBible(bookId)
  const { data: threads } = useThreads(bookId)
  const { data: chapters } = useChapters(bookId)
  const base = `/books/${bookId}`
  const icon = 'size-4'
  const live = working && draft && !draft.done && draft.job_id === job?.id ? draft : null
  const latest = live?.chapter ?? chapters?.find(c => c.status === 'drafting')?.index ?? chapters?.filter(c => c.status === 'final').at(-1)?.index
  return <div className="flex h-full min-h-0 flex-col">
    <section aria-label="编辑部会话" className="shrink-0 border-b border-divider pt-5 pb-4">
      <h2 className="mb-3 px-5 text-xs tracking-[0.25em] text-ink-2">编辑部</h2>
      <ConversationList onSelect={onNavigate} />
    </section>
    <nav aria-label="书稿目录" className="scroll-thin min-h-0 flex-1 overflow-y-auto px-3 pt-5 pb-6">
      <h2 className="mb-3 px-2.5 text-xs tracking-[0.25em] text-ink-2">书稿</h2>
      <div className="space-y-0.5">
        <Item to={base} end icon={<LayoutDashboard className={icon} />} label="概览" onNavigate={onNavigate} />
        <Item to={`${base}/concept`} icon={<Lightbulb className={icon} />} label="书的概念" onNavigate={onNavigate} />
        <Item to={`${base}/spine`} icon={<Route className={icon} />} label="主线骨架" onNavigate={onNavigate} />
        <Item to={`${base}/threads`} icon={<GitBranch className={icon} />} label="线索" count={threads?.length || undefined} onNavigate={onNavigate} />
      </div>
      {!!outline?.volumes.length && <Group title="大纲">{outline.volumes.map(v => <Item key={v.id} to={`${base}/volume/${v.index}`} icon={<BookMarked className={icon} />}
        label={`第 ${v.index} 卷 · ${cleanVolumeTitle(v.title)}`} onNavigate={onNavigate} />)}</Group>}
      <Group title="正文">
        <Item to={`${base}/chapters`} icon={<BookOpenText className={icon} />} label="目录" count={book.chapters_final || undefined} onNavigate={onNavigate} />
        {!!latest && <Item to={`${base}/chapter/${latest}`} icon={<BookOpenText className={icon} />} label={`${live ? '正在写' : '最新'} · 第 ${latest} 章`} onNavigate={onNavigate} />}
      </Group>
      <Group title="设定库">
        <Item to={`${base}/characters`} icon={<Users className={icon} />} label="人物" count={bible?.characters.length} onNavigate={onNavigate} />
        <Item to={`${base}/world`} icon={<Globe2 className={icon} />} label="世界观" count={bible?.world_entries.length} onNavigate={onNavigate} />
        <Item to={`${base}/relations`} icon={<Network className={icon} />} label="人物关系" count={bible?.relationships.length} onNavigate={onNavigate} />
        <Item to={`${base}/foreshadowing`} icon={<ScrollText className={icon} />} label="伏笔" count={bible?.foreshadowings.length} onNavigate={onNavigate} />
      </Group>
      <div className="mt-5 border-t border-divider pt-3"><Item to={`${base}/settings`} icon={<Settings className={icon} />} label="这本书的设置" onNavigate={onNavigate} /></div>
    </nav>
  </div>
}
