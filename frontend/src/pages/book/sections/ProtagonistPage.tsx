import { protagonistFields } from '../../../lib/setupPresentation'
import { useBookContext } from '../context'
import { PieceDecisions } from '../PieceDecisions'
import { FieldBlock, PageHeader } from './common'

export function ProtagonistPage() {
  const { book } = useBookContext()
  const card = book.protagonist ?? {}
  const available = Object.keys(card).length > 0
  return <div>
    <PieceDecisions piece="protagonist" />
    <PageHeader eyebrow="主角卡" title={card.name || '主角'} subtitle="他是谁、想要什么、为什么、凭什么。" />
    {available ? <div className="space-y-6" data-testid="protagonist-card">{protagonistFields(card).map(({ label, value }) => <FieldBlock key={label} label={label}><p className="text-sm leading-relaxed whitespace-pre-wrap">{value || '（未定）'}</p></FieldBlock>)}</div>
      : <div className="space-y-4 text-sm leading-relaxed text-ink-2"><p>{book.status === 'setting_up' || book.status === 'awaiting_approval' ? '主编还在准备主角卡。' : '这本书开书时还没有主角卡'}</p>{book.concept.protagonist_hook && <FieldBlock label="主角钩子"><p>{book.concept.protagonist_hook}</p></FieldBlock>}</div>}
  </div>
}
