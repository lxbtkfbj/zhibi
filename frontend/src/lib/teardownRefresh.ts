/** SSE 拆书的刷新边界：进度不读书，保存只读两份轻量数据，结束只整本刷新一次。 */
export function teardownRefreshGate() {
  const settled = new Set<string>()
  return (event: 'job' | 'message' | 'saved', job?: { id: string; status: string }) => {
    if (event === 'saved') return 'parts'
    if (event !== 'job' || !job || !['succeeded', 'failed', 'cancelled'].includes(job.status)) return 'none'
    if (settled.has(job.id)) return 'none'
    settled.add(job.id)
    return 'book'
  }
}
