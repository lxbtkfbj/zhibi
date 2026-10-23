/** 原型里的编辑部聊天：照几段写好的话一个字一个字吐出来，能停、能重新回答；打招呼、问是谁按身份答；话里带「出错」先演示一次没答上来。不连后台，不是模型写的。 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChatControl, ChatMessage, ChatRole } from './chatModel'
import type { VBook } from './model'

/** 打招呼、问是谁：按身份答。每人两句，重新回答换另一句 */
const INTRO: Record<ChatRole, string[]> = {
  主编: [
    '我是主编，编辑部里拿主意的那个：这本书往哪走、大纲怎么排、下一篇写什么，都可以问我。要改大纲、记写作要求，也跟我说。',
    '主编。方向和大纲归我管——想先定开头还是结尾、哪一篇要细化，直接跟我说就行。',
  ],
  设定师: [
    '我是设定师，管这本书的人物、地点、功法这些设定，还有前后对不对得上。想新建一个人物、补齐一张卡，跟我说。',
    '设定师。书里谁是谁、什么境界、人在哪儿，都记在我这儿；哪里前后矛盾了，我第一个发现。',
  ],
  写手: [
    '我是写手，正文是我写的。某个场面怎么写更爽、文风想往哪改，问我；有喜欢的写法也告诉我，我记下来照着写。',
    '写手。一章章的正文归我，想看哪种场面怎么写，我可以先示范一段。',
  ],
  审稿: [
    '我是审稿，专门挑毛病：哪里写得拖、哪里有漏洞、人物前后对不上，问我。',
    '审稿。写完的每一章我都过一遍，节奏、漏洞、爽点够不够，有话直说。',
  ],
}

const GREETING = /^(你好|您好|嗨|哈喽|hello|hi|在吗|在嗎|在不在|早上好|晚上好)$/i
const WHO = /你(叫|是)(什么|什麼|谁|誰)|名字|你是干什么|你是幹什麼|你管什么|你管什麼|你负责|你負責|介绍一下|介紹一下/

/** 每个人两段话：重新回答换另一段，看得出是新答的 */
const REPLIES: Record<ChatRole, string[]> = {
  主编: [
    '我理解你是想先把方向定稳。《{书名}》最抓人的是开头那一下，所以前几章最好让{主角}很快用上自己的本事：先救一个人，或者先躲过一次死局，让读者马上知道这本事有多值钱。\n\n大纲这边我建议先定两头：第一篇怎么开、全书怎么收。中间几篇等两头定了再往里填，不容易跑偏。你要是同意，说一声「帮我想一个开局和结尾」，我直接写进大纲。',
    '换个角度说：读者追这类书，图的是主角一步步往上爬、每爬一步都有回报。所以我更想先把第一卷的三个爽点定下来——{主角}在哪里第一次翻身、在哪里第一次被逼到墙角、卷末拿到什么——再回头补设定。\n\n想先定哪一头，直接说就行。',
  ],
  设定师: [
    '我看了一下{主角}这张卡。身份、性格都有了，但「想要什么」写得还虚。读者跟着主角走，靠的就是他想要一样具体的东西：活过今年的考核、救下某个人、查清某件事，都比「变强」好接。\n\n另外实力最好写个起点，后面每升一级我都照着记，前后才对得上。要我照这两条先补一版吗？你写过的地方不动。',
    '设定上有一处要留意：{主角}的金手指现在只写了能做什么，没写代价和限制。没有代价，后面很容易什么事都靠它一下解决，读者就不紧张了。\n\n可以加一条硬限制，比如每天只能用几次、用了要付出什么。限制写得越具体，越好写「明明能用、却不敢用」的场面。',
  ],
  写手: [
    '这种场面我一般先压后放。前面让{主角}憋着：周围人看不起、话说得难听，他也不还嘴，读者跟着憋一口气。到了点上，一句话或者一个动作翻过来，旁人的反应要写足——谁愣住了、谁脸色变了、谁悄悄往后退了半步。\n\n爽不在主角多厉害，在旁人的反应。要看的话，我拿第一章那段示范一下。',
    '文笔上我会短句多、形容词少，让动作和对话推着走。不写「他心中涌起一股难以言喻的愤怒」，写「他把碗放下，碗底磕在桌上，响了一声」。\n\n看网文的人读得快，一段别超过四五行，要紧的那一句单独成段。你有喜欢的写法就告诉我，我记成写作要求。',
  ],
  审稿: [
    '我挑三处，你看着办：\n\n一是开头铺垫有点长，第三段还没看到{主角}的本事，读者容易走；二是几个配角说话的口气太像，换个名字几乎分不出谁是谁；三是对手出场太晚，前面缺一个压着主角的人。\n\n第一条最要紧，建议把本事提到第一章前一半。',
    '节奏上我觉得有点拖：连着三章都在铺垫，中间没有一次小的回报。网文一般三五章就要给读者一点甜头，打脸、得宝、破境、揭开一个小秘密都行。\n\n可以在第二章末尾先放一个小胜，让{主角}躲过一劫，后面再接大的。',
  ],
}

