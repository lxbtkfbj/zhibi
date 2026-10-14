import clsx from 'clsx'
import { PanelRightClose, PanelRightOpen } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { ROLE_META } from '../../lib/roles'
import { TEAM, teamStatus } from '../../lib/team'
import { useBookContext } from './context'
import { DecisionControls, ResumeControls, RunningControls } from './Decision'
import { MeetingFeed, RoleAvatar } from './MeetingFeed'

function Roster({ compact }: { compact?: boolean }) {
  const { messages, working } = useBookContext()
  const status = teamStatus(messages, working)
  if (compact) {
    return (
      <div className="flex flex-col items-center gap-4">
        {TEAM.map((role) => (
          <div key={role} className="relative" title={`${ROLE_META[role].name}：${status[role].text}`}>
            <RoleAvatar speaker={role} working={status[role].state === 'working'} />
            {status[role].state === 'done' && <span className="absolute -right-0.5 -bottom-0.5 size-2.5 rounded-full border-2 border-paper-2 bg-lore" />}
          </div>
        ))}
      </div>
    )
  }
  return (
    <div className="grid grid-cols-2 gap-2">
      {TEAM.map((role) => {
        const s = status[role]
        const meta = ROLE_META[role]
        return (
          <div
            key={role}
            className={clsx(
              'rounded-xl border bg-card px-3 py-2.5 transition-all duration-500',
              s.state === 'working' ? 'border-transparent shadow-[var(--shadow-lift)] ring-1 ring-line-2' : 'border-line shadow-[var(--shadow-paper)]',
            )}
          >
            <div className="flex items-center gap-2">
              <RoleAvatar speaker={role} size="sm" working={s.state === 'working'} />
              <span className="text-[13px] font-medium">{meta.name}</span>
            </div>
            <p
              className={clsx(
                'mt-1.5 line-clamp-1 text-xs',
                s.state === 'working' ? meta.text : s.state === 'done' ? 'text-ink-2' : 'text-ink-3',
              )}
              title={s.text}
            >
              {s.text}
            </p>
          </div>
        )
      })}
    </div>
  )
}

function ActionCard() {
  const { job, waiting, working } = useBookContext()
  if (!job) return null
  return (
    <AnimatePresence mode="wait">
      {waiting && (
        <motion.div
          key="wait"
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          className="relative overflow-hidden rounded-xl border border-seal/30 bg-card p-4 shadow-[var(--shadow-lift)]"
        >
          <span className="absolute inset-y-0 left-0 w-1 bg-seal" />
          <p className="font-serif text-[15px] font-bold text-seal">
            开书方案已就绪{(job.pending?.round ?? 0) > 0 ? `（第 ${(job.pending?.round ?? 0) + 1} 版）` : ''}
          </p>
          <p className="mt-1 mb-3 text-xs leading-relaxed text-ink-3">左边目录里可以逐项查看、直接修改。满意就盖章，不满意就提意见。</p>
          <DecisionControls job={job} compact />
        </motion.div>
      )}
      {working && (
        <motion.div key="run" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="rounded-xl bg-chief-soft/60 px-3.5 py-2.5">
          <RunningControls job={job} />
        </motion.div>
      )}
      {(job.status === 'failed' || job.status === 'cancelled') && (
        <motion.div key="fail" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="rounded-xl border border-seal/30 bg-seal-soft/50 p-3.5">
          <ResumeControls job={job} />
        </motion.div>
      )}
    </AnimatePresence>
  )
}

/** 右侧编辑部面板：可收起为一条头像栏。 */
export function TeamPanel() {
  const { teamOpen, setTeamOpen, messages, working, connected } = useBookContext()

  return (
    <motion.aside
      animate={{ width: teamOpen ? 400 : 64 }}
      transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      className="relative hidden h-full shrink-0 flex-col overflow-hidden border-l border-line bg-paper-2/80 lg:flex"
    >
      {teamOpen ? (
        <div className="flex h-full w-[400px] flex-col">
          <div className="flex items-center justify-between px-4 pt-4 pb-3">
            <div className="flex items-center gap-2">
              <h2 className="font-serif text-lg font-bold">编辑部</h2>
              <span className={clsx('flex items-center gap-1 text-xs', connected ? 'text-lore' : 'text-ink-3')}>
                <span className={clsx('size-1.5 rounded-full', connected ? 'bg-lore' : 'bg-ink-3')} />
                {connected ? (working ? '开会中' : '在线') : '连接中'}
              </span>
            </div>
            <button onClick={() => setTeamOpen(false)} className="rounded-lg p-1.5 text-ink-3 hover:bg-line/60 hover:text-ink" aria-label="收起编辑部">
              <PanelRightClose className="size-4" />
            </button>
          </div>
          <div className="space-y-3 px-4 pb-3">
            <Roster />
            <ActionCard />
          </div>
          <div className="flex items-center gap-2 px-4 pt-1 pb-2 text-[11px] tracking-[0.2em] text-ink-3">
            会议记录
            <span className="h-px flex-1 bg-line" />
          </div>
          <MeetingFeed messages={messages} working={working} className="min-h-0 flex-1 px-4 pb-6" />
        </div>
      ) : (
        <div className="flex h-full w-16 flex-col items-center gap-5 pt-4">
          <button onClick={() => setTeamOpen(true)} className="rounded-lg p-1.5 text-ink-3 hover:bg-line/60 hover:text-ink" aria-label="展开编辑部">
            <PanelRightOpen className="size-4" />
          </button>
          <Roster compact />
        </div>
      )}
    </motion.aside>
  )
}

/** 窄屏：编辑部以全屏面板显示。 */
export function TeamSheetBody() {
  const { messages, working } = useBookContext()
  return (
    <div className="flex h-full flex-col">
      <div className="space-y-3 pb-3">
        <Roster />
        <ActionCard />
      </div>
      <MeetingFeed messages={messages} working={working} className="min-h-0 flex-1 pb-6" />
    </div>
  )
}
