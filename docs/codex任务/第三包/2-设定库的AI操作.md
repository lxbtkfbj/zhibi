# 任务 2：设定库的 AI 操作

> 先读 `docs/codex任务/第三包/README.md` 和 `docs/设计说明.md` 第 13 节（重点 13.2、13.4），并确认任务 1 已完成并提交。

## 目标

让 AI 能帮作者改设定库，而且只改作者点中的那一处：

- **改这一句／改这一项**：给几个写法、照作者的意思改、写细一点、精简一点；
- **补漏**：看还缺什么，建议新增条目或自建类别；
- **查一遍**：整库查，或只查一条，列出矛盾、同根、好看、题材、该定没定的问题；
- **连带建议**：改了专有名词的叫法，别的条目、大纲、定调里提到旧叫法的，各挂一条建议；正文已经用到的，挂一条「前文也一起换」的建议；
- **群聊找目标**：书空闲时，作者在群聊里说「把境界名称重想一下」，主编找到那一处，出几个写法。

这些操作都在接口里直接调用模型、直接返回（不走后台任务），所以写作进行中也能用。这个任务只做后端；页面在任务 4。

## 1. 结构化产出（`app/agents/schemas.py` 末尾新增）

逐字照抄，字段顺序也照抄：

```python
class Renamed(Lenient):
    old: str = Field(description="原来的叫法（人名、地名、境界名、物品名等专有名词），照原文抄")
    new: str = Field(description="改成的新叫法")


class RewriteOption(Lenient):
    label: Literal["稳妥", "大胆", "出格"] = Field(description="这种写法的大胆程度")
    text: str = Field(
        description="换上去的新文字：只写要改的那一处，不写别的部分；格式和原文一致（原文是一句就写一句，原文是一段就写一段）"
    )
    renamed: list[Renamed] = Field(default_factory=list, description="这种写法里改了叫法的专有名词；没改就留空")
    one_line: str = Field(
        default="", description="只在改的是一段话、而且这一条的一句话也该跟着变时，写新的一句话；否则留空"
    )


class RewriteOptions(Lenient):
    options: list[RewriteOption] = Field(description="三种写法，依次是稳妥、大胆、出格；稳妥的最贴近原来的意思")
    note: str = Field(default="", description="给作者的一句话：三种写法各自好在哪，推荐哪一种")


class RewriteOne(Lenient):
    text: str = Field(description="换上去的新文字：只写要改的那一处，不写别的部分；格式和原文一致")
    renamed: list[Renamed] = Field(default_factory=list, description="改了叫法的专有名词；没改就留空")
    one_line: str = Field(
        default="", description="只在改的是一段话、而且这一条的一句话也该跟着变时，写新的一句话；否则留空"
    )
    note: str = Field(default="", description="给作者的一句话：改了什么")


class FieldValue(Lenient):
    name: str = Field(description="字段名")
    value: str = Field(description="字段的内容")


class NewEntry(Lenient):
    category: str = Field(
        description="放进哪一类：角色卡片、等级体系、世界与地图、势力划分、物品与功法、往事与秘密、特殊规则，或已有的自建类别的名字"
    )
    name: str = Field(description="条目名称；角色卡片写人名")
    status: Literal["现在要定", "一句话就好", "以后再说"] = Field(description="现在要定、一句话就好、以后再说")
    one_line: str = Field(description="一句话")
    content: str = Field(default="", description="一段话；状态是一句话就好、以后再说的留空；角色卡片和卡片样式的类别留空，写在 fields 里")
    fields: list[FieldValue] = Field(
        default_factory=list,
        description="角色卡片写定位、性别、年龄、外貌、性格与说话方式、身世、想要什么、能力、和主角的关系；卡片样式的自建类别写它的字段；其他留空",
    )
    why: str = Field(description="为什么要补这一条，一句话")


class NewCategory(Lenient):
    name: str = Field(description="自建类别的名字，如「厉鬼」「剧本」「灵宠」")
    style: Literal["卡片", "段落"] = Field(description="卡片还是段落")
    fields: list[str] = Field(default_factory=list, description="卡片样式的字段名，按顺序；段落样式留空")
    hint: str = Field(description="这一类一段话里该说清什么，一句话")
    why: str = Field(description="为什么这本书需要这一类，一句话")


class GapReport(Lenient):
    entries: list[NewEntry] = Field(default_factory=list, description="建议新增的条目，最多 8 条；已有的不要重复")
    categories: list[NewCategory] = Field(
        default_factory=list, description="建议新建的自建类别，最多 2 个；七个默认类别放得下的不要建"
    )
    note: str = Field(default="", description="给作者的一句话总结")


class LibraryIssue(Lenient):
    kind: Literal["矛盾", "同根", "好看", "题材", "该定没定", "其他"] = Field(description="问题属于哪一类")
    title: str = Field(description="给作者看的一句话：哪里有问题")
    target_name: str = Field(default="", description="问题在哪一条（条目或角色卡片的名称）；涉及好几条写最主要的一条")
    quote: str = Field(default="", description="要改的原文，从那一条里照抄一句；不需要改原文的留空")
    fix: str = Field(default="", description="建议换成的文字，只写换掉 quote 的那一句；没有具体改法的留空")
    why: str = Field(description="为什么，一句话")


class LibraryReview(Lenient):
    issues: list[LibraryIssue] = Field(
        default_factory=list, description="查出的问题，按严重程度排，最多 10 条；没有问题就留空"
    )
    note: str = Field(default="", description="给作者的一句话总结")


class LibraryIntent(Lenient):
    kind: Literal["改设定", "其他"] = Field(
        description="作者这句话是不是要改设定库里的某一处；是写作要求、提问或闲聊的选「其他」"
    )
    target_name: str = Field(default="", description="要改哪一条：条目或角色卡片的名称，照设定库目录里的写法")
    part: str = Field(
        default="", description="改这一条的哪一处：卡片的字段名、等级的级名、「名称」「一句话」「一段话」"
    )
    quote: str = Field(default="", description="只改其中一句时，把那一句从原文里照抄出来；否则留空")
    mode: Literal["给几个写法", "照作者的意思改"] = Field(
        default="给几个写法",
        description="作者只说了不满意、没说怎么改的，选给几个写法；说清了怎么改的，选照作者的意思改",
    )
    instruction: str = Field(default="", description="作者想怎么改，用作者的话概括一句")
    reply: str = Field(description="主编在群聊里回作者的一句话")
```

