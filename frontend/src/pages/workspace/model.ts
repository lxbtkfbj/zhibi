/** 书工作台的数据形状：书架上的真书、示例书、空书、旧书快照，都先转成这个样子再画。 */

export interface VField {
  /** 原来的栏目名：作者改了名，程序还按它认（比如身世后面挂「另有秘密」） */
  key?: string
  label: string
  text: string
  placeholder?: string
}

export interface VEntry {
  id: string
  /** 角色卡、金手指是一栏一栏的；段落类是「名字＋一段话」；阶梯是一级一级的 */
  kind: 'character' | 'goldfinger' | 'paragraph' | 'ladder'
  /** 归在哪一类（显示名） */
  category: string
  name: string
  /** 角色、金手指的一句话；段落类不用 */
  oneLine: string
  tags: string[]
  locked: boolean
  /** 角色的定位，用来在目录里分组 */
  role?: string
  /** 角色已经死了：名字旁边标一下，不用「此刻」里写「活着」 */
  dead?: boolean
  /** 名字下面的短字段：显示名、内容、空着时的提示、存内容时认的名字（不写就是显示名） */
  facts: [string, string, string?, string?][]
  /** 一栏一栏的长字段；段落类只有一栏「内容」 */
  sections: VField[]
  /** 角色此刻的状态，设定师每章更新；全空就不显示 */
  now?: [string, string][]
  /** id 是真书里关系那一行；toLead 是旧数据「和主角的关系」那一栏 */
  relations?: { id?: string; to: string; kind: string; text: string; toLead?: boolean }[]
  /** 身世里「另有秘密」指向的条目 */
  secret?: string
  /** 角色的金手指条目 / 金手指的主人 */
  goldfinger?: string
  holder?: string
  overview?: string
  levels?: { name: string; text: string }[]
  /** 地点属于哪里：父条目 id */
  parent?: string
  appears: { node: string; label: string }[]
  /** 从别处推出来的（比如带金手指标签的角色），这里不能改 */
  readonly?: boolean
}

export interface VCategory {
  /** 存栏目时认的名字：内置类别就是显示名，自建的是 custom:xxx */
  key: string
  /** 自建类别在真书里那一行的 id */
  id?: string
  name: string
  /** 一句话说清这一类放什么 */
  about: string
  example?: { name: string; text: string }
  entries: VEntry[]
  /** 作者自建的类别：样式和卡片的栏目 */
  custom?: { style: 'paragraph' | 'card' | 'ladder'; fields: string[] }
}

/** 正文里的一章：大纲上的章节点带着它。 */
export interface VChapterBody {
  /** 只有章纲 / 写手在写 / 写完了 */
  status: 'planned' | 'writing' | 'done'
  words: number
  /** 正文；真书点开才去读，读之前是 undefined */
  text?: string
  /** 审稿退回重写过几次 */
  attempts?: number
  /** 这一章写完，设定师记下的变化，一行一条 */
  changes?: string[]
  /** 审稿：说好的、还可以更好的 */
  review?: { good: string[]; issues: string[] }
}

export interface VNode {
  id: string
  kind: '全书' | '篇' | '卷' | '单元' | '章'
  title: string
  text: string
  /** 章才有：正文 */
  body?: VChapterBody
  /** 章纲：发生什么、看点、结尾钩子 */
  sections?: VField[]
  chapters?: number
  /** 自己定的章数，0 是还没定（有几章算几章，写到这里编辑部再定）；只有单元和没拆单元的卷能改 */
  count?: number
  /** 第几章到第几章，程序按顺序算 */
  range?: [number, number]
  /** 写到哪了：没写 / 正在写 / 写完 */
  progress?: string
  later?: boolean
  /** 写到再定的篇里排在最前面的那一篇：可以直接在它下面加卷，加了它就定下来 */
  next?: boolean
  locked?: boolean
  uses: string[]
  children?: VNode[]
  /** 下面一层是什么：还没有孩子时用（没分篇的书，全书下面直接是卷） */
  childKind?: VNode['kind']
  /** 真书里对应的那一行 */
  ref?: { type: 'book' | 'segment' | 'volume' | 'unit' | 'chapter'; id: string }
}

