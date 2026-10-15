import clsx from 'clsx'
import { Settings2 } from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useHealth } from '../api/hooks'
import { Seal } from './decor'

export function HealthDot({ compact }: { compact?: boolean }) {
  const { data, isError } = useHealth()
  const ok = data?.status === 'ok' && !isError
  const tip = data
    ? Object.entries(data.components)
        .map(([name, c]) => `${name}：${c.ok ? '正常' : c.detail}`)
        .join('\n')
    : '后端未连接'
  return (
    <span className="flex items-center gap-1.5 text-xs text-ink-2" title={tip}>
      <span className="relative flex size-2">
        {ok && <span className="absolute inline-flex size-full animate-ping rounded-full bg-lore/50 [animation-duration:2.5s]" />}
        <span className={clsx('relative inline-flex size-2 rounded-full', ok ? 'bg-lore' : 'bg-seal')} />
      </span>
      {!compact && <span className="hidden sm:inline">{ok ? '服务正常' : '服务异常'}</span>}
    </span>
  )
}

export function Brand() {
  return (
    <NavLink to="/" className="group flex items-center gap-3">
      <Seal size={38} className="transition-transform duration-500 group-hover:-rotate-6" />
      <span className="flex flex-col leading-tight">
        <span className="font-serif text-xl font-bold tracking-[0.2em]">执笔</span>
        <span className="text-xs tracking-wider text-ink-2">AI 编辑部 · 长篇小说</span>
      </span>
    </NavLink>
  )
}

const navClass = ({ isActive }: { isActive: boolean }) =>
  clsx(
    'relative px-1 py-1 text-[15px] transition-colors',
    'after:absolute after:inset-x-0 after:-bottom-0.5 after:h-0.5 after:origin-left after:rounded-full after:bg-seal after:transition-transform after:duration-300',
    isActive ? 'text-ink after:scale-x-100' : 'text-ink-2 after:scale-x-0 hover:text-ink hover:after:scale-x-100',
  )

/** 书房、设置等页面的外框：较高的顶栏，滚动后变为半透明纸色。 */
export function SiteLayout() {
  const [scrolled, setScrolled] = useState(false)
  return (
    <div className="scroll-thin h-full overflow-y-auto" onScroll={(e) => setScrolled(e.currentTarget.scrollTop > 8)}>
      <header
        className={clsx(
          'sticky top-0 z-30 transition-all duration-300',
          scrolled ? 'border-b border-line/80 bg-paper/75 backdrop-blur-md' : 'border-b border-transparent',
        )}
      >
        <div className="mx-auto flex h-[72px] max-w-6xl items-center justify-between gap-6 px-5 sm:px-8">
          <Brand />
          <nav className="flex items-center gap-6">
            <NavLink to="/" end className={navClass}>
              书房
            </NavLink>
            <NavLink to="/settings" className={navClass}>
              <span className="flex items-center gap-1.5">
                <Settings2 className="size-4" />
                <span className="hidden sm:inline">模型设置</span>
              </span>
            </NavLink>
            <HealthDot />
          </nav>
        </div>
      </header>
      <Outlet />
    </div>
  )
}
