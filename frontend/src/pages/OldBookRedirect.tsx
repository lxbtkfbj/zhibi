import { Navigate, useParams } from 'react-router-dom'

/** 旧版书页退役（2026-10-19）：以前的地址（收藏的、聊天记录里的链接）都到书页 */
export function OldBookRedirect() {
  const { bookId = '' } = useParams()
  return <Navigate to={`/desk/${bookId}`} replace />
}
