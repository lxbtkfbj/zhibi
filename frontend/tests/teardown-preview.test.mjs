import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { createTeardownFieldSaver, teardownCleaningText, teardownIgnoredHeadingSelection, teardownIgnoredHeadingText, teardownNumberIssueText, teardownPreviewTotals, teardownSplitText, teardownVolumeDefaultText, teardownWords } from '../src/lib/teardownPreview.ts'

const preview = {
  chars: 1720000, chapter_count: 499, volumes: [{ index: 1, title: '初入江湖', chapters: 499 }], by_length: false,
  excluded: [{ order: 0, title: '请假', chars: 50 }, { order: 501, title: '感言', chars: 100 }],
}

test('分章确认有卷、没有卷、按字数切的数字和措辞一致', () => {
  assert.equal(teardownSplitText(preview), '共 172 万字 · 分了 1 卷、499 章')
  assert.equal(teardownSplitText({ ...preview, chars: 2230000, chapter_count: 670, volumes: [] }), '共 223 万字 · 670 章，原书没有分卷')
  assert.equal(teardownSplitText({ ...preview, by_length: true, chapter_count: 8 }), '没认出章节标题，按三千字左右切成了 8 段')
  assert.equal(teardownWords(9999), '9,999 字')
  assert.equal(teardownWords(10000), '1 万字')
})

test('不像正文默认排除，勾回时只加这份预览里的章数和字数', () => {
  assert.deepEqual(teardownPreviewTotals(preview, []), { chars: 1720000, chapters: 499 })
  assert.deepEqual(teardownPreviewTotals(preview, [0, 0, 501, 999]), { chars: 1720150, chapters: 501 })
  assert.equal(preview.chars, 1720000)
  assert.equal(teardownSplitText({ ...preview, chars: 400, volumes: [] }, [0]), '共 450 字 · 500 章，原书没有分卷')
})

test('原书章号四种不对的说明逐字使用任务措辞，单章和多章缺漏不同', () => {
  const issue = { index: 10, expected: 9, number: 10 }
  assert.equal(teardownNumberIssueText({ ...issue, kind: '跳了' }), '第 10 章前：原书没有第 9 章')
  assert.equal(teardownNumberIssueText({ ...issue, number: 13, kind: '跳了' }), '第 10 章前：原书没有第 9–12 章')
  assert.equal(teardownNumberIssueText({ ...issue, number: 8, kind: '重了' }), '第 10 章：原书第 8 章出现了两次')
  assert.equal(teardownNumberIssueText({ ...issue, number: 3, kind: '倒回去了' }), '第 10 章：原书章号从第 8 章倒回了第 3 章')
  assert.equal(teardownNumberIssueText({ ...issue, expected: 364, number: 36, kind: '打错了' }), '第 10 章：原书把第 364 章写成了「第36章」')
  assert.equal(teardownNumberIssueText({ ...issue, expected: 596, number: 396, count: 2, end_index: 597, end_number: 397, kind: '打错了' }), '原书把第 596–597 章写成了「第396章」到「第397章」')
  assert.equal(teardownNumberIssueText({ ...issue, expected: 1790, number: 1780, count: 8, end_index: 1797, end_number: 1787, kind: '打错了' }), '原书把第 1790–1797 章写成了「第1780章」到「第1787章」')
})

test('忽略的假标题和超400章原卷说明逐字照任务，400章不提醒', () => {
  assert.equal(teardownIgnoredHeadingText({ index: 810, title: '复仇', line: '第1章' }), '第 810 章「复仇」里的「第1章」')
  assert.equal(teardownVolumeDefaultText({ index: 2, title: '苍风烟云', chapters: 2099 }), '原书的「苍风烟云」一卷有 2099 章，太粗，默认让主编按剧情分。')
  assert.equal(teardownVolumeDefaultText({ index: 1, title: '原卷', chapters: 400 }), null)
  assert.equal(teardownVolumeDefaultText(null), null)
})

test('勾回前置排除章和排除章自身时假标题实时重编号，取消恢复，20条上限重算', () => {
  const raw = { ...preview,
    excluded: [{ order: 0 }, { order: 3 }],
    ignored_headings: [{ index: 1, title: '后面的章', line: '第1章', order: 1 }], ignored_heading_total: 1,
    ignored_heading_candidates: [{ order: 1, title: '后面的章', line: '第1章' }, ...Array.from({ length: 21 }, (_, index) => ({ order: 3, title: '排除章自身', line: `第${index + 10}章` }))],
  }
  const before = structuredClone(raw)
  assert.deepEqual(teardownIgnoredHeadingSelection(raw, []).ignored_headings.map(heading => heading.index), [1])
  assert.deepEqual(teardownIgnoredHeadingSelection(raw, [0, 0, 999]).ignored_headings.map(heading => heading.index), [2])
  const restored = teardownIgnoredHeadingSelection(raw, [0, 3])
  assert.equal(restored.ignored_headings.length, 20)
  assert.equal(restored.ignored_heading_total, 22)
  assert.deepEqual(restored.ignored_headings.map(heading => heading.index), [2, ...Array(19).fill(4)])
  assert.deepEqual(teardownIgnoredHeadingSelection(raw, []).ignored_headings.map(heading => heading.index), [1])
  assert.deepEqual(raw, before)
  assert.deepEqual(teardownIgnoredHeadingSelection({ ...raw, ignored_heading_candidates: undefined }, [0]).ignored_headings.map(heading => heading.index), [2], '兼容只有order的旧预览')
})

