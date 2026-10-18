/** 原型里演示写作：示例书照剧本一章章写出来，到该停的地方停下请作者拍板。不连后台，改的都只在这一页。 */

import { type Dispatch, type SetStateAction, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import {
  chapterNodes, countWords, findNode, numberChapters,
  type VBook, type VChapterBody, type VGate, type VNode, type VWriting, type WritePlan, type WritingGates,
} from './model'
import {
  PART_TWO, SAMPLE_CHANGES, SAMPLE_REVIEWS, SAMPLE_TEXTS, STUCK_ISSUES, VOLUME_TWO_TEXT, unitTwoChapters, volumeTwoUnits,
} from './sampleChapters'
import { type WritingControl, chapterLabel, placeOf } from './writing'

/** 原型右下角「演示」里能直接跳到的几种样子 */
export type DemoKind = 'reset' | 'writing' | 'segment' | 'volume' | 'chapters' | 'trial' | 'stuck' | 'stopped' | 'failed'

export const DEMOS: { key: DemoKind; label: string }[] = [
  { key: 'reset', label: '回到开头（写好了 2 章）' },
  { key: 'writing', label: '正在写' },
  { key: 'trial', label: '等你试读前 3 章' },
  { key: 'chapters', label: '等你看章纲' },
  { key: 'volume', label: '等你看卷纲' },
  { key: 'segment', label: '等你看下一篇怎么走' },
  { key: 'stuck', label: '一章重写两次还过不了' },
  { key: 'stopped', label: '停下了' },
  { key: 'failed', label: '出错停下了' },
]

interface Round { plan: WritePlan; wrote: number[]; unit?: string; volume?: string }

const GATES: Record<'trial' | 'chapters' | 'volume' | 'segment' | 'stuck', VGate> = {
  trial: {
    kind: 'trial', node: 'c1', title: '试读前 3 章',
    hint: '网文讲「黄金三章」：读者看完前三章，就决定追不追。读一读开头：文风、节奏、人物哪里不对就说，之后每一章都照你说的写；满意就接着写。',
  },
  chapters: {
    kind: 'chapters', node: 'u2', title: '单元二的章纲',
    hint: '主编给这个单元出了 5 章的章纲（第 5–9 章），就在下面。看看剧情顺不顺、爽点够不够；觉得哪里不对，可以直接改，也可以让主编改。满意就开写。',
  },
  volume: {
    kind: 'volume', node: 'v2', title: '第二卷的卷纲',
    hint: '主编把第二卷拆成了 3 个单元，就在下面，审稿也查过一遍。看看这一卷怎么走；觉得哪里不对，可以直接改，也可以让主编改。满意就开写。',
    issues: ['单元三「一个时辰」只给了 3 章，老祖和孙婆婆这场戏可能撑不开，审稿建议放宽到 5 章', '这一卷能说话的女性角色只有孙婆婆，讲经堂可以加一个'],
  },
  segment: {
    kind: 'segment', node: 'part2', title: '第二篇怎么走',
    hint: '第一篇快写完了。主编照全书的结局和第一篇的收尾，定好了第二篇的走向，分成两卷，就在下面。看看方向对不对；满意就往下写。',
  },
  stuck: {
    kind: 'stuck', node: 'c3', title: '第3章重写了两次，审稿还不满意',
    hint: '先读一读：觉得能用，就直接用这一版；想让写手再改，就告诉他怎么改。',
    issues: STUCK_ISSUES,
  },
}

const FALLBACK = '（原型：真书在这里一句句写出正文。）'

function cutShort(text: string): string {
  const one = text.trim().replace(/\s+/g, ' ')
  return one.length > 24 ? `${one.slice(0, 24)}…` : one
}

/** 这一轮写够了没有。 */
function reached(r: Round, root: VNode): boolean {
  if (r.plan === '1') return r.wrote.length >= 1
  if (r.plan === '3') return r.wrote.length >= 3
  const scope = r.plan === 'unit' ? r.unit : r.plan === 'volume' ? r.volume : undefined
  if (!scope || !r.wrote.length) return false
  const node = findNode(root, scope)?.at(-1)
  if (!node) return true
  const chapters = chapterNodes(node)
  const units = r.plan === 'volume' ? (node.children ?? []) : []
  return chapters.every((c) => c.body?.status === 'done') && units.every((u) => !!u.children?.length)
}

export function useWritingSim(book: VBook, setBook: Dispatch<SetStateAction<VBook>>, initial: VBook): WritingControl & { demo(kind: DemoKind): string | undefined } {
  const sample = initial.id === 'sample'
  const [status, setStatus] = useState<VWriting>({ state: 'idle' })
  const [gates, setGates] = useState<WritingGates>({ segment: true, volume: true, chapters: false, trial: true })
  const [trialDone, setTrialDone] = useState(false)
  const bookRef = useRef(book)
  const gatesRef = useRef(gates)
  const trialRef = useRef(trialDone)
  useLayoutEffect(() => {
    bookRef.current = book
    gatesRef.current = gates
    trialRef.current = trialDone
  })
  // 每开一轮加一：旧的一轮发现对不上就自己停
  const run = useRef(0)
  const round = useRef<Round | null>(null)
  const stopping = useRef(false)
  // 换书、离开页面：正在跑的这一轮作废
  useEffect(() => () => { run.current += 1 }, [])

  const sleep = useCallback((ms: number, token: number) => new Promise<boolean>((resolve) => setTimeout(() => resolve(run.current === token), ms)), [])

  const patch = useCallback((change: (outline: VNode) => void) => {
    setBook((b) => {
      const outline = structuredClone(b.outline)
      change(outline)
      numberChapters(outline)
      return { ...b, outline }
    })
  }, [setBook])

  const setBody = useCallback((id: string, body: Partial<VChapterBody>) => {
    patch((outline) => {
      const node = findNode(outline, id)?.at(-1)
      if (node) node.body = { status: 'planned', words: 0, ...node.body, ...body }
    })
  }, [patch])

  /** 写一章：备资料、一句句写、审稿、记变化。 */
  const writeChapter = useCallback(async (node: VNode, token: number, rewrite = false): Promise<boolean> => {
    const label = chapterLabel(node)
    if (!rewrite) {
      setStatus({ state: 'working', who: '设定师', doing: `设定师在给${label}备资料` })
      if (!await sleep(1100, token)) return false
    }
    const text = SAMPLE_TEXTS[node.id] ?? FALLBACK
    setBody(node.id, { status: 'writing' })
    setStatus({ state: 'working', who: '写手', doing: rewrite ? `写手在按你的意见重写${label}` : `写手在写${label}`, chapter: node.id, live: '' })
    for (let at = 0; at < text.length;) {
      const fast = stopping.current
      at = Math.min(text.length, at + (fast ? 60 : 14))
      setStatus((s) => ({ ...s, live: text.slice(0, at), stopping: stopping.current }))
      if (!await sleep(fast ? 40 : 110, token)) return false
    }
    setStatus((s) => ({ ...s, who: '审稿', doing: `审稿在看${label}`, live: text }))
    if (!await sleep(1300, token)) return false
    setStatus((s) => ({ ...s, who: '设定师', doing: `设定师在记${label}让设定变了什么` }))
    if (!await sleep(1000, token)) return false
    setBody(node.id, {
      status: 'done', text, words: countWords(text), changes: SAMPLE_CHANGES[node.id], review: SAMPLE_REVIEWS[node.id],
      attempts: rewrite ? (node.body?.attempts ?? 0) + 1 : node.body?.attempts,
    })
    setStatus((s) => ({ ...s, chapter: undefined, live: undefined }))
    return true
  }, [setBody, sleep])

  const go = useCallback(async (token: number) => {
    // 先让刚改的书画出来，再往下读
    if (!await sleep(80, token)) return
    for (;;) {
      const r = round.current
      if (!r) return
      if (stopping.current) {
        stopping.current = false
        const next = chapterNodes(bookRef.current.outline).find((c) => c.body?.status !== 'done')
        setStatus({ state: 'stopped', note: `停下了，写好的都留着。${next ? `接着写从${chapterLabel(next)}开始。` : ''}` })
        return
      }
      const outline = bookRef.current.outline
      const chapters = chapterNodes(outline)
      const done = chapters.filter((c) => c.body?.status === 'done')
      if (gatesRef.current.trial && !trialRef.current && done.length >= 3) {
        setStatus({ state: 'waiting', gate: GATES.trial })
        return
      }
      if (reached(r, outline)) {
        const first = r.wrote[0]
        const last = r.wrote.at(-1)
        setStatus({ state: 'finished', note: `这一轮写完了：${first === last ? `第 ${first} 章` : `第 ${first}–${last} 章`}。` })
        return
      }
      const next = chapters.find((c) => c.body?.status !== 'done')
      if (!next) {
        const unit = findNode(outline, 'u2')?.at(-1)
        if (unit && !unit.children?.length) {
          setStatus({ state: 'working', who: '主编', doing: '主编在给「单元二　外门考核」出章纲' })
          if (!await sleep(2600, token)) return
          patch((o) => {
            const u = findNode(o, 'u2')?.at(-1)
            if (u) u.children = unitTwoChapters()
          })
          if (!await sleep(80, token)) return
          if (gatesRef.current.chapters) {
            setStatus({ state: 'waiting', gate: GATES.chapters })
            return
          }
          continue
        }
        setStatus({ state: 'finished', note: '原型就演示到这里。真书会接着写：写完第一卷，开写第二卷前，按你的设置停下来请你看卷纲。' })
        return
      }
      if (!next.body?.text && !SAMPLE_TEXTS[next.id] && r.wrote.length) {
        setStatus({ state: 'finished', note: `这一轮写完了：第 ${r.wrote[0]}–${r.wrote.at(-1)} 章。原型只有前 5 章的正文，真书会接着往下写。` })
        return
      }
      const place = placeOf(outline, next.id)
      r.unit ??= place.unit?.id
      r.volume ??= place.volume?.id
      if (!await writeChapter(next, token)) return
      r.wrote.push(next.range?.[0] ?? chapters.indexOf(next) + 1)
      if (!await sleep(80, token)) return
    }
  }, [patch, sleep, writeChapter])

  const kick = useCallback(() => {
    const token = ++run.current
    void go(token)
  }, [go])

  const blocked = sample ? undefined : '原型里只有示例书能演示开写；这本书只看正文的样子。'

  const control = useMemo((): WritingControl & { demo(kind: DemoKind): string | undefined } => {
    const reset = () => {
      run.current += 1
      stopping.current = false
      round.current = null
      setBook(structuredClone(initial))
      setTrialDone(false)
      setStatus({ state: 'idle' })
    }
    const writeNow = (ids: string[]) => {
      for (const id of ids) {
        const text = SAMPLE_TEXTS[id]
        setBody(id, { status: 'done', text, words: countWords(text), changes: SAMPLE_CHANGES[id], review: SAMPLE_REVIEWS[id] })
      }
    }
    return {
      status, gates, trialDone, blocked,
      setGate: (key, on) => {
        setGates((g) => ({ ...g, [key]: on }))
        return on ? '好，写到那里会停下来请你看' : '好，写到那里编辑部自己定，不停下来'
      },
      start: (plan) => {
        if (blocked) return
        round.current = { plan, wrote: [] }
        stopping.current = false
        setStatus({ state: 'working', who: '主编', doing: '主编在排这一轮写哪几章' })
        kick()
      },
      stop: () => {
        if (status.state === 'working') {
          stopping.current = true
          setStatus((s) => ({ ...s, stopping: true }))
          return '好，等手上这一章写完就停'
        }
        run.current += 1
        setStatus({ state: 'stopped', note: '停下了，写好的都留着。' })
        return '停下了'
      },
      resume: () => {
        round.current ??= { plan: '3', wrote: [] }
        setStatus({ state: 'working', who: '主编', doing: '主编在接着排' })
        kick()
      },
      approve: () => {
        const gate = status.gate
        if (!gate) return undefined
        if (gate.kind === 'trial') {
          setTrialDone(true)
          trialRef.current = true
        }
        if (gate.kind === 'stuck') setBody(gate.node, { status: 'done', attempts: 2, review: { good: [], issues: STUCK_ISSUES } })
        if (gate.kind === 'volume' || gate.kind === 'segment') {
          patch((o) => {
            const node = findNode(o, gate.node)?.at(-1)
            if (node) node.later = false
          })
          setStatus({ state: 'finished', note: gate.kind === 'volume' ? '原型就演示到这里：批准以后，写手从第二卷第一章写起。' : '原型就演示到这里：确认以后，主编先把第二篇的第一卷拆成单元，再接着写。' })
          return '定了'
        }
        round.current ??= { plan: '3', wrote: [] }
        setStatus({ state: 'working', who: '主编', doing: '主编在接着排' })
        kick()
        return gate.kind === 'trial' ? '好，接着写' : '好，开写'
      },
      revise: (text) => {
        const gate = status.gate
        if (!gate || !text.trim()) return undefined
        if (gate.kind === 'trial') {
          setTrialDone(true)
          trialRef.current = true
          round.current ??= { plan: '3', wrote: [] }
          setStatus({ state: 'working', who: '主编', doing: '主编在接着排' })
          kick()
          return '记下了：以后每一章都照这个写（记在写作要求里，随时能改）'
        }
        if (gate.kind === 'stuck') {
          const node = findNode(bookRef.current.outline, gate.node)?.at(-1)
          if (!node) return undefined
          const token = ++run.current
          void writeChapter(node, token, true).then((ok) => {
            if (!ok) return
            round.current ??= { plan: '3', wrote: [] }
            void go(token)
          })
          return '好，写手照你说的再改一次'
        }
        setStatus((s) => (s.gate ? { ...s, gate: { ...s.gate, revising: true } } : s))
        const token = run.current
        void sleep(3500, token).then((alive) => {
          if (!alive) return
          setStatus((s) => (s.gate ? { ...s, gate: { ...s.gate, revising: false, issues: undefined, hint: `主编照你说的「${cutShort(text)}」改了一版，就在下面。满意就点「就这样」，还不行就接着说。` } } : s))
        })
        return '好，主编在改'
      },
      rewrite: (node, request) => {
        if (blocked || !SAMPLE_TEXTS[node.id] || !request.trim()) return undefined
        const before = node.body?.text ?? ''
        const token = ++run.current
        round.current = null
        void writeChapter(node, token, true).then((ok) => {
          if (ok) setStatus({ state: 'finished', note: `${chapterLabel(node)}照你的意见重写好了。（原型：真书会写出新的一版，这里还是原来的字）` })
        })
        return before
      },
      setText: (node, text) => setBody(node.id, { text, words: countWords(text) }),
      dismiss: () => setStatus({ state: 'idle' }),
      demo: (kind) => {
        reset()
        if (!sample) return undefined
        switch (kind) {
          case 'reset':
            return 'home'
          case 'writing':
            round.current = { plan: '3', wrote: [] }
            setStatus({ state: 'working', who: '主编', doing: '主编在排这一轮写哪几章' })
            kick()
            return 'c3'
          case 'trial':
            writeNow(['c3'])
            setStatus({ state: 'waiting', gate: GATES.trial })
            return 'c1'
          case 'chapters':
            writeNow(['c3', 'c4'])
            patch((o) => {
              const u = findNode(o, 'u2')?.at(-1)
              if (u) u.children = unitTwoChapters()
            })
            setTrialDone(true)
            setStatus({ state: 'waiting', gate: GATES.chapters })
            return 'node:u2'
          case 'volume':
            patch((o) => {
              const v = findNode(o, 'v2')?.at(-1)
              if (!v) return
              v.later = false
              v.text = VOLUME_TWO_TEXT
              v.children = volumeTwoUnits()
            })
            setStatus({ state: 'waiting', gate: GATES.volume })
            return 'node:v2'
          case 'segment':
            patch((o) => {
              const p = findNode(o, 'part2')?.at(-1)
              if (!p) return
              p.later = false
              p.title = `第二篇　${PART_TWO.name}`
              p.text = PART_TWO.text
              p.children = PART_TWO.volumes.map((v, i) => ({ id: `p2v${i + 1}`, kind: '卷', title: v.title, text: v.text, later: true, uses: [] }))
            })
            setStatus({ state: 'waiting', gate: GATES.segment })
            return 'node:part2'
          case 'stuck':
            setBody('c3', { status: 'writing', text: SAMPLE_TEXTS.c3, words: countWords(SAMPLE_TEXTS.c3), attempts: 2, review: { good: [], issues: STUCK_ISSUES } })
            setStatus({ state: 'waiting', gate: GATES.stuck })
            return 'c3'
          case 'stopped':
            round.current = { plan: '3', wrote: [] }
            setStatus({ state: 'stopped', note: '停下了，写好的都留着。接着写从第3章「少半截的小指」开始。' })
            return 'home'
          case 'failed':
            round.current = { plan: '3', wrote: [] }
            setBody('c3', { status: 'writing', text: SAMPLE_TEXTS.c3.slice(0, 260) })
            setStatus({ state: 'failed', error: '第3章写到一半，模型半天没回话，自动重试了 3 次还是不行。', note: '写好的都留着，点「接着写」从这一章重新写。' })
            return 'c3'
        }
        return undefined
      },
    }
  }, [status, gates, trialDone, blocked, initial, sample, setBook, setBody, patch, kick, go, sleep, writeChapter])

  return control
}
