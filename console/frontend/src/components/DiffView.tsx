import { useMemo } from 'react'

export interface DiffLine { type: 'same' | 'add' | 'del'; text: string }

/** 逐行比较（最长公共子序列）。技能文件不大，O(n·m) 足够。 */
export function diffLines(a: string, b: string): DiffLine[] {
  const x = a.split('\n')
  const y = b.split('\n')
  const dp: number[][] = Array.from({ length: x.length + 1 }, () => new Array<number>(y.length + 1).fill(0))
  for (let i = x.length - 1; i >= 0; i--) {
    for (let j = y.length - 1; j >= 0; j--) dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
  }
  const out: DiffLine[] = []
  let i = 0
  let j = 0
  while (i < x.length && j < y.length) {
    if (x[i] === y[j]) { out.push({ type: 'same', text: x[i] }); i++; j++ }
    else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ type: 'del', text: x[i++] })
    else out.push({ type: 'add', text: y[j++] })
  }
  while (i < x.length) out.push({ type: 'del', text: x[i++] })
  while (j < y.length) out.push({ type: 'add', text: y[j++] })
  return out
}

const STYLE: Record<DiffLine['type'], { bg: string; mark: string }> = {
  same: { bg: 'transparent', mark: ' ' },
  add: { bg: 'color-mix(in srgb, var(--green) 16%, transparent)', mark: '+' },
  del: { bg: 'color-mix(in srgb, var(--red) 16%, transparent)', mark: '−' },
}

/** 旧内容 → 新内容的差异。没有变化的行只保留改动前后各 2 行，其余折叠。 */
export default function DiffView({ before, after }: { before: string; after: string }) {
  const rows = useMemo(() => {
    const all = diffLines(before, after)
    const keep = new Set<number>()
    all.forEach((l, i) => { if (l.type !== 'same') for (let k = i - 2; k <= i + 2; k++) keep.add(k) })
    const out: (DiffLine | { type: 'gap'; n: number })[] = []
    let skipped = 0
    all.forEach((l, i) => {
      if (keep.has(i)) {
        if (skipped) { out.push({ type: 'gap', n: skipped }); skipped = 0 }
        out.push(l)
      } else skipped++
    })
    if (skipped) out.push({ type: 'gap', n: skipped })
    return { out, changed: all.some((l) => l.type !== 'same') }
  }, [before, after])

  if (!rows.changed) return <div className="muted" style={{ padding: 12 }}>内容没有差异</div>
  return (
    <pre className="mono" style={{ margin: 0, fontSize: 12.5, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word', border: '1px solid var(--line-2)', borderRadius: 8, overflow: 'hidden' }}>
      {rows.out.map((l, i) => 'n' in l
        ? <div key={i} className="muted" style={{ padding: '2px 10px', background: 'var(--surface-2)' }}>… 省略 {l.n} 行未改动 …</div>
        : <div key={i} style={{ padding: '0 10px', background: STYLE[l.type].bg }}><span className="muted" style={{ marginRight: 8 }}>{STYLE[l.type].mark}</span>{l.text || ' '}</div>)}
    </pre>
  )
}
