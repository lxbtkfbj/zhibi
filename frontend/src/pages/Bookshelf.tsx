import { Feather, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useBooks, useCreateBook, useDeleteBook, useProfiles } from '../api/hooks'
import type { BookSummary } from '../api/types'
import { Badge, Button, Card, EmptyState, ErrorText, inputClass, Label, Modal, Spinner } from '../components/ui'
import { BOOK_STATUS } from '../lib/roles'

const IDEA_EXAMPLES = [
  '一个能看见别人剩余寿命的杂役弟子，在吃人的宗门里步步为营',
  '末世第三年，我在丧尸围城的城中村开了家奶茶店',
  '穿越成反派大小姐身边的狗，我决定改写她的结局',
]

function NewBookDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [idea, setIdea] = useState('')
  const [style, setStyle] = useState('')
  const [showStyle, setShowStyle] = useState(false)
  const create = useCreateBook()
  const navigate = useNavigate()
  const { data: profiles } = useProfiles()
  const demoOnly = profiles !== undefined && profiles.every((p) => p.provider === 'demo')

  const submit = async () => {
    const result = await create.mutateAsync({ idea: idea.trim(), style_reference: style.trim() })
    onClose()
    setIdea('')
    setStyle('')
    navigate(`/books/${result.book.id}`)
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="开一本新书"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button variant="seal" onClick={submit} loading={create.isPending} disabled={idea.trim().length < 4}>
            <Feather className="size-4" />
            交给编辑部
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <label className="block">
          <Label hint="一句话也行，越具体越好">你想写一本什么样的书？</Label>
          <textarea
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
            rows={4}
            placeholder="例如：一个能看见别人剩余寿命的杂役弟子……"
            className={inputClass}
            onKeyDown={(e) => e.key === 'Enter' && (e.ctrlKey || e.metaKey) && idea.trim().length >= 4 && void submit()}
          />
        </label>
        <div className="flex flex-wrap gap-2">
          {IDEA_EXAMPLES.map((example) => (
            <button
              key={example}
              onClick={() => setIdea(example)}
              className="rounded-full border border-line-2 bg-card px-3 py-1 text-xs text-ink-2 hover:border-seal/40 hover:text-seal"
            >
              {example.slice(0, 16)}…
            </button>
          ))}
        </div>
        {showStyle ? (
          <label className="block">
            <Label hint="贴一段你喜欢的文字，编辑部会参考它的文风">文风参考（可选）</Label>
            <textarea value={style} onChange={(e) => setStyle(e.target.value)} rows={5} className={inputClass} />
          </label>
        ) : (
          <button onClick={() => setShowStyle(true)} className="text-sm text-ink-3 underline-offset-4 hover:text-ink hover:underline">
            + 添加文风参考（可选）
          </button>
        )}
        {demoOnly && (
          <p className="rounded-lg bg-writer-soft px-3 py-2 text-xs text-writer">
            还没有配置模型，编辑部会用「演示模式」生成一本示例书。想用真实模型，先去「模型设置」添加。
          </p>
        )}
        <p className="text-xs text-ink-3">
          接下来：主编定概念 → 设定师建世界观与人物 → 主编写大纲 → 审稿挑刺，全程在会议室直播，最后请你拍板。
        </p>
        <ErrorText error={create.error} />
      </div>
    </Modal>
  )
}

function BookCard({ book }: { book: BookSummary }) {
  const status = BOOK_STATUS[book.status] ?? { label: book.status, tone: 'idle' as const }
  const remove = useDeleteBook()
  return (
    <Card className="group relative flex flex-col transition-shadow hover:shadow-md">
      <Link to={`/books/${book.id}`} className="flex flex-1 flex-col gap-3 p-5">
        <div className="flex items-start justify-between gap-3">
          <h3 className="font-serif text-xl leading-snug font-bold">{book.title}</h3>
          <Badge tone={status.tone}>
            {status.tone === 'busy' && <Spinner className="size-3" />}
            {status.label}
          </Badge>
        </div>
        {book.genre && <p className="text-xs text-ink-3">{book.genre}</p>}
        <p className="line-clamp-3 text-sm leading-relaxed text-ink-2">{book.logline || book.idea}</p>
        <p className="mt-auto pt-2 text-xs text-ink-3">{new Date(book.updated_at).toLocaleString('zh-CN')}</p>
      </Link>
      <button
        onClick={() => {
          if (confirm(`确定删除《${book.title}》？设定库、大纲和会议记录都会一起删除。`)) remove.mutate(book.id)
        }}
        className="absolute right-3 bottom-3 rounded-md p-1.5 text-ink-3 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-seal-soft hover:text-seal"
        aria-label="删除"
      >
        <Trash2 className="size-4" />
      </button>
    </Card>
  )
}

export function Bookshelf() {
  const { data: books, isLoading, error } = useBooks()
  const [open, setOpen] = useState(false)

  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        <div className="mb-6 flex items-end justify-between gap-4">
          <div>
            <h1 className="font-serif text-2xl font-bold">书架</h1>
            <p className="mt-1 text-sm text-ink-3">给编辑部一个点子，剩下的交给他们。</p>
          </div>
          <Button variant="seal" onClick={() => setOpen(true)}>
            <Plus className="size-4" />
            开新书
          </Button>
        </div>

        {isLoading && (
          <div className="flex justify-center py-20 text-ink-3">
            <Spinner />
          </div>
        )}
        <ErrorText error={error} />
        {books && books.length === 0 && (
          <Card>
            <EmptyState icon={<Feather className="size-10" />} title="书架还是空的">
              <p>点「开新书」，写下你想写的故事，编辑部会帮你把它变成一本书的完整方案。</p>
              <Button variant="seal" className="mt-4" onClick={() => setOpen(true)}>
                <Plus className="size-4" />
                开新书
              </Button>
            </EmptyState>
          </Card>
        )}
        {books && books.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {books.map((book) => (
              <BookCard key={book.id} book={book} />
            ))}
          </div>
        )}
      </div>
      <NewBookDialog open={open} onClose={() => setOpen(false)} />
    </div>
  )
}
