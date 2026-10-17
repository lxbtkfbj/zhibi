import assert from 'node:assert/strict'
import test from 'node:test'
import { filterLibraryRows, libraryRows, parentChoices, suggestionAction, suggestionTargetId, worldTree } from '../src/lib/libraryView.ts'
const item = (id, extra = {}) => ({ id, name: id, one_line: '', content: '', category: '世界与地图', status: 'must', position: 0, tags: [], aliases: [], locked: false, source: 'ai', ...extra })
const snapshot = { categories: [], characters: [item('主角', {category: undefined, role_type: '主角'})], entries: [item('晚点', {status:'later'}), item('子地方', {parent_id:'世界', position: 3}), item('世界', {position: 1}), item('一言', {status:'one'}), item('金手指', {category:'特殊规则', tags:['金手指'], one_line:'全角：这是金手指。'})], focus: {characters:['主角'], entries:['金手指']}, suggestions_pending: 1 }
const suggestions = [{id:'s',title:'修改',target_id:'子地方',payload:{},origin:{},status:'pending'}]
const order = ['must','one','later']
test('设定库按状态再按位置排序，重点使用后端返回的角色与条目引用', () => {
  assert.deepEqual(filterLibraryRows(snapshot, suggestions, {focus:true}, order).map(row => row.id), ['金手指','主角'])
  assert.deepEqual(filterLibraryRows(snapshot, suggestions, {category:'世界与地图'}, order).map(row => [row.id,row.depth]), [['世界',0],['子地方',1],['一言',0],['晚点',0]])
})
test('现在要定、有建议和全文搜索可组合，不改动原数组', () => {
  assert.deepEqual(filterLibraryRows(snapshot, suggestions, {mustOnly:true,suggestionsOnly:true,search:'子'}, order).map(row=>row.id), ['子地方'])
  assert.deepEqual(filterLibraryRows(snapshot, suggestions, {search:'全角：'}, order).map(row=>row.id), ['金手指'])
  assert.equal(snapshot.entries[0].id, '晚点')
  assert.equal(filterLibraryRows(snapshot, suggestions, {category:'特殊规则',search:'不存在'}, order).length,0)
})
test('世界树保留孤儿及历史环，过滤掉父级后子项仍显示', () => {
  assert.deepEqual(worldTree(libraryRows({...snapshot,characters:[],entries:[item('A',{parent_id:'B'}),item('B',{parent_id:'A'}),item('C',{parent_id:'missing'})]})).map(row=>row.id), ['C','A','B'])
  assert.deepEqual(filterLibraryRows(snapshot, suggestions, {category:'世界与地图',suggestionsOnly:true}, order).map(row=>[row.id,row.depth]),[['子地方',0]])
})
test('所属地方排除自己、后代及其他类别', () => {
  const root = item('世界')
  assert.deepEqual(parentChoices([root,item('子',{parent_id:'世界'}),item('孙',{parent_id:'子'}),item('外'),item('物',{category:'物品与功法'})],root).map(row=>row.id),['外'])
})
test('正文引用提醒关联原条目，建议动作名准确', () => {
  assert.equal(suggestionTargetId({target_id:null,payload:{},origin:{target_id:'source'}}),'source')
  assert.equal(suggestionAction({payload:{op:'create_entry'}}),'建')
  assert.equal(suggestionAction({payload:{op:'replace_in_chapters'}}),'前文也一起换')
})
