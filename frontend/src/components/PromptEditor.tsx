import { Compartment, EditorState, StateField } from '@codemirror/state'
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'
import { Decoration, EditorView, WidgetType, drawSelection, keymap, type DecorationSet } from '@codemirror/view'
import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import type { PromptVariable } from '../api/prompts'

class VariableWidget extends WidgetType {
  readonly name: string
  readonly label: string
  constructor(name: string, label: string) { super(); this.name = name; this.label = label }
  eq(other: VariableWidget) { return this.name === other.name && this.label === other.label }
  toDOM() {
    const span = document.createElement('span')
    span.className = 'prompt-variable'
    span.textContent = this.label
    span.title = `{{${this.name}}}`
    span.setAttribute('aria-label', `变量：${this.label}`)
    span.setAttribute('contenteditable', 'false')
    return span
  }
}

export interface PromptEditorHandle { insert: (variable: string) => void }
export const PromptEditor = forwardRef<PromptEditorHandle, {
  value: string; editable: boolean; variables: PromptVariable[]; onChange: (content: string) => void
}>(function PromptEditor({ value, editable, variables, onChange }, ref) {
  const host = useRef<HTMLDivElement>(null)
  const editor = useRef<EditorView | null>(null)
  const editing = useRef(new Compartment())
  const callback = useRef(onChange)
  useEffect(() => { callback.current = onChange }, [onChange])
  useImperativeHandle(ref, () => ({ insert: variable => {
    const view = editor.current
    if (!view || !view.state.facet(EditorView.editable)) return
    view.dispatch(view.state.replaceSelection(`{{${variable}}}`))
    view.focus()
  } }), [])
  // A template's variable labels are immutable. Rebuild only when that template changes.
  const labelsKey = JSON.stringify(variables)
  useEffect(() => {
    if (!host.current) return
    const labels = new Map<string, string>((JSON.parse(labelsKey) as PromptVariable[]).map(v => [v.name, v.label]))
    const decorate = (state: EditorState): DecorationSet => Decoration.set(
      [...state.doc.toString().matchAll(/\{\{\s*([a-zA-Z_][\w]*)\s*\}\}/g)].map(match => Decoration.replace({
        widget: new VariableWidget(match[1], labels.get(match[1]) ?? `未知变量：${match[1]}`),
      }).range(match.index!, match.index! + match[0].length)),
    )
    const tokens = StateField.define<DecorationSet>({
      create: decorate,
      update: (decorations, transaction) => transaction.docChanged ? decorate(transaction.state) : decorations,
      provide: field => [EditorView.decorations.from(field), EditorView.atomicRanges.of(view => view.state.field(field))],
    })
    const view = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          tokens, history(), drawSelection(), EditorView.lineWrapping,
          keymap.of([...defaultKeymap, ...historyKeymap]),
          editing.current.of([EditorState.readOnly.of(!editable), EditorView.editable.of(editable)]),
          EditorView.contentAttributes.of({ 'aria-label': '提示词编辑区', spellcheck: 'false' }),
          EditorView.updateListener.of(update => { if (update.docChanged) callback.current(update.state.doc.toString()) }),
        ],
      }),
    })
    editor.current = view
    return () => { view.destroy(); editor.current = null }
    // Value/editability updates are handled below without destroying selection or undo history.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [labelsKey])
  useEffect(() => {
    const view = editor.current
    if (view && view.state.doc.toString() !== value) view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value } })
  }, [value])
  useEffect(() => {
    editor.current?.dispatch({ effects: editing.current.reconfigure([EditorState.readOnly.of(!editable), EditorView.editable.of(editable)]) })
  }, [editable])
  return <div ref={host} className={`prompt-editor ${editable ? 'is-editable' : 'is-readonly'}`} data-testid="prompt-editor" />
})
