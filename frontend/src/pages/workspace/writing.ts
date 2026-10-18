/** 写作：开写、停下、拍板这些事，界面只认这一套；原型用 writingSim 演示，真书以后接后台的写作任务。 */

import { chapterNodes, findNode, splitTitle, type VChapterBody, type VGate, type VNode, type VWriting, type WritePlan, type WritingGates } from './model'

/** 读一章：正文、审稿、设定师记下的变化 */
export interface ChapterDetail { text: string; review?: VChapterBody['review']; changes?: string[] }

/** 写作的这几个动作都要等后台：做完带回一句话（页面底下说一声），出错就报错 */
export interface WritingControl {
  status: VWriting
  /** 写的时候停在哪几处请作者看 */
  gates: WritingGates
  setGate(key: keyof WritingGates, on: boolean): Promise<string | void>
  /** 前 3 章试读过了没有 */
  trialDone: boolean
  /** 开不了写时说为什么 */
  blocked?: string
  start(plan: WritePlan): Promise<string | void>
  /** 等手上这一章写完再停 */
  stop(): Promise<string | void>
  resume(): Promise<string | void>
  /** 拍板：就这样 */
  approve(): Promise<string | void>
  /** 拍板：说哪里不对（试读、卡住时是给写手的话） */
  revise(text: string): Promise<string | void>
  /** 按作者的意见重写一章：带回原来的正文（能换回去）；交给编辑部去写的带回 null */
  rewrite(node: VNode, request: string): Promise<string | null>
  /** 作者改正文、换回原来的：把这一章的正文换成这些字 */
  setText(node: VNode, text: string): Promise<void>
  /** 真书、快照：点开一章才去读正文、审稿、设定的变化 */
  loadChapter?(node: VNode): Promise<ChapterDetail>
  /** 作者改了正文以后，让设定师照改过的重新记这一章的变化（还没接后台的不给） */
  redigest?(node: VNode): Promise<string | void>
  /** 写完一轮、停下后收起写作条 */
  dismiss(): void
}

export const GATE_LABELS: { key: keyof WritingGates; label: string; note?: string }[] = [
  { key: 'segment', label: '每一篇开写前，先给我看这一篇怎么走' },
  { key: 'volume', label: '每一卷开写前，先给我看卷纲（拆成了哪几个单元）' },
  { key: 'chapters', label: '每个单元的章纲也给我看' },
  { key: 'trial', label: '新书写完前 3 章，请我试读', note: '网文讲「黄金三章」：读者看完前三章就决定追不追，前三章最值得你亲自读。' },
]

/** 「第3章「少半截的小指」」 */
export function chapterLabel(node: VNode): string {
  const [prefix, name] = splitTitle(node.title)
  return name.trim() ? `${prefix}「${name.trim()}」` : prefix
}

/** 一章在哪个单元、哪一卷。 */
export function placeOf(root: VNode, id: string): { volume?: VNode; unit?: VNode } {
  const path = findNode(root, id) ?? []
  return { volume: path.find((n) => n.kind === '卷'), unit: path.find((n) => n.kind === '单元') }
}

const quoted = (node?: VNode) => (node ? `「${node.title.replace('　', ' ')}」` : '')

/** 这一轮写多少：五种。 */
export function writePlans(root: VNode): { key: WritePlan; label: string; hint: string }[] {
  const next = chapterNodes(root).find((c) => c.body?.status !== 'done')
  const { volume, unit } = next ? placeOf(root, next.id) : {}
  return [
    { key: '1', label: '写 1 章', hint: '先写一章看看' },
    { key: '3', label: '写 3 章', hint: '写够 3 章就停' },
    { key: 'unit', label: '写完这个单元', hint: unit ? `写完${quoted(unit)}就停：一个完整的小故事` : '写完眼下这个单元就停' },
    { key: 'volume', label: '写完这一卷', hint: volume ? `写完${quoted(volume)}就停` : '写完眼下这一卷就停' },
    { key: 'book', label: '一直写下去', hint: '只在下面勾了的地方停下来请你看' },
  ]
}

