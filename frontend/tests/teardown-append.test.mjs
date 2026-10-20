import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { teardownAddedText, teardownAppendEntryText, teardownAppendJunctionText, teardownAppendNotes, teardownAppendSelection, teardownAppendSplitText, teardownAppendVolumeText } from '../src/lib/teardownAppend.ts'

const preview = {
  mode: 'append', previous: { chapters: 500, last: { index: 500, title: '旧的终点' }, original_volumes: true },
  junction: { kind: null, a: 500, b: 501, missing: 0 }, duplicates: { leading: [], content: 0 }, reopen: [], ignored_volumes: 0,
  chapter_count: 100, chars: 100000, excluded: [{ order: 103, title: '番外', chars: 2000 }], volumes: [],
}
const source = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('补章节分章总结严格用补之前总章数，勾回后同步合计和拆书范围', () => {
  assert.equal(teardownAppendSplitText(preview), '新文件分出 100 章，接在第 500 章「旧的终点」后面，补上以后一共 600 章。')
  assert.equal(teardownAppendSplitText(preview, [103, 103, 999]), '新文件分出 101 章，接在第 500 章「旧的终点」后面，补上以后一共 601 章。')
})

test('接缝正好接上不出现，跳章只放接的地方，倒退只在页首警告', () => {
  assert.equal(teardownAppendJunctionText(preview), null)
  assert.deepEqual(teardownAppendNotes(preview), [])
  const jump = { ...preview, junction: { kind: '跳了', a: 500, b: 503, missing: 2 } }
  const jumpText = '原书第 500 章后面接的是原书第 503 章，中间缺 2 章'
  assert.equal(teardownAppendJunctionText(jump), jumpText)
  assert.deepEqual(teardownAppendNotes(jump), [jumpText])
  const back = { ...preview, junction: { kind: '倒回去了', a: 500, b: 400, missing: 0 } }
  assert.equal(teardownAppendJunctionText(back), '新文件从原书第 400 章开始，书里已经到原书第 500 章了：是不是传错了文件？')
  assert.deepEqual(teardownAppendNotes(back), [])
})

test('重复章两类分别显示，开头至多列10章，零条各自不出现', () => {
  const leading = Array.from({ length: 12 }, (_, index) => ({ number: 489 + index, title: `旧章${index + 1}` }))
  const notes = teardownAppendNotes({ ...preview, duplicates: { leading, content: 3 } })
  assert.equal(notes[0], `开头 12 章书里已经有了，不再补：${leading.slice(0, 10).map(chapter => `第 ${chapter.number} 章 ${chapter.title}`).join('、')}、还有 2 章。`)
  assert.doesNotMatch(notes[0], /旧章11|旧章12/)
  assert.equal(notes[1], '另有 3 章和书里的正文一模一样，不再补。')
  assert.deepEqual(teardownAppendNotes({ ...preview, duplicates: { leading: [], content: 1 } }), ['另有 1 章和书里的正文一模一样，不再补。'])
  assert.equal(teardownAppendNotes({ ...preview, duplicates: { leading: leading.slice(0, 1), content: 0 } })[0], '开头 1 章书里已经有了，不再补：第 489 章 旧章1。')
})

test('三处收尾只按后台明确列出的项目提醒，单元、原卷总结、主编卷顺序固定', () => {
  const reopen = [
    { kind: 'volume', title: '旧卷名' },
    { kind: 'summary', title: '原书末卷' },
    { kind: 'unit', title: '未完的事', first: 490, last: 500 },
  ]
  const expected = [
    '最后一个单元「未完的事」（第 490–500 章）会和新补的章一起重新归',
    '最后一卷「原书末卷」那段话会重写',
    '最后一卷「旧卷名」会和新补的章一起重新归，名字和那段话会重写',
  ]
  assert.deepEqual(teardownAppendNotes({ ...preview, reopen }), expected)
  for (const [index, item] of reopen.entries()) assert.deepEqual(teardownAppendNotes({ ...preview, reopen: [item] }), [expected[2 - index]])
  assert.deepEqual(teardownAppendNotes(preview), [])
})

