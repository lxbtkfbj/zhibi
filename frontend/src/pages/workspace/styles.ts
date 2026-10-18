/** 工作台各页共用的样式和小工具（不是组件，单放一个文件，页面热更新才顺）。 */

/** 读一栏里现在的字：不间断空格换回普通空格，去掉末尾的空行。 */
export const readText = (el: HTMLElement) => el.innerText.replace(/ /g, ' ').replace(/\n+$/, '')

/** 卡片里的小按钮（新增关系、加上一栏）：白底细框，和「编辑部帮写」同一种，小一号，不带加号。 */
export const smallButton = 'h-8 rounded-lg border border-line-2 bg-card px-3.5 text-[13px] text-ink-2 transition-colors hover:border-ink-3/50 hover:text-ink disabled:opacity-40 disabled:hover:border-line-2 disabled:hover:text-ink-2'

export const menuItem = 'block w-full rounded-lg px-3 py-2 text-left text-sm text-ink-2 hover:bg-subtle hover:text-ink'

export const rowSelected = 'bg-card shadow-[0_1px_2px_rgb(60_40_20/0.08)]'

/** 中间那一页纸 */
export const paperCard = 'rounded-xl border border-line bg-card px-12 py-11 shadow-[var(--shadow-paper)] 2xl:px-16 2xl:py-14'
export const titleClass = 'font-serif text-[34px] leading-tight font-bold break-all 2xl:text-[38px]'
