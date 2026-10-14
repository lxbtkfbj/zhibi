import clsx from 'clsx'

const PALETTES = [
  { bg: '#2f3e5c', edge: '#22304a', label: '#efe6d2' }, // 黛蓝
  { bg: '#2f5f57', edge: '#234943', label: '#efe6d2' }, // 青碧
  { bg: '#7a4a2a', edge: '#5f391f', label: '#f3e9d6' }, // 赭石
  { bg: '#8f2f24', edge: '#71241b', label: '#f3e9d6' }, // 朱砂
  { bg: '#3a3631', edge: '#2a2723', label: '#ece3cf' }, // 玄墨
  { bg: '#56654b', edge: '#43503a', label: '#efe6d2' }, // 苍绿
]

function hash(text: string) {
  let h = 0
  for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return h
}

function coverPalette(seed: string) {
  return PALETTES[hash(seed) % PALETTES.length]
}

/** 线装书封面：左侧装订线，右上竖排题签，左下钤印。 */
export function BookCover({
  title,
  seed,
  size = 'md',
  className,
}: {
  title: string
  seed: string
  size?: 'xs' | 'sm' | 'md' | 'lg'
  className?: string
}) {
  const p = coverPalette(seed)
  const width = { xs: 28, sm: 64, md: 150, lg: 180 }[size]
  const tiny = size === 'xs'
  const shortTitle = title.replace(/[（(].*$/, '').slice(0, 12)
  const titleSize = tiny ? 0 : shortTitle.length > 8 ? width * 0.085 : width * 0.11

  return (
    <div
      className={clsx('relative shrink-0 overflow-hidden rounded-r-[5px] rounded-l-[2px]', className)}
      style={{
        width,
        aspectRatio: '3 / 4',
        background: `${p.bg} repeating-linear-gradient(45deg, rgb(255 255 255 / 0.025) 0 2px, transparent 2px 6px)`,
        boxShadow: tiny ? 'none' : 'inset -6px 0 12px -8px rgb(0 0 0 / 0.35), 0 1px 2px rgb(0 0 0 / 0.15)',
      }}
      aria-hidden
    >
      {/* 装订线 */}
      <div className="absolute inset-y-0 left-0" style={{ width: width * 0.11, background: p.edge }}>
        {!tiny &&
          [0.16, 0.38, 0.62, 0.84].map((top) => (
            <span key={top} className="absolute left-1/2 -translate-x-1/2" style={{ top: `${top * 100}%` }}>
              <span className="block h-px bg-[#e9dcc0]/60" style={{ width: width * 0.16, marginLeft: -width * 0.02 }} />
              <span className="absolute -top-[2px] left-1/2 block size-[3px] -translate-x-1/2 rounded-full bg-black/40" />
            </span>
          ))}
      </div>
      {/* 题签 */}
      {!tiny && (
        <div
          className="absolute flex justify-center border border-black/10 py-2"
          style={{
            top: width * 0.1,
            right: width * 0.12,
            width: width * 0.24,
            height: '62%',
            background: p.label,
            boxShadow: 'inset 0 0 0 2px rgb(255 255 255 / 0.4)',
          }}
        >
          <span
            className="vertical overflow-hidden font-serif font-bold text-[#2a2622]"
            style={{ fontSize: titleSize, lineHeight: 1.1, letterSpacing: '0.08em' }}
          >
            {shortTitle}
          </span>
        </div>
      )}
      {/* 钤印 */}
      {!tiny && size !== 'sm' && (
        <span
          className="absolute flex items-center justify-center bg-seal font-serif text-[#f6eadf]"
          style={{ left: width * 0.2, bottom: width * 0.1, width: width * 0.13, height: width * 0.13, fontSize: width * 0.055, opacity: 0.9 }}
        >
          执笔
        </span>
      )}
    </div>
  )
}