/** 原型挑哪段话：打招呼、问是谁按身份答；别的话从这个人写好的两段里挑，所以常会答非所问 */
function replyFor(role: ChatRole, text: string, n: number): string {
  const intro = INTRO[role][n % INTRO[role].length]
  if (GREETING.test(text.replace(/[\s，,。.!！?？~～]/g, ''))) return `你好。${intro}`
  if (WHO.test(text)) return intro
  return REPLIES[role][n % REPLIES[role].length]
}

function protagonist(book: VBook): string {
  const people = book.categories.flatMap((c) => c.entries).filter((e) => e.kind === 'character')
  return (people.find((e) => e.role === '主角') ?? people[0])?.name || '主角'
}

const sampleSeed = (): ChatMessage[] => [
  { id: 's1', who: '主编', text: '简介我看了，开局「递丹」那一下很抓人。设定和大纲还空着的地方，想让谁写就直接说；想单独问谁，打 @ 点他的名。', state: 'done' },
  { id: 's2', who: '作者', text: '先别，我自己想想主角。' },
  { id: 's3', who: '主编', text: '好，想好了叫我。主角的「想要什么」写具体些，后面大纲好接。', state: 'done', replyTo: 's2' },
]

let serial = 0
const newId = () => `m${Date.now().toString(36)}${(serial++).toString(36)}`

export function useChatSim(book: VBook): ChatControl {
  const [messages, setMessages] = useState<ChatMessage[]>(() => (book.id === 'sample' ? sampleSeed() : []))
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  // 每一句答过几次：重新回答换一段；带「出错」的句子只错第一次
  const tries = useRef(new Map<string, number>())
  const failed = useRef(new Set<string>())
  const names = useMemo(() => ({ 书名: book.title || '这本书', 主角: protagonist(book) }), [book])

  useEffect(() => () => clearTimeout(timer.current), [])

  const update = useCallback((id: string, change: Partial<ChatMessage>) => {
    setMessages((all) => all.map((m) => (m.id === id ? { ...m, ...change } : m)))
  }, [])

  const answer = useCallback((replyId: string, question: ChatMessage) => {
    clearTimeout(timer.current)
    const n = tries.current.get(question.id) ?? 0
    tries.current.set(question.id, n + 1)
    // 没点名由主编答，和真书一样
    const role: ChatRole = question.to ?? '主编'
    update(replyId, { who: role, text: '', state: 'thinking', error: undefined })
    const fail = /出错|出錯/.test(question.text) && !failed.current.has(question.id)
    const full = replyFor(role, question.text, n).replace(/\{(书名|主角)\}/g, (_, key: '书名' | '主角') => names[key])
    timer.current = setTimeout(() => {
      if (fail) {
        failed.current.add(question.id)
        // 没答上来不算答过一次：重试还是第一段
        tries.current.set(question.id, n)
        update(replyId, { state: 'failed', error: '模型那边 60 秒没回话' })
        return
      }
      let shown = 0
      const tick = () => {
        // 一次冒一两个字，快慢不一，像真在写
        shown = Math.min(full.length, shown + 1 + Math.floor(Math.random() * 2))
        update(replyId, { text: full.slice(0, shown), state: shown >= full.length ? 'done' : 'streaming' })
        if (shown < full.length) timer.current = setTimeout(tick, 28 + Math.random() * 45)
      }
      tick()
    }, 900 + Math.random() * 700)
  }, [names, update])

  const answering = messages.some((m) => m.state === 'thinking' || m.state === 'streaming')

  const send = useCallback((text: string, to?: ChatRole) => {
    if (answering) return
    const question: ChatMessage = { id: newId(), who: '作者', text, to }
    const reply: ChatMessage = { id: newId(), who: to ?? '主编', text: '', state: 'thinking', replyTo: question.id }
    setMessages((all) => [...all, question, reply])
    answer(reply.id, question)
  }, [answer, answering])

  const stop = useCallback(() => {
    clearTimeout(timer.current)
    setMessages((all) => all.map((m) => (m.state === 'thinking' || m.state === 'streaming' ? { ...m, state: 'stopped' } : m)))
  }, [])

  const again = useCallback((id: string) => {
    const reply = messages.find((m) => m.id === id)
    const question = messages.find((m) => m.id === reply?.replyTo)
    if (reply && question && !answering) answer(reply.id, question)
  }, [answer, answering, messages])

  return { messages, answering, send, stop, again, hint: '原型 · 回答不是模型写的，是几段写好的示范，所以常会答非所问；话里带「出错」会演示一次没答上来' }
}