test('原书分卷才列卷，继续原卷和新卷措辞不同；只有主编归卷且新文件有卷名才提醒不用', () => {
  assert.equal(teardownAppendVolumeText({ index: 2, title: '第二卷', chapters: 70, continued: true }), '接着第 2 卷 第二卷 · 70 章')
  assert.equal(teardownAppendVolumeText({ index: 3, title: '第三卷', chapters: 30, continued: false }), '第 3 卷 第三卷 · 30 章')
  assert.deepEqual(teardownAppendNotes({ ...preview, ignored_volumes: 2 }), [])
  const chief = { ...preview, previous: { ...preview.previous, original_volumes: false }, ignored_volumes: 2 }
  assert.deepEqual(teardownAppendNotes(chief), ['新文件里写了 2 个卷名，这本书的卷是主编归的，不按文件分卷'])
  assert.deepEqual(teardownAppendNotes({ ...chief, ignored_volumes: 0 }), [])
})

test('接的地方按跳章、开头重复、正文重复、打开收尾、卷名不用的顺序', () => {
  const result = teardownAppendNotes({ ...preview,
    previous: { ...preview.previous, original_volumes: false }, junction: { kind: '跳了', a: 500, b: 503, missing: 2 },
    duplicates: { leading: [{ number: 500, title: '旧章' }], content: 1 },
    reopen: [{ kind: 'unit', title: '旧单元', first: 499, last: 500 }, { kind: 'volume', title: '旧卷' }], ignored_volumes: 2,
  })
  assert.equal(result.length, 6)
  assert.match(result[0], /^原书第/)
  assert.match(result[1], /^开头/)
  assert.match(result[2], /^另有/)
  assert.match(result[3], /^最后一个单元/)
  assert.match(result[4], /^最后一卷/)
  assert.match(result[5], /^新文件里写了/)
})

test('简介补过次数和最近范围来自最后一条，待确认两种入口字与活动状态无关', () => {
  for (const data of [undefined, null, {}, { added: [] }]) assert.equal(teardownAddedText(data), '')
  assert.equal(teardownAddedText({ added: [
    { at: '2026-10-19T10:00:00Z', first: 501, last: 600 },
    { at: '2026-10-20T10:00:00Z', first: 601, last: 700 },
  ] }), ' · 补过 2 次，最近 2026-10-20 补了第 601–700 章')
  for (const stage of ['imported', 'stopped', 'running', 'done']) {
    assert.equal(teardownAppendEntryText({ stage, adding: null }), '补后面的章节')
    assert.equal(teardownAppendEntryText({ stage, adding: { file: 'later.txt', chapters: 100 } }), '补章节还没确认')
  }
  assert.equal(teardownAppendEntryText(), '补后面的章节')
})

const selectablePreview = () => ({ ...preview, chapter_count: 2,
  excluded: [{ order: 0, title: '勾回的开头', chars: 10 }, { order: 3, title: '勾回的末尾', chars: 20 }],
  volumes: [{ index: 3, title: '新的一卷', chapters: 2, continued: false }],
  selection: [
    { order: 0, title: '勾回的开头', number: 501, volume: 2, excluded: true, flags: ['不像正文'] },
    { order: 1, title: '新卷起点', number: 1, volume: 3, excluded: false, flags: [] },
    { order: 2, title: '新卷下一章', number: 2, volume: 3, excluded: false, flags: [] },
    { order: 3, title: '勾回的末尾', number: 3, volume: 3, excluded: true, flags: ['空的'] },
  ],
  last_numbered: { number: 500, volume: 2 },
  reopen_context: { original_volumes: true, open_volume_id: null, last_volume: { index: 2, title: '旧的末卷', summary: true }, tail_unit: { id: 'tail', title: '旧单元', first: 490, last: 500 } },
})

