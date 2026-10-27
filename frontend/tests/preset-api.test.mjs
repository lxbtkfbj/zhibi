import assert from 'node:assert/strict'
import test from 'node:test'
import { presetApi, PresetApiError } from '../src/api/presets.ts'

test('预设API精确接线，保存使用所有显式块字段，块ID以后台返回为准', async () => {
  const original = globalThis.fetch
  const calls = []
  const blocks = [{ id: 'temporary', title: '新的块', role: 'system', enabled: true, required: false, when: 'always', content: '' }]
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options })
    return new Response(JSON.stringify({ id: 'mine-1', blocks: [{ ...blocks[0], id: 'custom_issued' }] }), { status: 200 })
  }
  try {
    await presetApi.list()
    await presetApi.system(2)
    await presetApi.create({ source: 'system', version: 2 })
    const saved = await presetApi.save('mine-1', { name: '我的预设', blocks })
    assert.equal(saved.blocks[0].id, 'custom_issued')
    assert.deepEqual(calls.map(row => row.url), ['/api/presets?kind=chief_group', '/api/presets/system/chief_group?version=2', '/api/presets/mine', '/api/presets/mine/mine-1'])
    assert.deepEqual(JSON.parse(calls[2].options.body), { kind: 'chief_group', source: 'system', version: 2 })
    assert.deepEqual(JSON.parse(calls[3].options.body), { name: '我的预设', blocks })
    assert.equal(calls[3].options.method, 'PUT')
  } finally { globalThis.fetch = original }
})

test('活动预设422保留后台检查条目，拆书占位符422保持状态供页面隐藏预览', async () => {
  const original = globalThis.fetch
  const issue = { severity: 'error', code: 'missing_note', block_id: null, title: null, message: '没有一块放了 {{作者这次说的}}，主编看不到你这次说的话。' }
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: { message: '这份预设还不能用', issues: [issue] } }), { status: 422 })
    await assert.rejects(() => presetApi.activate({ source: 'mine', id: 'mine-1' }), error => {
      assert.ok(error instanceof PresetApiError)
      assert.equal(error.status, 422)
      assert.equal(error.message, '这份预设还不能用')
      assert.deepEqual(error.issues, [issue])
      return true
    })
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: '拆书照旧用原来的提示词' }), { status: 422 })
    await assert.rejects(() => presetApi.placeholders('teardown-book'), error => error.status === 422 && error.issues.length === 0)
  } finally { globalThis.fetch = original }
})

test('保存历史逐版取blocks、恢复接口以及JSON附件导入导出', async () => {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, options) => { calls.push({ url, options }); return new Response('{}') }
  try {
    await presetApi.saves('mine-1')
    await presetApi.snapshot('mine-1', 3)
    await presetApi.restore('mine-1', 3)
    await presetApi.importFile(new File(['{}'], '导入.json', { type: 'application/json' }))
    assert.deepEqual(calls.map(row => row.url), ['/api/presets/mine/mine-1/saves', '/api/presets/mine/mine-1/saves/3', '/api/presets/mine/mine-1/saves/3/restore', '/api/presets/import'])
    assert.equal(calls[2].options.method, 'POST')
    assert.equal(calls[3].options.body.get('file').name, '导入.json')
    assert.equal(calls[3].options.headers, undefined, 'multipart边界由浏览器生成')
    assert.equal(presetApi.exportHref({ source: 'system', version: 2 }), '/api/presets/system/chief_group/export?version=2')
    assert.equal(presetApi.exportHref({ source: 'mine', id: 'mine-1' }), '/api/presets/mine/mine-1/export')
  } finally { globalThis.fetch = original }
})
