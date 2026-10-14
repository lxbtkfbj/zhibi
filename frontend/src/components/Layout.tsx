import clsx from 'clsx'
import { BookOpen, Settings2 } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'
import { useHealth } from '../api/hooks'

export function Seal({ size = 'md' }: { size?: 'sm' | 'md' }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center justify-center rounded-md bg-seal font-serif font-bold text-paper-2 shadow-[inset_0_0_0_2px_rgba(255,255,255,0.25)]',
        size === 'sm' ? 'size-7 text-base' : 'size-9 text-xl',
      )}
    >
      笔
    </span>
  )
}

function HealthDot() {
  const { data, isError } = useHealth()
  const ok = data?.status === 'ok' && !isError
  const tip = data
    ? Object.entries(data.components)
        .map(([name, c]) => `${name}：${c.ok ? '正常' : c.detail}`)
        .join('\n')
    : '后端未连接'
  return (
    <span className="flex items-center gap-1.5 text-xs text-ink-3" title={tip}>
      <span className={clsx('size-2 rounded-full', ok ? 'bg-lore' : 'bg-seal')} />
      <span className="hidden sm:inline">{ok ? '服务正常' : '服务异常'}</span>
    </span>
  )
}

const navClass = ({ isActive }: { isActive: boolean }) =>
  clsx(
    'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-colors',
    isActive ? 'bg-card text-ink shadow-sm ring-1 ring-line' : 'text-ink-2 hover:text-ink',
  )

export function Layout() {
  return (
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 items-center justify-between gap-4 border-b border-line bg-paper-2/80 px-4 py-2.5 backdrop-blur sm:px-6">
        <NavLink to="/" className="flex items-center gap-2.5">
          <Seal />
          <span className="flex flex-col leading-tight">
            <span className="font-serif text-lg font-bold tracking-wide">执笔</span>
            <span className="text-[11px] text-ink-3">AI 编辑部 · 长篇小说创作</span>
          </span>
        </NavLink>
        <nav className="flex items-center gap-1">
          <NavLink to="/" end className={navClass}>
            <BookOpen className="size-4" />
            书架
          </NavLink>
          <NavLink to="/settings" className={navClass}>
            <Settings2 className="size-4" />
            <span className="hidden sm:inline">模型设置</span>
          </NavLink>
          <span className="ml-2">
            <HealthDot />
          </span>
        </nav>
      </header>
      <main className="min-h-0 flex-1">
        <Outlet />
      </main>
    </div>
  )
}