/** 开写以后会怎么走：按大纲现在的样子和这几处要不要停，用白话列出来。 */
export function upcomingSteps(root: VNode, gates: WritingGates, trialDone: boolean): string[] {
  const chapters = chapterNodes(root)
  const done = chapters.filter((c) => c.body?.status === 'done').length
  const next = chapters.find((c) => c.body?.status !== 'done')
  const stop = (on: boolean) => (on ? '，停下来请你看' : '')
  const steps: string[] = []
  if (!next) {
    // 排好的章都写完了（或者还一章没排）：从大纲里第一处还空着的地方往下拆
    const empty = firstEmpty(root)
    if (empty?.kind === '单元') {
      steps.push(`给${quoted(empty)}出章纲${stop(gates.chapters)}`)
    } else {
      const parts = (root.children ?? []).filter((n) => n.kind === '篇')
      if (empty?.kind !== '卷') steps.push(`主编照${empty?.kind === '篇' ? quoted(empty) : parts[0] ? quoted(parts[0]) : '第一篇'}那段话，把它分成几卷`)
      steps.push(`把${empty?.kind === '卷' ? quoted(empty) : done ? '下一卷' : '第一卷'}拆成几个单元，写出卷纲${stop(gates.volume)}`)
      steps.push(`给第一个单元出章纲${stop(gates.chapters)}`)
    }
    steps.push(done ? `写手从第 ${done + 1} 章接着写，一章一章往下写` : '写手从第 1 章写起，一章一章往下写')
  } else {
    steps.push(`写手从${chapterLabel(next)}${done ? '接着' : '开始'}写，一章一章往下写`)
  }
  steps.push('每章写完，审稿过一遍（不过关退回重写，两次还不行就停下来请你定），设定师记下人物、设定的变化')
  if (gates.trial && !trialDone && done < 3) steps.push('写完前 3 章，停下来请你试读')
  if (next && hasUnitWithoutChapters(root)) steps.push(`写到还没有章纲的单元，主编先出章纲${stop(gates.chapters)}`)
  if (next && hasLater(root, '卷')) steps.push(`写到新的一卷，主编先拆单元、写卷纲${stop(gates.volume)}`)
  if (hasLater(root, '篇')) steps.push(`写到新的一篇，主编先定这一篇怎么走、分几卷${stop(gates.segment)}`)
  return steps
}

/** 按顺序第一处还没往下拆的篇、卷、单元 */
function firstEmpty(node: VNode): VNode | undefined {
  if (node.kind !== '全书' && node.kind !== '章' && !node.children?.length) return node
  for (const child of node.children ?? []) {
    const found = firstEmpty(child)
    if (found) return found
  }
  return undefined
}

function hasUnitWithoutChapters(node: VNode): boolean {
  if (node.kind === '单元') return !node.children?.length
  return (node.children ?? []).some(hasUnitWithoutChapters)
}

function hasLater(node: VNode, kind: VNode['kind']): boolean {
  if (node.kind === kind && node.later) return true
  return (node.children ?? []).some((child) => hasLater(child, kind))
}

/** 开写前大纲够不够：至少要有第一篇那段话，或者已经有卷。 */
export function readyToWrite(root: VNode): string | undefined {
  const parts = root.children ?? []
  if (!parts.length) return '大纲还空着。开写前，先在大纲里写好第一篇那段话（在哪个舞台、主角想做成什么、谁挡路、怎么收尾），编辑部照它一层层往下拆。'
  const first = parts[0]
  if (first.kind === '篇' && !first.text.trim() && !first.children?.length) return `「${first.title.replace('　', ' ').trim()}」那段话还空着。先写几句这一篇讲什么（也可以让编辑部帮写），编辑部照它往下拆。`
  return undefined
}

/** 拍板的卡片在哪一页：大纲节点，还是正文里的章。 */
export function gateTarget(gate: VGate): { chapter?: string; node?: string } {
  return gate.kind === 'trial' || gate.kind === 'stuck' ? { chapter: gate.node } : { node: gate.node }
}
