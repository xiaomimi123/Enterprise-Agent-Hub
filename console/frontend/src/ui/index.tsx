import type { ReactNode } from 'react'
import { DEPT_META, TONE } from '../lib'

export function PageHeader({ title, sub, extra }: { title: ReactNode; sub?: ReactNode; extra?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1 className="page-title">{title}</h1>
        {sub && <div className="page-sub">{sub}</div>}
      </div>
      {extra && <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0 }}>{extra}</div>}
    </div>
  )
}

export function Panel({ title, sub, extra, children, flat, tight, style, className = '' }: {
  title?: ReactNode
  sub?: ReactNode
  extra?: ReactNode
  children: ReactNode
  flat?: boolean
  tight?: boolean
  style?: React.CSSProperties
  className?: string
}) {
  return (
    <section className={`panel ${className}`} style={style}>
      {(title || extra) && (
        <div className={`panel-head ${flat ? 'flat' : ''}`}>
          <div className="panel-title">{title}{sub && <span className="panel-sub">{sub}</span>}</div>
          {extra}
        </div>
      )}
      <div className={`panel-body ${tight ? 'tight' : ''}`}>{children}</div>
    </section>
  )
}

/** 状态胶囊：根据文字自动选色调 */
export function Pill({ children, tone, dot = true }: { children: ReactNode; tone?: string; dot?: boolean }) {
  const t = tone ?? (typeof children === 'string' ? TONE[children] : undefined) ?? 'gray'
  return <span className={`pill ${t}`}>{dot && <i />}{children}</span>
}

export function Token({ children }: { children: ReactNode }) {
  return <span className="token">{children}</span>
}

const AVATAR_COLORS = ['#5b5bd6', '#e5484d', '#30a46c', '#0090ff', '#8e4ec6', '#d6409f', '#12a594', '#f76b15', '#3a3936']

export function Avatar({ name, size = 28 }: { name: string; size?: number }) {
  let h = 0
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0
  const bg = AVATAR_COLORS[h % AVATAR_COLORS.length]
  return (
    <span className="avatar" title={name} style={{ width: size, height: size, background: bg, fontSize: size * 0.42 }}>
      {name.length > 2 ? name.slice(-2) : name}
    </span>
  )
}

export function AvatarStack({ names, max = 5, size = 24 }: { names: string[]; max?: number; size?: number }) {
  const rest = names.length - max
  return (
    <span className="avatar-stack">
      {names.slice(0, max).map((n) => <Avatar key={n} name={n} size={size} />)}
      {rest > 0 && (
        <span className="avatar" style={{ width: size, height: size, background: 'var(--surface-3)', color: 'var(--ink-2)', fontSize: 11 }}>
          +{rest}
        </span>
      )}
    </span>
  )
}

export function DeptTile({ dept, size = 36, children }: { dept: string; size?: number; children?: ReactNode }) {
  const m = DEPT_META[dept] ?? DEPT_META.all
  return (
    <span className="dept-tile" style={{ width: size, height: size, background: m.soft, color: m.color, fontSize: size * 0.42, fontWeight: 650 }}>
      {children ?? m.short}
    </span>
  )
}

export function Meter({ value, color, height = 6 }: { value: number; color?: string; height?: number }) {
  const v = Math.max(0, Math.min(100, value))
  const c = color ?? (v >= 90 ? 'var(--red)' : v >= 70 ? '#f5a524' : 'var(--accent)')
  return <div className="meter" style={{ height }}><span style={{ width: `${v}%`, background: c }} /></div>
}

export function Seg<T extends string | number>({ value, options, onChange }: {
  value: T
  options: { value: T; label: ReactNode }[]
  onChange: (v: T) => void
}) {
  return (
    <div className="seg">
      {options.map((o) => (
        <button key={String(o.value)} className={o.value === value ? 'on' : ''} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  )
}

/** 迷你趋势线（SVG） */
export function Sparkline({ data, color = 'var(--accent)', width = 96, height = 32, fill = true }: {
  data: number[]
  color?: string
  width?: number
  height?: number
  fill?: boolean
}) {
  if (data.length < 2) return null
  const max = Math.max(...data)
  const min = Math.min(...data)
  const span = max - min || 1
  const pts = data.map((v, i) => [(i / (data.length - 1)) * width, height - 3 - ((v - min) / span) * (height - 6)])
  const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const id = `sp${Math.abs(data.reduce((a, b) => a * 31 + b, 7) | 0)}`
  const [lx, ly] = pts[pts.length - 1]
  return (
    <svg width={width} height={height} style={{ display: 'block', overflow: 'visible' }}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.18" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {fill && <path d={`${line} L${width},${height} L0,${height} Z`} fill={`url(#${id})`} />}
      <path d={line} fill="none" stroke={color} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lx} cy={ly} r="2.5" fill={color} />
    </svg>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div style={{ padding: '28px 0', textAlign: 'center', color: 'var(--ink-3)' }}>{children}</div>
}