export interface VBook {
  id: string
  title: string
  channel: string
  genre: string
  tags: string[]
  length?: number
  chapterWords: number
  blurb: string
  /** 世界概况：一本书只有一篇，单独放在设定最上面 */
  world: string
  categories: VCategory[]
  outline: VNode
  pending: number
  /** 这本书每一类设定有哪几栏，键是类别的 key；没存的按默认 */
  layouts: Record<string, CardTemplate>
}

/* ---------------- 写作：开写、正文、拍板 ---------------- */

/** 要作者拍板的五种：下一篇怎么走、卷纲、章纲、试读前 3 章、一章重写两次还过不了 */
export type GateKind = 'segment' | 'volume' | 'chapters' | 'trial' | 'stuck'

export interface VGate {
  kind: GateKind
  /** 在哪一页拍板：篇、卷、单元是大纲节点 id，试读、卡住是章的 id */
  node: string
  /** 第一卷的卷纲 */
  title: string
  /** 白话说清要作者看什么、点了会怎样 */
  hint: string
  /** 审稿的提醒、卡住的原因 */
  issues?: string[]
  /** 主编正在按作者的意见改 */
  revising?: boolean
}

export interface VWriting {
  /** 空闲 / 在干活 / 等作者拍板 / 停下了 / 出错停下了 / 这一轮写完了 */
  state: 'idle' | 'working' | 'waiting' | 'stopped' | 'failed' | 'finished'
  who?: '主编' | '写手' | '审稿' | '设定师'
  /** 正在做什么：主编在给单元二出章纲 */
  doing?: string
  /** 写手正在写的章 */
  chapter?: string
  /** 写手已经写出来的字 */
  live?: string
  gate?: VGate
  error?: string
  /** 停下、写完时的一句交代 */
  note?: string
  /** 点了停下，等手上这一章写完 */
  stopping?: boolean
}

/** 写作中停下来请作者看的地方（本书设置里的四个开关） */
export interface WritingGates { segment: boolean; volume: boolean; chapters: boolean; trial: boolean }

export type WritePlan = '1' | '3' | 'unit' | 'volume' | 'book'

/** 全书所有的章，按顺序。 */
export function chapterNodes(root: VNode): VNode[] {
  const out: VNode[] = []
  const walk = (node: VNode) => {
    if (node.kind === '章') out.push(node)
    node.children?.forEach(walk)
  }
  walk(root)
  return out
}

/** 一章写了多少字：不算空白。 */
export function countWords(text: string): number {
  return text.replace(/\s/g, '').length
}

/** 一栏：key 是存内容时认的名字，label 是现在显示的名字（改了名 key 不变）。 */
export interface FieldItem { key: string; label: string }
/** 一类设定每一条有哪几栏：facts 是名字下面的小字，sections 是正文栏目。 */
export interface CardTemplate { facts: FieldItem[]; sections: FieldItem[] }