test('勾回开头和末尾时即时重算首尾标题、卷章数、接缝与应打开的单元，不改后台原预览', () => {
  const raw = selectablePreview()
  const before = structuredClone(raw)
  const initial = teardownAppendSelection(raw, [])
  assert.deepEqual(initial.first, { index: 501, title: '新卷起点' })
  assert.deepEqual(initial.last, { index: 502, title: '新卷下一章' })
  assert.equal(initial.junction.kind, null, '新卷从1起不警告')
  assert.deepEqual(initial.reopen, [{ kind: 'summary', title: '旧的末卷' }])
  const restored = teardownAppendSelection(raw, [0, 3, 3, 999])
  assert.deepEqual(restored.first, { index: 501, title: '勾回的开头' })
  assert.deepEqual(restored.last, { index: 504, title: '勾回的末尾' })
  assert.deepEqual(restored.volumes, [
    { index: 2, title: '旧的末卷', chapters: 1, continued: true },
    { index: 3, title: '新的一卷', chapters: 3, continued: false },
  ])
  assert.deepEqual(restored.reopen.map(item => item.kind), ['unit', 'summary'])
  assert.equal(teardownAppendSplitText(restored, [0, 3]), '新文件分出 4 章，接在第 500 章「旧的终点」后面，补上以后一共 504 章。')
  assert.deepEqual(raw, before)
  assert.strictEqual(teardownAppendSelection(preview, [103]), preview, '兼容无selection的旧预览')
})

test('勾回后按新章的顺序重新比章号，跳号、重号、倒退、笔误、新卷和番外与后台一致', () => {
  const raw = selectablePreview()
  const selection = [501, 504, 504, 400, 50, 403].map((number, order) => ({ order, title: `候选${order}`, number, volume: 2, excluded: false, flags: [] }))
  const display = teardownAppendSelection({ ...raw, selection }, [])
  assert.equal(display.junction.kind, null)
  assert.deepEqual(display.number_issues.map(({ index, number, expected, kind }) => ({ index, number, expected, kind })), [
    { index: 502, number: 504, expected: 502, kind: '跳了' },
    { index: 503, number: 504, expected: 505, kind: '重了' },
    { index: 504, number: 400, expected: 505, kind: '倒回去了' },
    { index: 505, number: 50, expected: 401, kind: '倒回去了' },
    { index: 506, number: 403, expected: 51, kind: '跳了' },
  ])
  const typo = teardownAppendSelection({ ...raw, selection: [501, 50, 503].map((number, order) => ({ order, title: '', number, volume: 2, excluded: false, flags: [] })) }, [])
  assert.deepEqual(typo.number_issues.map(issue => issue.kind), ['打错了'])
  const extra = teardownAppendSelection({ ...raw, selection: [
    { order: 0, title: '番外', number: 9, volume: 2, excluded: false, flags: ['番外'] },
    { order: 1, title: '无号', number: null, volume: 2, excluded: false, flags: [] },
    { order: 2, title: '跳章', number: 503, volume: 2, excluded: false, flags: [] },
  ] }, [])
  assert.deepEqual(extra.junction, { kind: '跳了', a: 500, b: 503, missing: 2 })
  assert.equal(extra.number_issues[0].index, 503)
  const noAnchor = teardownAppendSelection({ ...raw, last_numbered: null }, [])
  assert.equal(noAnchor.junction.kind, null)
  assert.deepEqual(noAnchor.number_issues, [])
})

