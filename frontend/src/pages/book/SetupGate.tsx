import { PieceDecisions } from './PieceDecisions'

/** 开书等确认时，把「主编替你做的决定」放在页面最上面；确认和提意见在书稿底部的操作条里。 */
export function SetupGate({ piece }: { piece: 'concept' | 'settings' | 'outline' }) {
  return <PieceDecisions piece={piece} />
}