## 2. 提示词

把 `docs/codex任务/第三包/提示词/` 下的四份用 `git mv -f` 搬进 `backend/app/prompts/`：

| 文件 | 变量 |
|---|---|
| `library_rewrite.md` | `concept`、`library`、`target_full`、`related`、`target_label`、`current`、`category_hint`、`mode` |
| `library_fill_gaps.md` | `concept`、`genre_defaults`、`library`、`requirements` |
| `library_review.md` | `concept`、`library_full`、`outline`、`scope` |
| `library_route.md` | `library`、`note` |

登记到 `app/prompts/catalog.py`：

```python
("library_rewrite", "改一处", "设定库", "lorekeeper", "作者让 AI 改设定库或大纲里的一处"),
("library_fill_gaps", "补漏", "设定库", "chief", "看设定库还缺什么"),
("library_review", "查一遍", "设定库", "reviewer", "查设定库的矛盾、同根、好看、题材"),
("library_route", "群聊找目标", "设定库", "chief", "作者在群聊里要改设定时找到那一处"),
```

`VARIABLE_LABELS` 补上（已有的不动）：`library` 设定库目录、`library_full` 设定库全文、`target_full` 这一条的全文、`related` 相关的条目、`target_label` 要改的地方、`current` 原文、`category_hint` 这一类该写清什么、`mode` 怎么改、`genre_defaults` 题材和常建的条目、`scope` 这次查什么、`note` 作者的话。

系统提示用 `persona(角色)`，和现有调用一致；角色见上表第四列。

## 3. 拼给模型的文字（`app/services/library_context.py`，逐字照抄）

### 3.1 定调 `concept`

- `concept.story` 不空：

  ```
  {story}
  底牌（只有作者和编辑部知道）：{底牌那一条的 content 或 one_line}
  ```

  没有底牌那一条时不写第二行。
