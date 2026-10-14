import clsx from 'clsx'
import { Check } from 'lucide-react'
import { Fragment } from 'react'
import type { StageState } from '../../lib/team'

export function Stepper({ stages }: { stages: { key: string; label: string; state: StageState }[] }) {
  return (
    <ol className="flex items-center" aria-label="流程进度">
      {stages.map((stage, i) => (
        <Fragment key={stage.key}>
          {i > 0 && (
            <li aria-hidden className="relative mx-1.5 h-px w-4 bg-line-2 lg:w-6">
              <span
                className="absolute inset-y-0 left-0 bg-lore transition-[width] duration-700 ease-[cubic-bezier(0.22,1,0.36,1)]"
                style={{ width: stage.state === 'todo' ? '0%' : '100%' }}
              />
            </li>
          )}
          <li className="flex items-center gap-1.5" aria-current={stage.state === 'current' ? 'step' : undefined}>
            <span
              className={clsx(
                'relative flex size-5 items-center justify-center rounded-full text-[10px] font-medium transition-colors duration-500',
                stage.state === 'done' && 'bg-lore text-paper-2',
                stage.state === 'current' && 'bg-seal text-paper-2',
                stage.state === 'todo' && 'border border-line-2 text-ink-3',
              )}
            >
              {stage.state === 'current' && <span className="breath absolute inset-0 rounded-full text-seal" />}
              {stage.state === 'done' ? <Check className="size-3" strokeWidth={3} /> : i + 1}
            </span>
            <span
              className={clsx(
                'text-[13px]',
                stage.state === 'current'
                  ? 'font-medium text-seal'
                  : clsx('hidden xl:inline', stage.state === 'done' ? 'text-ink-2' : 'text-ink-3'),
              )}
            >
              {stage.label}
            </span>
          </li>
        </Fragment>
      ))}
    </ol>
  )
}
