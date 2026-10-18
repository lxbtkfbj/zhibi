/** 工作台原型用的假书：只为看样子，不连后台。字段名照真实设定库（library_config.py）。 */

export type Status = '现在要定' | '一句话就好' | '以后再说'

interface EntryBase {
  id: string
  name: string
  oneLine: string
  status: Status
  tags?: string[]
  locked?: boolean
  /** 在大纲里出现的地方：节点 id 和显示的字 */
  appears?: { node: string; label: string }[]
}

export interface CharacterEntry extends EntryBase {
  kind: 'character'
  /** 短的：放右边资料卡 */
  facts: { 别名: string; 定位: string; 性别: string; 年龄: string }
  /** 长的：放正文 */
  long: { 外貌: string; 性格与说话方式: string; 身世: string; 想要什么: string; 能力: string; 和主角的关系?: string; 备注: string }
  /** 设定师每写完一章更新 */
  now?: { 此刻想要: string; 在哪: string; 处境: string; 是否活着: string }
  relations?: { to: string; kind: string; text: string }[]
  /** 身世里「另有秘密」指向的那一条 */
  secret?: string
}

export interface ParagraphEntry extends EntryBase {
  kind: 'paragraph'
  body: string
  belongs?: string
  knownBy?: string
}

export interface LadderEntry extends EntryBase {
  kind: 'ladder'
  overview: string
  levels: { name: string; text: string }[]
}

export type SampleEntry = CharacterEntry | ParagraphEntry | LadderEntry

export interface SampleCategory {
  name: string
  /** 这一类写清什么，照真实配置拆成几句 */
  hints: string[]
  /** 空着时建议从这些开始 */
  starters?: string[]
  entries: SampleEntry[]
}

export const PLACEHOLDERS: Record<string, string> = {
  外貌: '一两处让人记住的地方就够了，比如疤、小动作',
  性格与说话方式: '怎么说话最能看出这个人：话多话少、爱用什么词',
  身世: '公开的来历；藏着的写进「往事与秘密」，这里标一句「另有秘密」',
  想要什么: '长远想要什么，眼下想要什么',
  能力: '会什么本事，有什么限制',
  和主角的关系: '对主角来说，他是谁',
  备注: '随手记：口头禅、忌讳、以后可能用上的点子',
}

export const BOOK = {
  title: '窥命长生',
  channel: '男频',
  genre: '仙侠',
  tags: ['天赋觉醒', '苟道', '宗门', '智斗'],
  length: 200,
  chapters: 800,
  blurb:
    '头顶还剩三天寿命的传功执事，正一脸慈祥地递来一枚“筑基丹”。\n底层杂役陈默一睁眼，就能看破所有人的剩余寿数。\n在这座表面仙风道骨、暗地敲骨吸髓的吃人宗门里，别人的死期，就是他的生机。\n所有人都以为他平平无奇，直到某天，他撞见了那位号称与天地同寿的宗门老祖——\n老祖头顶上的数字，赫然只剩一个时辰。',
}