- `concept.story` 空着（旧书）：用现有的 `format_concept(concept)`。

### 3.2 设定库目录 `library`

按 `GET /library` 的类别顺序，每类一段，空的类别不写：

```
【角色卡片】
- 楚风（主角）：{one_line}
- 后面的红颜（以后再说）：{one_line}
【等级体系】
- 武道境界：{one_line}
【世界与地图】
- 世界概况：{one_line}
- 青阳城（属于天风国）：{one_line}
【厉鬼】（自建类别）
- 末班车司机（已锁）：{one_line}
```

- 角色卡片名字后括号里写定位；
- 状态是「以后再说」的加「（以后再说）」，锁住的加「（已锁）」，几个括号依次写在一起，如「（主角）（已锁）」；
- 地方有上级的写「（属于{上级名称}）」；
- `one_line` 空的只写名称。

### 3.3 一条的全文 `target_full`、`related` 和 `library_full`

`entry_full_text(target)`：

- 段落样式：

  ```
  {类别} · {名称}
  一句话：{one_line}
  {content}
  ```

- 阶梯样式：

  ```
  {类别} · {名称}
  总说明：{content}
  各级（从低到高）：
  1. {名称}：{介绍}
  2. {名称}：{介绍}
  ```

- 角色卡片：第一行 `角色卡片 · {姓名}`，之后按 `CHARACTER_CATEGORY.fields` 的顺序逐行 `{字段名}：{值}`（空的不写，别名用顿号连起来），最后 `此刻想要：{want}`（空的不写）。
- 卡片样式的自建类别：第一行 `{类别名} · {名称}`，之后逐行 `{字段名}：{值}`。
- 大纲节点：`大纲 · 第 {N} 篇「{篇名}」：{text}`、`大纲 · 第 {N} 卷「{卷名}」：{summary}`、`大纲 · 单元「{单元名}」：{summary}`；定调：`定调：{story}`。

`related`：目标全文里出现过名称或别名的其他条目和角色卡片（最多 8 条，按出现先后），逐条 `entry_full_text`，之间空一行；一条都没有就写「（没有）」。

`library_full`：整个设定库逐条 `entry_full_text`，类别顺序同目录，条目之间空一行。

### 3.4 要改的地方 `target_label`

`{类别} · {条目名} · {部分}`，部分按路径写：

| 路径 | 部分 |
|---|---|
| `content` | 一段话（阶梯样式写「总说明」） |
| `one_line` | 一句话 |
| `name` | 名称 |
| `fields.<字段名>`，或角色卡片的列 | 字段名（角色卡片按 `CHARACTER_CATEGORY` 的中文名） |
| `levels.<i>.name` | 第 {i+1} 级「{级名}」的名称 |
| `levels.<i>.text` | 第 {i+1} 级「{级名}」的介绍 |

带 `@起:止` 的，部分后面加「里选中的一句」。大纲和定调分别写 `大纲 · 第 {N} 篇「{篇名}」 · 一段话`（或「篇名」）、`大纲 · 第 {N} 卷「{卷名}」 · 一段话`、`大纲 · 单元「{单元名}」 · 一段话`、`定调 · 一段话`。

### 3.5 原文 `current`、这一类该写清什么 `category_hint`

- `current`：路径指向的那一处文字；带 `@起:止` 的只取选中的那一段。
- `category_hint`：取 `BUILTIN_CATEGORIES`、`CHARACTER_CATEGORY` 或自建类别的 `hint`；大纲节点写「这一层的一段话要说清的事，见大纲的写法」；定调写「一段话说清这本小说主要讲什么故事」。

### 3.6 怎么改 `mode`

| 模式 | 文字 |
|---|---|
| `options` | 给三种写法：稳妥、大胆、出格。稳妥的最贴近原来的意思，只把它写得更好；大胆的换一个更抓人的方向；出格的走一步险棋，但要和定调、底牌对得上。 |
| `instruction` | 照作者的意思改：{instruction}。作者没提到的意思，原样保留。 |
| `expand` | 写细一点：把这一处展开写具体，原来的意思一个都不能丢。 |
| `shorten` | 精简一点：把这一处压短，留下最要紧的意思。 |

