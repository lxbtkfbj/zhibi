export type EditorialDock = 'ball' | 'float' | 'side'

// 编辑部摆放是本机界面偏好，换书也沿用；原型不读写正式工作台的选择。
const key = (live: boolean) => live ? 'zhibi:editorial-dock' : 'zhibi:prototype-editorial-dock'

export function readEditorialDock(live: boolean): EditorialDock {
  try {
    const saved = localStorage.getItem(key(live))
    if (saved === 'ball' || saved === 'float' || saved === 'side') return saved
  } catch { /* 存储不可用时仍能打开编辑部。 */ }
  return 'ball'
}

export function writeEditorialDock(dock: EditorialDock, live: boolean): void {
  try { localStorage.setItem(key(live), dock) } catch { /* 只影响下次恢复，不影响本次切换。 */ }
}