export const CATEGORIES: SampleCategory[] = [
  {
    name: '角色',
    hints: ['有名有姓、会再出场的人', '会说话的器灵、系统人格也算'],
    entries: [
      {
        kind: 'character',
        id: 'chenmo',
        name: '陈默',
        oneLine: '外门杂役，一睁眼就能看见所有人头顶剩下的寿命。',
        status: '现在要定',
        tags: ['主角', '金手指'],
        facts: { 别名: '小默子', 定位: '主角', 性别: '男', 年龄: '十七岁' },
        long: {
          外貌: '瘦，肤色偏黑，走路总低着头；右手少了半截小指。',
          性格与说话方式: '胆小是装的，记仇是真的。话少，开口先算账；被逼急了反而会笑。',
          身世: '山下猎户家的孩子，十二岁被卖进宗门做杂役。另有秘密。',
          想要什么: '长远：活下去，弄清是谁在收割整座宗门。\n眼下：熬过三天后的外门考核。',
          能力: '窥命之眼：看得见所有人头顶剩下的寿命；看得越久，折自己的寿越多。',
          备注: '',
        },
        now: { 此刻想要: '躲过那枚筑基丹', 在哪: '外门杂役院', 处境: '被传功执事盯上', 是否活着: '活着' },
        relations: [
          { to: 'zhao', kind: '上司', text: '正盯着他，要他吃下丹药' },
          { to: 'laozu', kind: '宿敌', text: '还没见过面，命数却连在一起' },
        ],
        secret: 'origin',
        appears: [
          { node: 'c1', label: '第1章　三天 · 第一次出场' },
          { node: 'v1', label: '第一卷　杂役院 · 全卷' },
        ],
      },
      {
        kind: 'character',
        id: 'zhao',
        name: '赵长河',
        oneLine: '笑眯眯的传功执事，头顶只剩三天寿命，却还在给弟子发丹药。',
        status: '现在要定',
        tags: ['对手', '第一卷'],
        facts: { 别名: '', 定位: '对手', 性别: '男', 年龄: '看着五十，实际一百一十岁' },
        long: {
          外貌: '圆脸，总是笑，袖口永远干干净净。',
          性格与说话方式: '说话慢，爱拍人肩膀，从不发火；越客气越危险。',
          身世: '',
          想要什么: '在死前把这一批“筑基丹”发完。',
          能力: '筑基后期，掌管外门传功堂。',
          和主角的关系: '陈默所在杂役院的上司。',
          备注: '',
        },
        now: { 此刻想要: '让陈默吃下丹药', 在哪: '传功堂', 处境: '寿命只剩三天', 是否活着: '活着' },
        relations: [
          { to: 'chenmo', kind: '下属', text: '盯上了这个装傻的杂役' },
          { to: 'laozu', kind: '主子', text: '替老祖发丹' },
        ],
        appears: [{ node: 'u1', label: '单元一　递丹之局' }],
      },
      {
        kind: 'character',
        id: 'laozu',
        name: '青冥老祖',
        oneLine: '号称与天地同寿的宗门老祖，头顶的数字只剩一个时辰。',
        status: '一句话就好',
        tags: ['对手'],
        facts: { 别名: '', 定位: '对手', 性别: '男', 年龄: '' },
        long: { 外貌: '', 性格与说话方式: '', 身世: '', 想要什么: '', 能力: '', 和主角的关系: '', 备注: '' },
        appears: [{ node: 'book', label: '全书 · 结局' }],
      },
    ],
  },
  {
    name: '等级体系',
    hints: ['怎么往上升、越级多难、有什么代价', '各级写名称和一段介绍，按高低排', '高阶的可以先只列名字，以后再补'],
    entries: [
      {
        kind: 'ladder',
        id: 'realm',
        name: '修炼境界',
        oneLine: '每破一境多一甲子寿命，所以人人都在拼命往上爬。',
        status: '现在要定',
        overview: '往上升靠灵气和丹药，越往上越慢。越级极难：境界差一层，寿命差一截，打起来先怕死的那个输。',
        levels: [
          { name: '炼气', text: '分九层，外门弟子大多卡在这里。' },
          { name: '筑基', text: '寿命翻倍。宗门发的“筑基丹”是唯一捷径。' },
          { name: '金丹', text: '可以开宗立派，青冥宗只有七位。' },
          { name: '元婴', text: '' },
        ],
        appears: [{ node: 'part1', label: '第一篇　外门求生' }],
      },
    ],
  },
  {
    name: '世界与地图',
    hints: ['这是什么地方，给人什么感觉', '属于哪里、谁说了算', '有什么规矩或危险', '主角在这里处境如何、能得到什么'],
    entries: [
      {
        kind: 'paragraph',
        id: 'world',
        name: '世界概况',
        oneLine: '灵气一年比一年稀薄，寿命成了修士最值钱的东西。',
        status: '现在要定',
        body: '东洲七宗分据七山，青冥宗居首。凡人六十而终，修士靠境界续命；境界卡住的人，只能另想办法。钱用灵石，但真正的硬通货是寿元。',
      },
      {
        kind: 'paragraph',
        id: 'yard',
        name: '外门杂役院',
        oneLine: '青冥宗最底下的地方，三百杂役挤在一座山坳里。',
        status: '现在要定',
        belongs: '青冥宗 · 外门',
        body: '每月初一发一次丹药，每年一次外门考核。考不过的人就“下山”了，再没人见过。杂役之间互相盯着，谁多领了一口饭，第二天全院都知道。',
        appears: [{ node: 'v1', label: '第一卷　杂役院' }],
      },
    ],
  },
  {
    name: '势力划分',
    hints: ['什么组织、想要什么', '谁领头、实力多大', '和主角是敌是友', '内部有什么矛盾'],
    entries: [
      {
        kind: 'paragraph',
        id: 'sect',
        name: '青冥宗',
        oneLine: '东洲第一宗，表面仙风道骨，暗地敲骨吸髓。',
        status: '一句话就好',
        body: '',
      },
    ],
  },
  {
    name: '物品与功法',
    hints: ['是什么东西或什么本事', '有什么用、有什么限制', '从哪来、谁想要它', '现在在谁手里'],
    entries: [
      {
        kind: 'paragraph',
        id: 'pill',
        name: '筑基丹',
        oneLine: '宗门每年发给外门弟子的“恩赐”，吃过的人寿命都停在同一天。',
        status: '现在要定',
        tags: ['第一卷'],
        body: '丹房出的，每年初一由传功执事亲手发。吃下去当场破境，三年之内却都会在同一个日子“坐化”。现在陈默手里有一枚没吃的。',
        appears: [{ node: 'u1', label: '单元一　递丹之局' }],
      },
    ],
  },
  {
    name: '往事与秘密',
    hints: ['过去发生了什么，或藏着什么真相', '谁知道、谁不知道', '打算什么时候、怎么揭开', '和主角有什么关系'],
    entries: [
      {
        kind: 'paragraph',
        id: 'secret',
        name: '老祖的寿命',
        oneLine: '老祖靠“筑基丹”把弟子的寿命收到自己身上。',
        status: '现在要定',
        tags: ['底牌'],
        locked: true,
        knownBy: '只有你和编辑部',
        body: '三百年来，每一枚筑基丹都是一张“借命契”。吃丹的人破境越快，被收走的寿命越多。老祖头顶只剩一个时辰，是因为今年的丹还没收回来。',
      },
      {
        kind: 'paragraph',
        id: 'origin',
        name: '陈默的来历',
        oneLine: '陈默是老祖当年收命时漏下的一个孩子。',
        status: '以后再说',
        knownBy: '只有你和编辑部；打算第二篇揭开',
        body: '',
      },
    ],
  },
  {
    name: '特殊规则',
    hints: ['管什么、怎么运作', '有什么限制和代价', '会给故事制造什么麻烦或机会'],
    starters: ['窥命之眼的代价', '寿命能不能转给别人', '宗门门规'],
    entries: [],
  },
]