### 3.7 题材和常建的条目 `genre_defaults`

```
这本书的题材：{book.genre，空的写「没写」}
这类书常建的条目（只是起点，按定调增减）：
- {类别} · {名称}（{状态的中文}）
```

按题材名挑 `GENRE_DEFAULTS` 里最接近的一组：含「玄幻」「仙侠」「修仙」→ 玄幻、仙侠；含「都市」→ 都市；含「无限」「网游」「游戏」→ 无限流、网游；含「悬疑」「灵异」「惊悚」「怪谈」→ 悬疑、灵异；含「历史」「宫斗」「官场」「宅斗」→ 历史、宫斗、官场。都不含的，五组全部列出，每组前面加一行 `【{组名}】`。

### 3.8 大纲 `outline` 和查什么 `scope`

- `outline`：按 `outline-tree` 逐篇写 `第 {N} 篇「{篇名}」：{text 或 event}`，篇下逐卷写 `  第 {N} 卷「{卷名}」：{summary}`；还没有大纲写「（还没有大纲）」。
- `scope`：查整库写「查整个设定库。」；查一条写「只查这一条：{target_label 去掉部分}；需要时对照别的条目。」

## 4. 接口（`app/api/library_ai.py`）

所有操作在请求里直接调模型（`LLMRouter(sessionmaker, book_id=…)`，用完 `aclose`）。模型出错返回 502「模型出错了：{原因}」。每次操作在群聊里发一条消息（`post_message`，`job_id` 为空，说话人见下），让作者事后看得到改过什么。

### 4.1 改一处

`POST /books/{book_id}/library/rewrite`

```json
{"target_type": "entry", "target_id": "…", "path": "levels.2.text", "mode": "options", "instruction": ""}
```

- `target_type`：`entry`、`character`、`concept`、`segment`、`volume`、`unit`；`path` 按任务 1 第 5 节，可以带 `@起:止`。
- `mode`：`options`、`instruction`、`expand`、`shorten`；`instruction` 模式下 `instruction` 不能空（422「先写一句你想怎么改」）。
- 目标锁住时（条目或角色卡片 `locked`，卷和单元 `locked`，篇的节点 `pinned`），返回 409「已锁：AI 不能改这一处，先解锁」。
- 角色卡片不能改每章更新的状态（`want`、`location`、`condition`、`is_alive`），返回 422。
- 调 `library_rewrite`（设定师），`options` 模式用 `RewriteOptions`，其余用 `RewriteOne`。
- **`options`**：新建一条候选（任务 1 的 `setting_candidates`）：`base` 是原文，`options` 存 `[{label, text, renamed, one_line}]`。返回 `{"candidate": …}`，不改目标。群聊（设定师）：`我给「{条目名}」的{部分}出了三种写法，去设定库挑一个。`
- **其他三种**：用 `splice(target, path, text, base=原文)` 换进去，记一版（`source = 'ai'`，`note` 写模式的中文名，如「照作者的意思改」），再按第 5 节生成连带建议。返回 `{"applied": {"path", "before", "after"}, "version": N, "suggestions": [...]}`。群聊（设定师）：`照你的意思改了「{条目名}」的{部分}。`（写细、精简分别换成「写细了」「精简了」）
- 模型返回的 `one_line` 不空、而且改的是 `content` 时，不直接改，挂一条连带建议（`set_field`，路径 `one_line`，标题「『{条目名}』的一段话改了，一句话要不要跟着换成：{one_line}」）。

### 4.2 选候选（扩展任务 1 的接口）

`POST /candidates/{id}/choose` 换进去以后，按选中那一项的 `renamed`、`one_line`，同样按第 5 节生成连带建议；返回值加上 `suggestions`。

### 4.3 补漏

`POST /books/{book_id}/library/fill-gaps`：调 `library_fill_gaps`（主编），每条 `entries` 生成一条建议（`kind = 'fill_gap'`）：