/** 八个默认类别。名字三到五个字；from 是真实设定库里对应的类别。 */
export const CATEGORY_DEFS: { name: string; from: string[]; about: string; example?: { name: string; text: string } }[] = [
  { name: '角色列表', from: ['角色卡片'], about: '有名有姓、会再出场的人；会说话的器灵、系统人格也算。' },
  { name: '金手指', from: ['金手指'], about: '主角最大的倚仗：系统、物品、体质、重生记忆……能做什么、有什么代价、怎么变强。' },
  {
    name: '等级体系', from: ['等级体系'], about: '一切分高低的等级：修炼境界、玩家等级、鬼的等级、官阶……一本书可以有好几套。',
    example: { name: '修炼境界', text: '炼气：分九层，外门弟子大多卡在这里。\n筑基：寿命翻倍。\n金丹：可以开宗立派。\n元婴：先只列个名字，以后再补。' },
  },
  {
    name: '地点列表', from: ['世界与地图'], about: '一个个地方。写清它属于哪里，目录里会排成一棵树。',
    example: { name: '青阳城', text: '属于东域。楚、秦、柳三家分治的小城，城外是黑风山脉，常有妖兽出没。主角开局就在这里，处处受人冷眼。' },
  },
  {
    name: '势力列表', from: ['势力划分'], about: '宗门、家族、国家、公司、公会、队伍。',
    example: { name: '天音宗', text: '东域三大宗门之一，只收女弟子。宗主闭关百年，大长老掌权。和主角所在的宗门是死对头，内部分成宗主一系和大长老一系。' },
  },
  {
    name: '物品功法', from: ['物品与功法'], about: '能拿到、能学、能传下去的东西：法宝、丹药、道具、功法、技能、血脉。',
    example: { name: '九转筑基丹', text: '筑基用的三品丹药。吃了能把筑基的把握从三成提到七成；炼一炉要九叶还魂草，市面上一年出不了十颗。现在只有城主府有存货。' },
  },
  {
    name: '往事秘密', from: ['往事与秘密'], about: '过去发生的事，和藏着的真相。秘密记得写谁知道、打算什么时候揭开。',
    example: { name: '三百年前的灭门案', text: '三百年前，青云宗一夜之间被灭门，只活下来一个孩子。谁知道：只有现任掌门。打算第二卷揭开：那个孩子就是主角的师父。' },
  },
  {
    name: '特殊规则', from: ['特殊规则'], about: '这个世界特有的规矩、限制和代价。一条规矩一个名字，内容可以一条条列。',
    example: { name: '夺舍法则', text: '1. 只能夺舍神识比自己弱的人\n2. 一辈子只能夺舍一次\n3. 夺舍后三年内修为不能再往上走' },
  },
]

export const CATEGORY_NAMES = CATEGORY_DEFS.map((c) => c.name)

export function emptyCategory(name: string): VCategory {
  const def = CATEGORY_DEFS.find((c) => c.name === name)
  return { key: name, name, about: def?.about ?? '', example: def?.example, entries: [] }
}

/** 角色卡的字段（照真实设定库），定位按这个顺序分组。 */
export const ROLE_ORDER = ['主角', '女主', '男主', '班底', '对手', '导师', '配角']
export const LEGACY_ROLES: Record<string, string> = { 反派: '对手', 龙套: '配角' }

/** 角色卡的长栏目，按这个顺序。「和主角的关系」并进了关系，不单列。 */
export const CHARACTER_FIELDS = ['外貌', '性格与说话方式', '身世', '想要什么', '软肋', '能力', '成长与结局', '备注']

export const CHARACTER_PLACEHOLDERS: Record<string, string> = {
  外貌: '一两处让人记住的地方，比如疤、小动作',
  性格与说话方式: '话多话少、口头禅，一句话就能看出这个人',
  身世: '公开的来历；藏着的写进「往事秘密」，这里标一句「另有秘密」',
  想要什么: '这辈子最想要的是什么（眼下想要的写在「此刻」）',
  软肋: '怕什么、在乎谁，拿什么能逼住他',
  能力: '会什么本事，有什么限制',
  成长与结局: '在书里会怎么变，最后怎么收场',
  备注: '随手记',
}

/** 每一类默认有哪几栏：facts 是名字下面的小字，sections 是正文栏目。作者可以按书改。 */
export const DEFAULT_FIELDS: Record<string, { facts: string[]; sections: string[] }> = {
  角色列表: { facts: ['定位', '所属', '性别', '年龄', '别名'], sections: CHARACTER_FIELDS },
  金手指: { facts: ['是什么', '谁知道'], sections: ['能做什么', '规矩和限制', '代价', '怎么变强', '来历'] },
  地点列表: { facts: ['归谁管'], sections: ['内容'] },
  势力列表: { facts: ['领头的', '对主角', '地盘'], sections: ['内容'] },
  物品功法: { facts: ['品阶', '在谁手里'], sections: ['内容'] },
  往事秘密: { facts: ['谁知道', '打算何时揭开'], sections: ['内容'] },
  特殊规则: { facts: [], sections: ['内容'] },
}