export interface SampleNode {
  id: string
  kind: '全书' | '篇' | '卷' | '单元' | '章'
  title: string
  text: string
  chapters?: number
  later?: boolean
  locked?: boolean
  /** 这一段用到的设定 */
  uses?: string[]
  children?: SampleNode[]
}

export const OUTLINE: SampleNode = {
  id: 'book',
  kind: '全书',
  title: '全书',
  text: '结局：陈默掀了青冥宗的命簿，自己却成了下一个看守它的人。',
  uses: ['chenmo', 'laozu', 'secret'],
  children: [
    {
      id: 'part1',
      kind: '篇',
      title: '第一篇　外门求生',
      text: '舞台是青冥宗外门。陈默想在外门考核前活下来，挡路的是给弟子发“筑基丹”的传功执事。这一篇以陈默揭穿丹药的真相、借执事之死换来进内门的名额收尾。读者一直在等：头顶数字归零的人，到底是怎么死的。',
      uses: ['chenmo', 'zhao', 'yard', 'pill', 'realm'],
      children: [
        {
          id: 'v1',
          kind: '卷',
          title: '第一卷　杂役院',
          chapters: 12,
          locked: true,
          text: '这一卷陈默要做成一件事：在不暴露眼睛的前提下，活过赵长河发丹的那一天。卷首他还是任人使唤的杂役；卷末，他看着赵长河在众目睽睽之下化成一具枯骨，而自己手里多了一枚没吃的丹药。',
          uses: ['chenmo', 'zhao', 'yard', 'pill'],
          children: [
            {
              id: 'u1',
              kind: '单元',
              title: '单元一　递丹之局',
              chapters: 4,
              text: '赵长河当众点名，要把一枚“筑基丹”赏给陈默。陈默看见执事头顶只剩三天，也看见吃过丹的师兄寿命全停在同一天。他装病躲丹，被逼到墙角时，借一场意外把丹换了出去。',
              uses: ['chenmo', 'zhao', 'pill'],
              children: [
                { id: 'c1', kind: '章', title: '第1章　三天', uses: ['chenmo', 'zhao'], text: '发生什么：陈默第一次看见所有人头顶的数字，最长的那个属于传功执事——只剩三天。\n看点：一个杂役看穿了整个宗门的死期。\n结尾钩子：执事笑着朝他招手：“陈默，过来领丹。”' },
                { id: 'c2', kind: '章', title: '第2章　筑基丹', uses: ['chenmo', 'pill'], text: '发生什么：陈默装病躲丹，发现吃过丹的师兄们寿命都停在同一天。\n看点：同一个日期，像一张死亡名单。\n结尾钩子：那一天，就是三天后。' },
                { id: 'c3', kind: '章', title: '第3章　少半截的小指', uses: ['chenmo', 'zhao'], text: '发生什么：执事亲自上门送丹，陈默用断指的旧伤骗过搜身。\n看点：装傻和算计。\n结尾钩子：执事走时回头看了他一眼，头顶的数字变了。' },
                { id: 'c4', kind: '章', title: '第4章　执事的数字', uses: ['zhao', 'laozu'], text: '发生什么：陈默发现执事的寿命不是在减，而是在被“收走”。\n看点：真相露出一角。\n结尾钩子：收走寿命的那只手，来自后山。' },
              ],
            },
            { id: 'u2', kind: '单元', title: '单元二　外门考核', chapters: 5, text: '考核前夜，杂役院死了第一个人。陈默要在考核里不出头、不垫底，还得弄清谁动的手。', uses: ['chenmo', 'yard'] },
            { id: 'u3', kind: '单元', title: '单元三　借命', chapters: 3, text: '执事死期到了。陈默把那枚没吃的丹药，换成了进内门的门票。', uses: ['chenmo', 'zhao', 'pill'] },
          ],
        },
        { id: 'v2', kind: '卷', title: '第二卷　内门试炼', later: true, text: '暂定：进了内门，陈默发现内门弟子头顶的数字，全都指向同一个时辰。' },
      ],
    },
    { id: 'part2', kind: '篇', title: '第二篇', later: true, text: '' },
  ],
}

export const PENDING = [
  { id: 'p1', text: '境界改名后，「外门杂役院」里还写着“灵海”，要不要一起换？' },
  { id: 'p2', text: '大纲里出现了新人物「孙婆婆」，要给她建一张角色卡吗？' },
]

export const CHAT = [
  { who: '主编', text: '简介我看了，开局“递丹”那一下很抓人。设定和大纲还空着，要我按简介先补一版吗？你写过的不会动。' },
  { who: '作者', text: '先别，我自己想想主角。' },
  { who: '主编', text: '好，想好了叫我。主角的“想要什么”写具体些，后面大纲好接。' },
]

export function findEntry(id: string): { category: SampleCategory; entry: SampleEntry } | null {
  for (const category of CATEGORIES) {
    const entry = category.entries.find((e) => e.id === id)
    if (entry) return { category, entry }
  }
  return null
}