test('勾回实时计划不随无关状态打开收尾，主编已有open卷不改卷名；问题最多列50条', () => {
  const raw = selectablePreview()
  const context = { ...raw.reopen_context, last_volume: { ...raw.reopen_context.last_volume, summary: false }, tail_unit: null }
  assert.deepEqual(teardownAppendSelection({ ...raw, reopen_context: context }, [0]).reopen, [])
  const chief = { ...raw, reopen_context: { ...raw.reopen_context, original_volumes: false } }
  assert.deepEqual(teardownAppendSelection(chief, []).reopen.map(item => item.kind), ['unit', 'volume'])
  assert.deepEqual(teardownAppendSelection({ ...chief, reopen_context: { ...chief.reopen_context, open_volume_id: 'open' } }, []).reopen.map(item => item.kind), ['unit'])
  const selection = Array.from({ length: 100 }, (_, order) => ({ order, title: '', number: 600, volume: 2, excluded: false, flags: [] }))
  const limited = teardownAppendSelection({ ...raw, selection }, [])
  assert.equal(limited.number_issue_total, 100)
  assert.equal(limited.number_issues.length, 50)
})

test('确认页每种条件、原文编码、清理、共用选项、上传框和取消两次严格接现有样式与接口', () => {
  const page = source('../src/pages/Teardown.tsx')
  const append = page.slice(page.indexOf('function TeardownAppendBook'))
  const api = source('../src/api/teardown.ts')
  assert.match(source('../src/main.tsx'), /path: '\/teardown\/:bookId\/append', element: <TeardownAppendPage \/>/)
  assert.match(append, /back=\{\{ to: `\/desk\/\$\{bookId\}`, label: '回书页' \}\}/)
  assert.doesNotMatch(append, /teardown-title|teardown-author|saveFields|patch\(/)
  assert.match(append, /!loading && !preview && book && last/)
  assert.match(append, /pending\.error\.status === 404.*没有待确认的补章节/)
  assert.match(append, /preview\.junction\.kind === '倒回去了' && <p className="[^"]*text-seal/)
  assert.match(append, /notes\.length > 0 && <section aria-label="接的地方"/)
  assert.match(append, /preview\.previous\.original_volumes && preview\.volumes\.length > 0/)
  assert.match(append, /expandedVolumes \? preview\.volumes : preview\.volumes\.slice\(0, 8\)/)
  assert.match(append, /preview\.volumes\.length > 8/)
  assert.match(append, /preview\.excluded\.length > 0/)
  assert.match(append, /preview\.number_issues\.length > 0/)
  assert.match(append, /preview\.number_issue_total > preview\.number_issues\.length/)
  assert.match(append, /teardownCleaningText\(preview\)/)
  assert.match(append, /preview\.opening\.split\('\\n'\)/)
  assert.match(append, /ENCODINGS\.map/)
  assert.match(append, /setInclude\(\[\]\)/)
  assert.match(append, /<TeardownOptions total=\{total\}/)
  assert.match(append, /preview\.previous\.chapters \+ added/)
  assert.match(append, /<TeardownFilePicker busy=\{busy !== null\}/)
  assert.equal((page.match(/<TeardownFilePicker /g) ?? []).length, 2)
  assert.match(append, /if \(!confirmDelete\) \{ setConfirmDelete\(true\); return \}/)
  assert.match(append, /cancelTeardownAppend\(bookId\)/)
  assert.doesNotMatch(append, /del\(`\/books/)
  for (const text of ['不补了', '确定不补了？再点一次', '先只补上，不拆', '补上并接着拆']) assert.ok(append.includes(text))
  assert.match(append, /disabled=\{busy !== null \|\| upto === undefined \|\| !model.ready\}/)
  assert.match(append, /importTeardownAppend\(bookId, include, start \? \{ upto \} : undefined\)/)
  assert.match(api, /include, start: start \?\? null/)
  assert.match(api, /uploadTeardownFile<TeardownAppendPreview>\(`\/api\/teardown\/\$\{bookId\}\/append`/)
  for (const suffix of ['/append`', '/append/encoding`', '/append/import`']) assert.ok(api.includes(suffix))
  const intro = source('../src/pages/workspace/desk-v2/SettingsPages.tsx')
  assert.match(intro, /<a className="btn seal-line" data-testid="teardown-append-entry" href=\{`\/teardown\/\$\{book\.id\}\/append`\}/)
  assert.ok(intro.indexOf('teardownAddedText(data)') < intro.indexOf('data?.number_issue_total'))
})
