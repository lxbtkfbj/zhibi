import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { createTeardownFieldSaver, teardownCleaningText, teardownNumberIssueText, teardownPreviewTotals, teardownSplitText, teardownWords } from '../src/lib/teardownPreview.ts'

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
  for (const text of ['只能导入 TXT 文件', '文件超过 50MB', '正在分章……', '确定不导入？再点一次', '还没确认分章']) {
    assert.ok((page + readFileSync(new URL('../src/pages/Home.tsx', import.meta.url), 'utf8')).includes(text), text)
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
  assert.match(page, /importTeardown\(bookId, fieldsRef\.current, include, start \? \{ upto \} : undefined\)/)
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

test('书房继续写作和自己的书架不混入拆书；拆书卡片用确认状态导航并保留删除', () => {
  const home = readFileSync(new URL('../src/pages/Home.tsx', import.meta.url), 'utf8')
  assert.match(home, /ownBooks = books\?\.filter\(book => book\.source !== 'teardown'\)/)
  assert.match(home, /const latest = ownBooks\?\.\[0\]/)
  assert.match(home, /confirming \? `\/teardown\/\$\{book\.id\}` : `\/desk\/\$\{book\.id\}`/)
  assert.match(home, /已导入 \$\{book\.teardown\?\.chapters \?\? 0\} 章 · 还没开拆/)
  assert.match(home, /teardownBooks\.length > 0/)
  assert.match(home, /state=\{teardown && !confirming \? \{ teardownHome: true \} : undefined\}/)
  assert.match(home, /aria-label="删除"/)
  assert.equal((home.match(/>拆一本书<\/Button>/g) ?? []).length, 2)
})
