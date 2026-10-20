import type { WorkspaceActions } from '../pages/workspace/actions'

/** 只收窄拆书的界面能力；手写文字仍走原来的保存和错误提示。 */
export function teardownWorkspaceActions(source: string | undefined, actions: WorkspaceActions): WorkspaceActions {
  if (source !== 'teardown') return actions
  return {
    ...actions,
    canAdd: () => false,
    canDelete: () => false,
    canArrange: () => false,
    canEdit: node => !node.virtual && !!node.ref,
    draft: undefined,
    rewrite: undefined,
    chooseOption: undefined,
    writeNode: undefined,
    canWrite: () => false,
    splitNode: undefined,
    acceptSplit: undefined,
  }
}

export function teardownImportedDate(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return ''
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}