export const FACT_PLACEHOLDERS: Record<string, string> = {
  所属: '哪个宗门、家族、势力',
  归谁管: '哪个势力说了算',
  领头的: '谁说了算',
  对主角: '敌、友、中立，还是想利用他',
  地盘: '在哪些地方',
  品阶: '几品、什么级别',
  在谁手里: '现在归谁',
  谁知道: '哪些人知道，读者知不知道',
  打算何时揭开: '比如第二卷末',
  是什么: '系统、物品、体质、功法、重生记忆……',
}

/** 新增按钮上的叫法：新增人物、新增地点…… */
export function nounOf(category: string): string {
  return ({ 角色列表: '人物', 金手指: '金手指', 等级体系: '一套等级', 地点列表: '地点', 势力列表: '势力', 物品功法: '物品', 往事秘密: '往事', 特殊规则: '规则' } as Record<string, string>)[category] ?? category
}

export const GOLDFINGER_PLACEHOLDERS: Record<string, string> = {
  是什么: '系统、物品、体质、功法、重生记忆……',
  谁知道: '谁知道主角有它',
  能做什么: '读者最爽的那一下是什么',
  规矩和限制: '什么时候能用、什么时候不能用',
  代价: '用一次要付出什么；代价越痛，故事越好看',
  怎么变强: '它会怎么升级，每一级多出什么本事',
  来历: '从哪来；最好落在底牌上',
}

const DIGITS = '零一二三四五六七八九'
/** 1→一，12→十二，25→二十五 */
export function cn(n: number): string {
  if (n < 10) return DIGITS[n]
  if (n < 20) return `十${n % 10 ? DIGITS[n % 10] : ''}`
  if (n < 100) return `${DIGITS[Math.floor(n / 10)]}十${n % 10 ? DIGITS[n % 10] : ''}`
  return String(n)
}

export function findEntry(book: VBook, id: string): VEntry | undefined {
  for (const category of book.categories) {
    const entry = category.entries.find((e) => e.id === id)
    if (entry) return entry
  }
  return undefined
}

export function findNode(node: VNode, id: string, path: VNode[] = []): VNode[] | null {
  if (node.id === id) return [...path, node]
  for (const child of node.children ?? []) {
    const found = findNode(child, id, [...path, node])
    if (found) return found
  }
  return null
}

/** 按顺序给每个卷、单元、章算出「第几章到第几章」。和后台一样：单元（或没拆单元的卷）定了章数、
 *  章纲还没出全的，给没出的章留着号；章数没定的有几章算几章。 */
export function numberChapters(root: VNode): void {
  let next = 1
  const visit = (node: VNode) => {
    node.range = undefined
    if (node.kind === '章') {
      const n = Number(/第(\d+)章/.exec(node.title)?.[1] ?? next)
      node.range = [n, n]
      next = n + 1
      return
    }
    const start = next
    node.children?.forEach(visit)
    const leaf = node.kind === '单元' || (node.kind === '卷' && !node.children?.length)
    if (leaf && node.chapters && next - start < node.chapters) next = start + node.chapters
    if (next > start) node.range = [start, next - 1]
  }
  visit(root)
}

/** 把条目名字在大纲里出现的地方连起来：条目的「出现在」和大纲节点的「用到的设定」。
 *  「出现在」只列最底下那一层：第 1 章提到了，就不再把它上面的单元、卷、篇也列一遍。 */