- 角色卡片：`op = create_character`，`fields` 按 `CHARACTER_CATEGORY` 的中文字段名对上列；`one_line`、`status` 一起写入；
- 其他类别：`op = create_entry`，类别名先对上内置类别或这本书的自建类别（按名称），对不上的放进「特殊规则」；
- 标题：`补一条{类别}：「{名称}」——{why}`。

每个 `categories` 生成一条建议，`op = create_category`（这个任务新增，见第 6 节），标题 `建一个自建类别「{名称}」——{why}`。返回 `{"suggestions": [...], "note": "…"}`；群聊（主编）发 `note`。

### 4.4 查一遍、查一查

- `POST /books/{book_id}/library/review`：查整库；
- `POST /books/{book_id}/library/check`：`{"target_type", "target_id"}`，只查一条。

调 `library_review`（审稿）。每条 `issues` 生成一条建议（`kind = 'review'`）：

- `target_name` 对得上一条条目或角色卡片，`quote` 在那一条的某个字段里找得到，`fix` 不空：`op = splice`，路径是那个字段加 `@起:止`，`base = quote`，`new = fix`；
- 否则 `op = note`。
- 标题：`【{kind}】{title}`。

返回 `{"suggestions": [...], "note": "…"}`；群聊（审稿）发 `note`，没有问题时发「查过了，没发现问题。」

### 4.5 群聊找目标

改 `POST /books/{book_id}/notes`（`app/api/jobs.py` 的 `add_note`）：**书空闲**（没有进行中或等作者的任务）时，先调 `library_route`（主编，`LibraryIntent`）：

1. `kind = 其他`：照原来的做法记成作者要求，回「记下了，下次开工就照办。」
2. `kind = 改设定`：
   - 按 `target_name` 找条目或角色卡片（先比名称，再比别名，再找名称包含它的；找到多条取第一条）。找不到：主编回「没找到「{target_name}」这一条。去设定库点那一处改，或者告诉我它在哪一类。」，不记成要求。
   - 按 `part` 定路径：卡片字段名、等级的级名（`levels.<i>.text`；作者说名称时 `levels.<i>.name`）、「名称」「一句话」「一段话」；对不上的，段落样式用 `content`，卡片用第一个非空字段。`quote` 不空、而且在那一处找得到时，加上 `@起:止`。
   - 按 `mode` 调 4.1 的改一处（`给几个写法` → `options`，`照作者的意思改` → `instruction`，`instruction` 用模型概括的那句）。
   - 主编在群聊回 `reply`；改一处自己的群聊消息照常发。
   - 不记成作者要求。
3. 书**不空闲**时（开书或写作中），照原来的做法，不调这个提示词。

## 5. 连带建议

改一处换进去以后（4.1 的后三种、4.2 的选候选），以及作者在接口里改了**名称**（条目的 `name`、`aliases`，阶梯某一级的名称，角色卡片的 `name`、`aliases`）以后，对每一对「旧叫法 → 新叫法」：

1. **设定库、大纲和定调**：在这些地方找旧叫法：条目的 `name`、`one_line`、`content`、`fields` 的值、`levels` 的名称和介绍；角色卡片的文字列（不含每章更新的状态）；`concept.story`；篇的 `title`、`text`；卷和单元的 `summary`。被改的那一处本身跳过。每个找到的「目标 + 路径」挂一条建议：`kind = 'cascade'`，`op = replace_text`，标题「『{旧叫法}』改成了『{新叫法}』，「{目标名}」的{部分}里还写着旧叫法，要不要一起换？」；目标锁住的，标题后面加「（已锁）」。
2. **已经写进正文的**：在定稿的章节正文里找旧叫法。有的话挂一条建议：`kind = 'written'`，`op = replace_in_chapters`（第 6 节），标题「『{旧叫法}』在第 {章号，用顿号连起来，最多列 10 个，多了写「等 N 章」} 章的正文里出现过，要不要把前文也一起换成『{新叫法}』？」；`payload` 里带上每章出现的次数，和每章前三处的上下文（前后各 15 字），给页面列出来。
3. 同一个目标、同一个路径、同一对叫法，已经有待处理的建议就不再挂。
4. 作者改名称时，旧叫法是原来的名称，新叫法是新名称；名称没变不挂。只改了 `content` 这类长文字的，不猜叫法，不挂建议。

