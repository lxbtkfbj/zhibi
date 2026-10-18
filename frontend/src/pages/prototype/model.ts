/** 工作台原型的数据形状：示例书、空书、旧书快照、书架上的真书，都先转成这个样子再画。 */

export interface VField {
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
  /** 右边资料卡里的短字段：名称、内容、空着时的提示 */
  facts: [string, string, string?][]
  /** 一栏一栏的长字段（角色卡、金手指、自定栏目的卡片） */
  sections: VField[]
  /** 段落类的那一段话 */
  body?: string
  /** 角色此刻的状态，设定师每章更新；全空就不显示 */
  now?: [string, string][]
  relations?: { to: string; kind: string; text: string }[]
  /** 身世里「另有秘密」指向的条目 */
  secret?: string
  /** 角色的金手指条目 / 金手指的主人 */
  goldfinger?: string
  holder?: string
  overview?: string
  levels?: { name: string; text: string }[]
  /** 地点属于哪里：父条目 id */
  parent?: string
  /** 秘密：谁知道 */
  knownBy?: string
  appears: { node: string; label: string }[]
}

export interface VCategory {
  name: string
  /** 一句话说清这一类放什么 */
  about: string
  example?: { name: string; text: string }
  entries: VEntry[]
  /** 作者自建的类别：样式和卡片的栏目 */
  custom?: { style: 'paragraph' | 'card' | 'ladder'; fields: string[] }
}

export interface VNode {
  id: string
  kind: '全书' | '篇' | '卷' | '单元' | '章'
  title: string
  text: string
  /** 章纲：发生什么、看点、结尾钩子 */
  sections?: VField[]
  chapters?: number
  /** 第几章到第几章，程序按顺序算 */
  range?: [number, number]
  /** 写到哪了：没写 / 正在写 / 写完 */
  progress?: string
  later?: boolean
  locked?: boolean
  uses: string[]
  children?: VNode[]
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
}

/** 八个默认类别。名字三到五个字；from 是真实设定库里对应的类别。 */
export const CATEGORY_DEFS: { name: string; from: string[]; about: string; example?: { name: string; text: string } }[] = [
  { name: '角色列表', from: ['角色卡片'], about: '有名有姓、会再出场的人；会说话的器灵、系统人格也算。' },
  { name: '金手指', from: [], about: '主角最大的倚仗：系统、物品、体质、重生记忆……能做什么、有什么代价、怎么变强。' },
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
  return { name, about: def?.about ?? '', example: def?.example, entries: [] }
}

/** 角色卡的字段（照真实设定库），定位按这个顺序分组。 */
export const ROLE_ORDER = ['主角', '女主', '男主', '班底', '对手', '导师', '配角']
export const LEGACY_ROLES: Record<string, string> = { 反派: '对手', 龙套: '配角' }

export const CHARACTER_PLACEHOLDERS: Record<string, string> = {
  外貌: '一两处让人记住的地方就够了，比如疤、小动作',
  性格与说话方式: '怎么说话最能看出这个人：话多话少、爱用什么词',
  身世: '公开的来历；藏着的写进「往事秘密」，这里标一句「另有秘密」',
  想要什么: '长远想要什么，眼下想要什么',
  能力: '会什么本事，有什么限制',
  和主角的关系: '对主角来说，他是谁',
  备注: '随手记：口头禅、忌讳、以后可能用上的点子',
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

/** 按顺序给每个卷、单元、章算出「第几章到第几章」。 */
export function numberChapters(root: VNode): void {
  let next = 1
  const visit = (node: VNode) => {
    if (node.kind === '章') {
      const n = Number(/第(\d+)章/.exec(node.title)?.[1] ?? next)
      node.range = [n, n]
      next = n + 1
      return
    }
    const start = next
    if (node.children?.length) node.children.forEach(visit)
    else if (node.chapters) next += node.chapters
    if (next > start) node.range = [start, next - 1]
  }
  visit(root)
}

/** 把条目名字在大纲里出现的地方连起来：条目的「出现在」和大纲节点的「用到的设定」。 */
export function linkMentions(book: VBook): void {
  const entries = book.categories.flatMap((c) => c.entries)
  const visit = (node: VNode) => {
    const text = [node.text, ...(node.sections ?? []).map((s) => s.text)].join('\n')
    for (const entry of entries) {
      const names = [entry.name.replace(/（.*?）|\(.*?\)/g, '')].filter((n) => n.length >= 2)
      if (!node.uses.includes(entry.id) && names.some((n) => text.includes(n))) node.uses.push(entry.id)
      if (node.uses.includes(entry.id) && node.kind !== '全书' && entry.appears.length < 4 && !entry.appears.some((a) => a.node === node.id)) {
        entry.appears.push({ node: node.id, label: node.title })
      }
    }
    node.uses = node.uses.slice(0, 10)
    node.children?.forEach(visit)
  }
  visit(book.outline)
}