export function linkMentions(book: VBook): void {
  const entries = book.categories.flatMap((c) => c.entries)
  const mark = (node: VNode) => {
    const text = [node.text, ...(node.sections ?? []).map((s) => s.text)].join('\n')
    for (const entry of entries) {
      const names = [entry.name.replace(/（.*?）|\(.*?\)/g, '')].filter((n) => n.length >= 2)
      if (!node.uses.includes(entry.id) && names.some((n) => text.includes(n))) node.uses.push(entry.id)
    }
    node.children?.forEach(mark)
  }
  // 返回这一层或下面有没有提到；下面提到了，这一层就不进「出现在」
  const collect = (node: VNode, entry: VEntry): boolean => {
    let below = false
    for (const child of node.children ?? []) if (collect(child, entry)) below = true
    const here = node.uses.includes(entry.id)
    if (here && !below && node.kind !== '全书' && entry.appears.length < 4) entry.appears.push({ node: node.id, label: node.title })
    return here || below
  }
  const trim = (node: VNode) => {
    node.uses = node.uses.slice(0, 10)
    node.children?.forEach(trim)
  }
  mark(book.outline)
  for (const entry of entries) collect(book.outline, entry)
  trim(book.outline)
}

/** 「第一卷」加全角空格加「杂役院」：拆成前缀和名字，前缀程序排，名字作者起。 */
export function splitTitle(title: string): [string, string] {
  const at = title.indexOf('　')
  return at < 0 ? [title, ''] : [title.slice(0, at), title.slice(at + 1)]
}

/** 等级体系、自建的阶梯类没有栏目可调。 */
export function isLadder(category: VCategory): boolean {
  return category.name === '等级体系' || category.custom?.style === 'ladder'
}

/** 一类默认有哪几栏：内置的照 DEFAULT_FIELDS，自建的照建的时候选的。 */
export function defaultTemplateFor(category: VCategory): CardTemplate {
  const item = (key: string): FieldItem => ({ key, label: key })
  const preset = DEFAULT_FIELDS[category.name]
  if (preset && !category.custom) return { facts: preset.facts.map(item), sections: preset.sections.map(item) }
  if (category.custom?.style === 'card') return { facts: [], sections: category.custom.fields.map(item) }
  return { facts: [], sections: [item('内容')] }
}

export function templateOf(book: VBook, category: VCategory): CardTemplate {
  return book.layouts[category.key] ?? defaultTemplateFor(category)
}

function hintOf(key: string): string | undefined {
  return CHARACTER_PLACEHOLDERS[key] ?? GOLDFINGER_PLACEHOLDERS[key] ?? FACT_PLACEHOLDERS[key]
}

/** 这一条某一栏写的内容：小字和正文栏目里都找。 */
export function valueOf(entry: VEntry, key: string): string {
  const fact = entry.facts.find(([label]) => label === key)
  if (fact) return fact[1]
  return entry.sections.find((s) => (s.key ?? s.label) === key)?.text ?? ''
}

/** 按这本书的栏目重新摆一条：内容按 key 找，改了名也跟着走；栏目里没有、但写了内容的，接在最后，不藏起来。 */
export function applyTemplate(entry: VEntry, template: CardTemplate): VEntry {
  if (entry.kind === 'ladder') return entry
  const keys = new Set([...template.facts, ...template.sections].map((f) => f.key))
  const placeholder = (f: FieldItem) => (f.label === f.key ? entry.sections.find((s) => (s.key ?? s.label) === f.key)?.placeholder ?? hintOf(f.key) : undefined)
  const leftovers: VField[] = [
    ...entry.facts.filter(([label, value]) => value && !keys.has(label)).map(([label, value]) => ({ key: label, label, text: value })),
    ...entry.sections.filter((s) => s.text && !keys.has(s.key ?? s.label)),
  ]
  return {
    ...entry,
    facts: template.facts.map((f) => {
      const old = entry.facts.find(([label]) => label === f.key)
      return [f.label, valueOf(entry, f.key), f.label === f.key ? old?.[2] ?? hintOf(f.key) : undefined, f.key] as VEntry['facts'][number]
    }),
    sections: [
      ...template.sections.map((f) => ({ key: f.key, label: f.label, text: valueOf(entry, f.key), placeholder: placeholder(f) })),
      ...leftovers,
    ],
  }
}
