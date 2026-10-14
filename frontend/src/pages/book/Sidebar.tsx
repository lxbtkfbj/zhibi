import clsx from 'clsx'
import { BookMarked, Globe2, LayoutDashboard, Lightbulb, MessagesSquare, Network, Route, ScrollText, Settings2, Users } from 'lucide-react'
import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { useBible, useOutline } from '../../api/hooks'
import { BookCover } from '../../components/BookCover'
import { HealthDot } from '../../components/Layout'
import { cleanTitle, cleanVolumeTitle } from '../../lib/status'
import { useBookContext } from './context'

function Item({ to, icon, label, count, end, onNavigate }: { to: string; icon: ReactNode; label: ReactNode; count?: number; end?: boolean; onNavigate?: () => void }) {
  return (
    <NavLink
      to={to}
      end={end}
      onClick={onNavigate}
      className={({ isActive }) =>
        clsx(
          'group relative flex items-center gap-2.5 rounded-lg px-2.5 py-[7px] text-[14px] transition-colors',
          isActive ? 'bg-card font-medium text-ink shadow-[var(--shadow-paper)] ring-1 ring-line' : 'text-ink-2 hover:bg-line/50 hover:text-ink',
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && <span className="absolute top-1/2 -left-3 h-4 w-[3px] -translate-y-1/2 rounded-r-full bg-seal" />}
          <span className={clsx('shrink-0', isActive ? 'text-seal' : 'text-ink-3 group-hover:text-ink-2')}>{icon}</span>
          <span className="min-w-0 flex-1 truncate">{label}</span>
          {count !== undefined && <span className="text-xs text-ink-3">{count}</span>}
        </>
      )}
    </NavLink>
  )
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="mt-5">
      <p className="mb-1.5 px-2.5 text-[11px] tracking-[0.2em] text-ink-3">{title}</p>
      <div className="space-y-0.5">{children}</div>
    </div>
  )
}

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { bookId, book } = useBookContext()
  const { data: outline } = useOutline(bookId)
  const { data: bible } = useBible(bookId)
  const base = `/books/${bookId}`
  const icon = 'size-4'

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 px-4 pt-5 pb-4">
        <BookCover title={book.title} seed={book.id} size="sm" className="!w-11" />
        <div className="min-w-0">
          <p className="truncate font-serif text-[15px] font-bold">{cleanTitle(book.title)}</p>
          <p className="truncate text-xs text-ink-3">{book.genre || '开书中'}</p>
        </div>
      </div>
      <nav className="scroll-thin flex-1 overflow-y-auto px-3 pb-4">
        <div className="space-y-0.5">
          <Item to={base} end icon={<LayoutDashboard className={icon} />} label="概览" onNavigate={onNavigate} />
          <Item to={`${base}/concept`} icon={<Lightbulb className={icon} />} label="书的概念" onNavigate={onNavigate} />
          <Item to={`${base}/spine`} icon={<Route className={icon} />} label="主线骨架" count={book.spine?.milestones?.length || undefined} onNavigate={onNavigate} />
          <Item to={`${base}/meeting`} icon={<MessagesSquare className={icon} />} label="会议记录" onNavigate={onNavigate} />
        </div>
        {outline && outline.volumes.length > 0 && (
          <Group title="大纲">
            {outline.volumes.map((v) => (
              <Item
                key={v.id}
                to={`${base}/volume/${v.index}`}
                icon={<BookMarked className={icon} />}
                label={
                  <span>
                    <span className="mr-1.5 text-ink-3">第{v.index}卷</span>
                    {cleanVolumeTitle(v.title)}
                  </span>
                }
                count={v.units.length || undefined}
                onNavigate={onNavigate}
              />
            ))}
          </Group>
        )}
        {/* 删光人物后也要能进设定库的其他页面 */}
        {bible && (book.status !== 'setting_up' || bible.characters.length + bible.world_entries.length > 0) && (
          <Group title="设定库">
            <Item to={`${base}/characters`} icon={<Users className={icon} />} label="人物" count={bible.characters.length} onNavigate={onNavigate} />
            <Item to={`${base}/world`} icon={<Globe2 className={icon} />} label="世界观" count={bible.world_entries.length} onNavigate={onNavigate} />
            <Item to={`${base}/relations`} icon={<Network className={icon} />} label="人物关系" count={bible.relationships.length} onNavigate={onNavigate} />
            <Item to={`${base}/foreshadowing`} icon={<ScrollText className={icon} />} label="伏笔" count={bible.foreshadowings.length} onNavigate={onNavigate} />
          </Group>
        )}
      </nav>
      <div className="flex items-center justify-between border-t border-line px-4 py-3">
        <NavLink to="/settings" className="flex items-center gap-1.5 text-[13px] text-ink-3 hover:text-ink">
          <Settings2 className="size-4" />
          模型设置
        </NavLink>
        <HealthDot compact />
      </div>
    </div>
  )
}