## 6. 新增两种建议操作（扩展任务 1 第 6 节）

| `op` | 字段 | 做什么 |
|---|---|---|
| `create_category` | `category`（`name`、`style`、`fields`、`hint`） | 新建自建类别；`style` 的「卡片」「段落」换成 `card`、`paragraph` |
| `replace_in_chapters` | `old`、`new`、`chapters`（章号列表） | 逐章：先给这一章记一版（`target_type = 'chapter'`，快照是 `title` 和 `content`），再把正文里所有旧叫法换成新叫法，重算字数 |

版本的 `target_type` 加上 `chapter`，`snapshot_of`、`apply_snapshot` 跟着支持；章节的版本也能退回。

## 7. 演示模式

`app/llm/demo.py` 补上新增的结构化产出，结果固定、可预期，方便测试和验收：

- `RewriteOptions`：三项，`text` 分别是「（稳妥）{原文}」「（大胆）{原文}」「（出格）{原文}」（原文从提示词「原文：」下一行取，取不到写「新写法」）；原文里有「灵海」时，第二项的 `renamed` 是 `[{"old": "灵海", "new": "灵渊"}]`，`text` 里同时把灵海换成灵渊；
- `RewriteOne`：`text` 是「{原文}（已按要求修改）」，`renamed` 为空；
- `GapReport`：一条「物品与功法 · 九叶还魂草（一句话就好）」，一条角色卡片「楚雄」（定位：对手）；目录里有「厉鬼」二字时，再给一个自建类别「厉鬼」（卡片：外形、杀人规律、怎么应对、现在在哪）；
- `LibraryReview`：一条「好看」（`note` 类），一条「矛盾」：在目录里找第一个有一段话的条目，`quote` 取它的第一句，`fix` 是这一句加「（已改）」；
- `LibraryIntent`：作者的话里有「改」「重想」「换个」时，`kind = 改设定`，`target_name` 取目录里第一个出现在作者话里的名称（都没有就取第一条），`mode = 给几个写法`；否则 `kind = 其他`。

## 8. 测试

- 改一处：
  - `options` 只建候选、不改目标；三项存全；
  - `instruction`、`expand`、`shorten` 只换那一处，其余字段和其余句子一个字不动；带 `@起:止` 时只换那一段；原文改过时报错；
  - 锁住、改每章状态、`instruction` 为空时的错误码；
  - 每次换进去都记一版；退回后内容一致。
- 连带建议：
  - 改了等级的名称，等级以外提到旧叫法的条目、角色卡片、篇、卷、单元、定调各挂一条；锁住的标题带「（已锁）」；重复不挂；
  - 正文用到时挂一条 `written`，章号、次数、上下文正确；接受后逐章替换、记版本、能退回；
  - 作者改名称挂建议；只改一段话不挂；
  - 选候选时按那一项的 `renamed` 挂建议；`one_line` 不空时挂 `set_field` 建议。
- 补漏：三种建议各一条，类别对不上的放进特殊规则；`create_category` 接受后类别建好。
- 查一遍：`splice` 类和 `note` 类各一条；`quote` 找不到时退成 `note`。
- 群聊找目标：空闲时「改设定」建候选、主编回话、不记成要求；「其他」照旧记成要求；找不到目标时的回话；书不空闲时不调提示词。
- 演示模式下以上全部能跑。

## 9. 验收

在独立环境、演示模式下：

1. 用第二包演示开一本书、写几章（任务 1 已迁移）；
2. 对一条阶梯条目的某一级「给几个写法」，选第二项（会把灵海换成灵渊），看连带建议：其他条目、大纲里提到灵海的各一条，正文用到的一条「前文也一起换」；
3. 接受「前文也一起换」，确认正文换了、版本能退回；
4. 补漏、查一遍各跑一次，接受其中一条；
5. 在群聊说「把境界名称重想一下」，确认出了候选、主编回了话、没有记成写作要求；再说「下一章节奏快一点」，确认照旧记成要求。

用接口和群聊验收即可，结果写进 `docs/第三包验收.md` 的「任务 2」小节。这个任务没有界面改动，不用截图。