test('假标题选择兼容旧缓存和不含排除章列表的部分预览', () => {
  assert.deepEqual(teardownIgnoredHeadingSelection({}, []), { ignored_headings: [], ignored_heading_total: undefined })
  const old = { ignored_headings: [{ index: 5, order: 4, title: '旧章', line: '第1章' }], ignored_heading_total: 1 }
  assert.deepEqual(teardownIgnoredHeadingSelection(old, [0]), old)
  const candidates = { ignored_heading_candidates: [{ order: 4, title: '候选章', line: '第2章' }] }
  assert.deepEqual(teardownIgnoredHeadingSelection(candidates, []).ignored_headings, [{ order: 4, title: '候选章', line: '第2章', index: 5 }])
})

test('无重复章时不显示半句话，第二批移除导入不花钱的旧小字', () => {
  assert.equal(teardownCleaningText({ ads_removed: 3, duplicates_removed: 0 }), '去掉了 3 行广告和网址。')
  assert.equal(teardownCleaningText({ ads_removed: 4, duplicates_removed: 2 }), '去掉了 4 行广告和网址，重复的章 2 个。')
})

test('离焦保存排队、只存变化的字段；换编码等待最新手改，旧请求不能覆盖它', async () => {
  const calls = []
  let release
  const wait = new Promise(resolve => { release = resolve })
  const saver = createTeardownFieldSaver({ title: '猜的', author: '' }, async fields => {
    calls.push(fields)
    if (calls.length === 1) await wait
  })
  const first = saver.save({ title: '手改', author: '' })
  const second = saver.save({ title: '手改', author: '作者' })
  const beforeEncoding = saver.save({ title: '最后的书名', author: '作者' })
  await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(calls, [{ title: '手改' }])
  release()
  await Promise.all([first, second, beforeEncoding])
  assert.deepEqual(calls, [{ title: '手改' }, { author: '作者' }, { title: '最后的书名' }])
  await saver.save({ title: '最后的书名', author: '作者' })
  assert.equal(calls.length, 3)
  saver.accept({ title: '新编码认出来的书名', author: '作者' })
  await saver.save({ title: '新编码认出来的书名', author: '作者' })
  assert.equal(calls.length, 3)
})

test('保存失败阻止下一步并保留待存字段；重新保存能恢复，不把失败当已保存', async () => {
  const calls = []
  const saver = createTeardownFieldSaver({ title: '猜的', author: '' }, async fields => {
    calls.push(fields)
    if (calls.length === 1) throw new Error('不能保存')
  })
  await assert.rejects(saver.save({ title: '保留手改', author: '' }), /不能保存/)
  await saver.save({ title: '保留手改', author: '' })
  await saver.settled()
  assert.deepEqual(calls, [{ title: '保留手改' }, { title: '保留手改' }])
})

