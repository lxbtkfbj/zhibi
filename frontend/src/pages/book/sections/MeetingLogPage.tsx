import { Card } from '../../../components/ui'
import { useBookContext } from '../context'
import { MeetingFeed } from '../MeetingFeed'
import { PageHeader } from './common'

export function MeetingLogPage() {
  const { messages, working } = useBookContext()
  return (
    <div>
      <PageHeader eyebrow="会议记录" title="编辑部会议记录" subtitle={`共 ${messages.length} 条，包括每位编辑的发言、交付的方案和你的拍板。`} />
      <Card className="p-5 sm:p-7">
        <MeetingFeed messages={messages} working={working} autoScroll={false} className="!overflow-visible" />
      </Card>
    </div>
  )
}
