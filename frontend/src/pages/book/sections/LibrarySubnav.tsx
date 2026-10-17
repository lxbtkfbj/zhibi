import { useBible } from '../../../api/hooks'
import { Segmented } from '../../../components/ui'
import { useBookContext } from '../context'

type Section = 'library' | 'relations' | 'secrets' | 'foreshadowing'

/** 设定库下的四种看法：条目和三本台账。 */
export function LibrarySubnav({ current }: { current: Section }) {
  const { bookId, manualNavigate } = useBookContext()
  const { data: bible } = useBible(bookId)
  const label = (text: string, count?: number) => <>{text}{count ? <span className="text-[11px] text-ink-3 tabular-nums">{count}</span> : null}</>
  return <Segmented label="设定库分区" value={current} className="mb-6"
    options={[['library', label('条目')], ['relations', label('人物关系', bible?.relationships.length)], ['secrets', label('信息差', bible?.secrets.length)], ['foreshadowing', label('伏笔与期待', bible?.foreshadowings.length)]] as const}
    onChange={key => manualNavigate(`/books/${bookId}/${key}`)} />
}
