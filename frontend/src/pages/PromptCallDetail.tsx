import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, LoaderCircle, X, XCircle } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { promptApi } from '../api/prompts'
import { ErrorText } from '../components/ui'
import { ROLE_META } from '../lib/roles'

/** 调用原文只读查看；与提示词工作台共用宣纸、字号及界面缩放。 */
export function PromptCallDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const query = useQuery({ queryKey: ['llm-call', id], queryFn: () => promptApi.call(id) })
  const call = query.data
  const dialog = useRef<HTMLDialogElement>(null)
  const backdrop = useRef(false)
  useEffect(() => {
    const panel = dialog.current!
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    panel.showModal()
    return () => { panel.close(); document.body.style.overflow = overflow; if (previous?.isConnected) previous.focus() }
  }, [])
  return createPortal(<dialog ref={dialog} className="prompt-call-dialog" aria-labelledby="call-detail-title" aria-modal="true"
    onCancel={event => { event.preventDefault(); onClose() }}
    onPointerDown={event => { backdrop.current = event.target === event.currentTarget }}
    onClick={event => { if (backdrop.current && event.target === event.currentTarget) onClose(); backdrop.current = false }}
    onKeyDown={event => {
      if (event.key === 'Escape') event.stopPropagation()
      if (event.key !== 'Tab') return
      const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), summary, a[href], [tabindex="0"]')).filter(item => item.getClientRects().length)
      const first = items[0], last = items.at(-1)
      if (event.shiftKey && (document.activeElement === first || document.activeElement === event.currentTarget)) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }}>
    <div className="call-dialog-content">
      <header className="call-dialog-heading"><div><h2 id="call-detail-title">调用详情</h2><p>查看编辑部实际发送的内容与模型原样回复，不会重新调用模型。</p></div><button type="button" className="prompt-icon-button" aria-label="关闭调用详情" title="关闭（Esc）" onClick={onClose}><X className="size-5" /></button></header>
      <div className="call-dialog-scroll scroll-thin">
        {query.isPending && <p className="prompt-state" role="status"><LoaderCircle className="size-5 animate-spin" />正在读取调用记录…</p>}
        {query.isError && <div className="prompt-state"><p>这条调用记录暂时没读出来</p><ErrorText error={query.error} /><button type="button" className="prompt-secondary-button" onClick={() => void query.refetch()}>重新读取</button></div>}
        {call && <div className="call-detail">
          <section className="call-summary">
            <div className="call-summary-title"><h3>{call.purpose}</h3><span className={`call-status ${call.ok ? 'is-ok' : 'is-failed'}`}>{call.ok ? <CheckCircle2 className="size-3.5" /> : <XCircle className="size-3.5" />}{call.ok ? '成功' : '失败'}</span></div>
            <p>{call.book_title || '未关联书籍'} · {new Date(call.created_at).toLocaleString('zh-CN', { hour12: false })}</p>
            <dl className="call-facts"><div><dt>角色</dt><dd>{ROLE_META[call.role as keyof typeof ROLE_META]?.name ?? call.role}</dd></div><div><dt>模型</dt><dd>{call.model}<small>{call.profile_name || '未记录配置名称'}</small></dd></div><div><dt>输入 / 输出 Token</dt><dd>{call.prompt_tokens?.toLocaleString('zh-CN') ?? '—'} / {call.completion_tokens?.toLocaleString('zh-CN') ?? '—'}</dd></div><div><dt>耗时</dt><dd>{call.latency_ms == null ? '—' : `${(call.latency_ms / 1000).toFixed(2)} 秒`}</dd></div></dl>
          </section>
          {!call.request && <p className="call-retention-note">这次调用的完整请求未留存。每本书只保留最近 2000 次调用的完整内容，较早记录的统计信息仍然保留。</p>}
          <section><h3>系统提示</h3><pre tabIndex={0}>{call.request?.system ?? '未留存'}</pre></section>
          <section><h3>用户提示</h3><pre tabIndex={0}>{call.request?.user ?? '未留存'}</pre></section>
          <details><summary>结构说明与调用方式</summary><p className="call-schema-meta">{call.request?.method ?? '历史记录'} · {call.request?.schema_name ?? '无结构化输出要求'}</p><pre tabIndex={0}>{call.request?.schema ? JSON.stringify(call.request.schema, null, 2) : '无结构说明'}</pre></details>
          <section><h3>模型的原样回复</h3><pre tabIndex={0}>{call.response ?? '未留存'}</pre></section>
          {call.error && <section><h3 className="text-seal">错误信息</h3><pre tabIndex={0} className="call-error-text">{call.error}</pre></section>}
        </div>}
      </div>
    </div>
  </dialog>, document.body)
}