test('上传和确认页只接 TXT、提供上传进度、编码失败保留预览并显示原样错误', () => {
  const page = readFileSync(new URL('../src/pages/Teardown.tsx', import.meta.url), 'utf8')
  const api = readFileSync(new URL('../src/api/teardown.ts', import.meta.url), 'utf8')
  const shelf = readFileSync(new URL('../src/lib/teardownShelf.ts', import.meta.url), 'utf8')
  for (const text of ['只能导入 TXT 文件', '文件超过 50MB', '正在分章……', '确定不导入？再点一次', '还没确认分章']) {
    assert.ok((page + shelf).includes(text), text)
  }
  assert.match(page, /accept="\.txt"/)
  assert.match(page, /aria-valuenow=\{progress\}/)
  assert.match(api, /request\.upload\.onprogress/)
  assert.match(api, /typeof detail === 'string' \? detail/)
  const encoding = page.slice(page.indexOf('const switchEncoding'), page.indexOf('const importBook'))
  assert.ok(encoding.indexOf('await saveFields()') < encoding.indexOf('await changeTeardownEncoding'))
  assert.match(encoding, /catch \(reason\) \{ if \(fieldsSaved\) setEncodingError\(reason\) \}/)
  assert.doesNotMatch(encoding, /setPreview\(null\)/)
  assert.match(page, /<ErrorText error=\{encodingError\}/)
  assert.match(page, /reason\.status === 409.*\/desk\//)
  assert.match(page, /replace: true, state: \{ teardownHome: true \}/)
  assert.match(page, /navigate\(`\/desk\/\$\{bookId\}`, \{ state: \{ teardownHome: true \} \}\)/)
  assert.match(page, /importTeardown\(bookId, fieldsRef\.current, include, start \? \{ upto \} : undefined, volumeMode\)/)
  assert.match(page, /if \(operating\.current \|\| !preview\) return/)
})

test('字段保存失败独立显示，最新一次保存成功清掉旧错误，不覆盖编码和导入错误', () => {
  const page = readFileSync(new URL('../src/pages/Teardown.tsx', import.meta.url), 'utf8')
  const save = page.slice(page.indexOf('const saveFields'), page.indexOf('const switchEncoding'))
  assert.match(save, /const attempt = \+\+fieldAttempt\.current/)
  assert.match(save, /if \(fieldAttempt\.current === attempt\) setFieldError\(null\)/)
  assert.match(save, /if \(fieldAttempt\.current === attempt\) setFieldError\(reason\)/)
  assert.doesNotMatch(save, /setError\(|setEncodingError\(/)
  assert.match(page, /<ErrorText error=\{fieldError\}/)
  assert.doesNotMatch(page, /saveFields\(\)\.catch\(setError\)/)
})

test('繁简重预览沿用编码的保存队列，分卷只切本地选择，补章节不显示繁简和分卷选择', () => {
  const page = readFileSync(new URL('../src/pages/Teardown.tsx', import.meta.url), 'utf8')
  const api = readFileSync(new URL('../src/api/teardown.ts', import.meta.url), 'utf8')
  const confirm = page.slice(page.indexOf('function TeardownConfirmBook'), page.indexOf('export function TeardownAppendPage'))
  const append = page.slice(page.indexOf('function TeardownAppendBook'))
  for (const text of ['原文是繁体，导入时转成简体', '转成简体，拆出来的人名、设定都用简体，不容易把同一个人认成两个', '照原书分卷', '让主编按剧情分卷', '主编一边拆一边分，大约每一百章一卷，收在大高潮上。下面原书的卷名不用。']) assert.ok(confirm.includes(text))
  assert.match(confirm, /preview\.traditional &&/)
  assert.match(confirm, /checked=\{preview\.t2s\}/)
  assert.match(confirm, /changeTeardownEncoding\(bookId, encoding, t2s\)/)
  assert.match(confirm, /t2s = preview\?\.traditional \? preview\.t2s : undefined/)
  assert.match(confirm, /setVolumeMode\(data\.volume_mode \?\? 'original'\)/)
  assert.match(confirm, /aria-pressed=\{volumeMode === mode\}/)
  assert.match(confirm, /onClick=\{\(\) => \{ setVolumeMode\(mode\); setConfirmDelete\(false\) \}\}/)
  assert.match(api, /volume_mode: volumeMode/)
  assert.match(api, /t2s === undefined \? \{\} : \{ t2s \}/)
  assert.doesNotMatch(append, /preview\.traditional|setVolumeMode|原文是繁体/)
  assert.match(confirm, /<IgnoredHeadings preview=\{preview\} include=\{include\} \/>/)
  assert.match(append, /<IgnoredHeadings preview=\{preview\} \/>/)
})

test('拆书简介用原生h1的DeskEdit并沿用现有保存动作，空白不存且不增样式', () => {
  const source = readFileSync(new URL('../src/pages/workspace/desk-v2/EssencePages.tsx', import.meta.url), 'utf8')
  const intro = source.slice(source.indexOf('export function TeardownIntro'))
  assert.match(intro, /<DeskEdit as="h1" value=\{book\.title\} placeholder="书名" onSave=\{title => \{ if \(title\.trim\(\)\) save\(actions\.saveBook\(\{ title: title\.trim\(\) \}\)\) \}\} \/>/)
  assert.doesNotMatch(intro, /<h1>\{book\.title\}<\/h1>/)
})

test('书房继续写作和自己的书架不混入拆书；拆书卡片用确认状态导航并保留删除', () => {
  const home = readFileSync(new URL('../src/pages/Home.tsx', import.meta.url), 'utf8')
  assert.match(home, /ownBooks = books\?\.filter\(book => book\.source !== 'teardown'\)/)
  assert.match(home, /const latest = ownBooks\?\.\[0\]/)
  assert.match(home, /confirming \? `\/teardown\/\$\{book\.id\}` : `\/desk\/\$\{book\.id\}`/)
  assert.match(home, /teardownShelfStatus\(book\.teardown, fallbackRead\)/)
  assert.match(home, /teardownBooks\.length > 0/)
  assert.match(home, /state=\{teardown && !confirming \? \{ teardownIntro: true \} : undefined\}/)
  assert.match(home, /aria-label="删除"/)
  assert.equal((home.match(/>拆一本书<\/Button>/g) ?? []).length, 1)
})

test('书架标题不重复显示拆书和开书按钮，保留顶部入口与开新书卡片', () => {
  const home = readFileSync(new URL('../src/pages/Home.tsx', import.meta.url), 'utf8')
  const shelfHeader = home.slice(home.indexOf('{books && ('), home.indexOf('<FretDivider'))
  assert.doesNotMatch(shelfHeader, /<Button/)
  assert.match(home, /<Button variant="seal" size="lg" onClick=\{submit\}>/)
  assert.match(home, /<Link to="\/new" className="group flex flex-col items-center">/)
})
