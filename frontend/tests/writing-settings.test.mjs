import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { EFFORT_PRESETS, effortHint, parseChapterWords, unusedCustomNote } from '../src/lib/writingSettings.ts'

const source = (path) => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')
/** 去掉注释：注释里会提到挪走的旧叫法 */
const code = (path) => source(path).replace(/\/\*[\s\S]*?\*\//gu, '').replace(/\/\/.*$/gmu, '')

test('编辑部写得多仔细：三档各用白话说会怎样，以前自己调过的照实说', () => {
  assert.match(effortHint({ effort_preset: 'quick', ...EFFORT_PRESETS.quick }), /最多重写 1 次；卷纲只出一版/u)
  assert.match(effortHint({ effort_preset: 'balanced', ...EFFORT_PRESETS.balanced }), /最多重写 2 次；卷纲出两版挑好的，再专门查一遍/u)
  assert.match(effortHint({ effort_preset: 'premium', ...EFFORT_PRESETS.premium }), /中等毛病也退回，最多重写 3 次/u)
  assert.equal(
    effortHint({ effort_preset: 'custom', max_rewrites: 0, pitches: 1, volume_audit: false, review_strictness: 'strict' }),
    '现在是以前自己调的：审稿更严，不过关不重写，直接停下来请你定；卷纲只出一版。点上面三档就换掉。',
  )
})

test('亲密戏、书名选的不是「自己写」却存着自己写的话：说一声那句没生效', () => {
  assert.equal(unusedCustomNote('fade', '详细描写床戏'), '你写过「详细描写床戏」，选「自己写」才按这句来。')
  assert.equal(unusedCustomNote('custom', '详细描写床戏'), null)
  assert.equal(unusedCustomNote('fade', '  '), null)
  assert.match(unusedCustomNote('short', '一'.repeat(40)), /^你写过「一{30}……」/u)
})

test('每章字数只收 500～20000 的整数，空着和写错的都不算', () => {
  for (const words of [500, 2500, 20000]) assert.equal(parseChapterWords(String(words)), words)
  assert.equal(parseChapterWords(' 3000 '), 3000)
  for (const invalid of ['', ' ', '0', '499', '20001', '2500.5', '-2500', '两千五']) assert.equal(parseChapterWords(invalid), null)
})

test('本书设置（2026-10-19 精简）：书页上居中的弹窗、背景糊掉，只剩写正文、写作要求、编辑部写得多仔细', () => {
  const dialog = code('pages/workspace/BookSettings.tsx')
  assert.match(dialog, /backdrop-blur/u)
  assert.match(dialog, /role="dialog" aria-modal="true"/u)
  assert.match(dialog, /zoom: 'calc\(var\(--desk-zoom\) \* var\(--desk-scale\)\)'/u)
  for (const title of ['写正文', '写作要求', '编辑部写得多仔细']) assert.match(dialog, new RegExp(`<Section title="${title}"`, 'u'))
  for (const label of ['人称', '亲密戏写到哪一步', '每章字数', '文风参考', '加一条', '整理一下']) assert.ok(dialog.includes(label), label)
  // 挪走的：篇幅在简介页，停在哪由你定在开写页；书名风格只在新书默认；题材打法、自定义力度、发给编辑部的原话都不要了
  for (const gone of ['全书计划写多长', '每卷卷纲', '新书前 3 章', '书名风格', '题材打法', '自定义', '实际发给编辑部的话', '其他规矩']) assert.ok(!dialog.includes(gone), gone)
  assert.match(source('pages/workspace/BookDesk.tsx'), /<BookSettingsDialog open=\{settings\} onClose=\{closeSettings\} \/>/u)
})

test('新书默认只留起书名、写正文、仔细程度；四个开关只在开写页', () => {
  const defaults = code('components/settings/WritingSettings.tsx')
  for (const label of ['书名风格', '人称', '亲密戏写到哪一步', '每章字数', '编辑部写得多仔细']) assert.ok(defaults.includes(label), label)
  for (const gone of ['每卷卷纲都要我拍板', '每个单元的章纲都给我看', '每一篇开写前先给我确认', '新书前 3 章先给我试读', '题材打法', '其他规矩', 'RulesPreview', '自定义']) assert.ok(!defaults.includes(gone), gone)
  assert.ok(!source('pages/SettingsPage.tsx').includes('开书方式'))
  const writing = source('pages/workspace/writing.ts')
  assert.ok(writing.indexOf("key: 'segment'") < writing.indexOf("key: 'volume'"))
  assert.ok(writing.indexOf("key: 'volume'") < writing.indexOf("key: 'chapters'"))
  assert.ok(writing.indexOf("key: 'chapters'") < writing.indexOf("key: 'trial'"))
})
