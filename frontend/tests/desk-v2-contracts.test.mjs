import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import postcss from 'postcss'

const read = file => fs.readFileSync(new URL(file, import.meta.url), 'utf8')
test('样张整段CSS只机械添加作用域，变量、声明顺序、数值与媒体规则全部相同', () => {
  const html = read('../../docs/界面原型/精髓样张.html')
  const source = html.match(/<style>([\s\S]*?)<\/style>/)[1]
  const decoration = read('../../docs/界面原型/装修样张.html').match(/<style>([\s\S]*?)<\/style>/)[1]
  assert.ok(source.startsWith(decoration), '精髓样张以装修样张第一段 CSS 原样开头')
  const original = postcss.parse(source)
  original.walkRules(rule => { rule.selector = rule.selectors.map(s => [':root', 'body', 'html'].includes(s) ? '.desk-v2' : '.desk-v2 ' + s).join(', ') })
  assert.equal(read('../src/styles/desk-v2.css').trim(), original.toString().trim())
})
test('只恢复两个新编号伪元素的UA盒模型，不改样张字号、尺寸或机械CSS', () => {
  const selectors = ['.desk-v2 .kp .steps li::before', '.desk-v2 .intro2 .learn li::before']
  const host = postcss.parse(read('../src/styles/desk-v2-host.css'))
  const resets = []
  host.walkRules(rule => {
    if (rule.selectors.some(selector => selectors.includes(selector))) {
      resets.push(...rule.selectors)
      assert.deepEqual(rule.nodes.map(node => [node.prop, node.value]), [['box-sizing', 'content-box']])
    }
  })
  assert.deepEqual(resets, selectors)
  const sample = postcss.parse(read('../../docs/界面原型/精髓样张.html').match(/<style>([\s\S]*?)<\/style>/)[1])
  const global = sample.nodes.find(node => node.type === 'rule' && node.selector === '*')
  assert.ok(global.nodes.some(node => node.prop === 'box-sizing' && node.value === 'border-box'))
  sample.walkRules(rule => {
    if (rule.selector.includes('::before')) assert.ok(!rule.nodes.some(node => node.prop === 'box-sizing'))
  })
})
test('缩放使用宽高共同限制的1700/800算法，页面与弹窗复用同一倍数', () => {
  const appearance = read('../src/lib/appearance.tsx')
  assert.match(appearance, /Math\.min\(1\.5, Math\.max\(1, window\.innerWidth \/ 1700\), Math\.max\(1, window\.innerHeight \/ 800\)\)/)
  assert.match(appearance, /window\.addEventListener\('resize', apply\)/)
  assert.doesNotMatch(read('../src/index.css'), /@media \(min-width: (?:1800|2200|2500|3200)px\)/)
  for (const file of ['../src/pages/workspace/saves.css', '../src/pages/workspace/BookSettings.tsx', '../src/components/TeardownStart.tsx']) assert.match(read(file), /var\(--desk-zoom\).*var\(--desk-scale\)/)
  for (const file of ['../src/index.css', '../src/main.tsx']) for (const weight of [400, 600, 700]) {
    if (weight === 400 && file.endsWith('index.css')) continue // main imports the shared 400 face.
    assert.match(read(file), new RegExp(`noto-serif-sc/${weight}\\.css`))
  }
})
test('新目录的搜索、置顶、折叠和全书导出保留真实入口，不把搜索伪装成未命中', () => {
  const chrome = read('../src/pages/workspace/desk-v2/Chrome.tsx')
  assert.match(chrome, /searchBookText\(book\.id, q, signal\)/)
  assert.match(chrome, /searchResult\.isPending/)
  assert.match(chrome, /searchResult\.error/)
  assert.match(chrome, /onSearchSelect\(`c\$\{hit\.index\}`, q\)/)
  assert.match(chrome, /orderedCharacters\(category\.entries, teardown\)/)
  assert.match(chrome, /e\.stopPropagation\(\); onToggle\(unit\.id\)/)
  assert.match(chrome, /export\.txt/)
})
test('等级手改/新建显式序列化结构化到达章，不因驼峰展示字段丢失元数据', () => {
  const live = read('../src/pages/workspace/liveActions.ts')
  assert.equal((live.match(/protagonist_chapter: protagonistChapter/g) ?? []).length, 2)
  assert.match(read('../src/pages/workspace/actions.ts'), /levels\?: VEntry\['levels'\]/)
})
test('仅模板恢复浏览器默认值，旧编辑部排除重置且SVG属性不被all:revert清掉', () => {
  const host = read('../src/styles/desk-v2-host.css')
  assert.match(host, /:not\(\.desk-legacy, \.desk-legacy \*\)/)
  assert.doesNotMatch(host, /:where\([^)]*(?:button|input|svg)[^)]*\) \{ all: revert/)
  const workspace = read('../src/pages/workspace/Workspace.tsx')
  assert.match(workspace, /data-testid="editorial-docked" className="desk-legacy/)
  assert.match(workspace, /data-testid="editorial-floating"[\s\S]*?className="desk-legacy/)
})
