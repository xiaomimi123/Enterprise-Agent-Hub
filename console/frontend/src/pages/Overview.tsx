import { ArrowRight, Clock, ShieldAlert } from 'lucide-react'
import { Alert, Skeleton } from 'antd'
import dayjs from 'dayjs'
import type { EChartsOption } from 'echarts'
import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type Overview as OverviewData } from '../api'
import EChart, { areaGradient } from '../components/EChart'
import { deptColor, fromNow, greeting, tokens, useRequest, yuan } from '../lib'
import { useSession } from '../auth'
import { useTheme } from '../theme'
import { Avatar, Empty, Meter, PageHeader, Panel, Pill, Sparkline } from '../ui'

export default function Overview() {
  const { data, loading, error } = useRequest(api.overview)
  const nav = useNavigate()
  const { p } = useTheme()
  const session = useSession()

  const trendOption = useMemo<EChartsOption>(() => ({
    tooltip: {
      trigger: 'axis',
      formatter: (ps) => {
        const p = (Array.isArray(ps) ? ps : [ps])[0] as { dataIndex: number }
        const t = data!.trend[p.dataIndex]
        return `${t.date}<br/>Token&nbsp;&nbsp;<b>${tokens(t.tokens)}</b><br/>花费&nbsp;&nbsp;&nbsp;&nbsp;<b>${yuan(t.cost)}</b>`
      },
    },
    grid: { left: 8, right: 20, top: 16, bottom: 4, containLabel: true },
    xAxis: { type: 'category', boundaryGap: false, data: data?.trend.map((t) => dayjs(t.date).format('M/D')) ?? [] },
    yAxis: { type: 'value', axisLabel: { formatter: (v: number) => (v ? `${v / 1e4}万` : '0') }, splitNumber: 3 },
    series: [{
      type: 'line', smooth: 0.35, symbol: 'circle', symbolSize: 5, showSymbol: false,
      lineStyle: { width: 2, color: p.accent }, itemStyle: { color: p.accent },
      areaStyle: { color: areaGradient(p.accent) },
      data: data?.trend.map((t) => t.tokens) ?? [],
    }],
  }), [data, p])

  if (error) return <Alert type="error" title="加载失败" description={error} showIcon />
  if (loading || !data) return <Skeleton active paragraph={{ rows: 14 }} style={{ marginTop: 24 }} />
  const s = data.stats
  const ops = data.daily_ops
  const activeToday = ops.length ? ops[ops.length - 1].online : 0   // 今天有过信号（心跳、调用中枢工具、用中枢模型）的人数，不会因为此刻没开 agent 就归零
  const budgetPct = Math.round((s.cost_month / s.budget_month) * 100)
  const maxDept = Math.max(...data.cost_by_dept.map((d) => d.cost))

  return (
    <>
      <PageHeader
        title={`${greeting()}，${session.user.display_name || '管理员'} 👋`}
        sub={<>现在有 <b className="num" style={{ color: 'var(--ink)' }}>{s.agents_online}</b> 人在线，今天共 <b className="num" style={{ color: 'var(--ink)' }}>{activeToday}</b> 人用过，
          中枢拦截了 <b className="num" style={{ color: 'var(--red)' }}>{s.denied_today}</b> 次越权访问，
          <b className="num" style={{ color: 'var(--ink)' }}>{s.pending_approvals}</b> 个动作等待员工确认。</>}
        extra={<span className="chip">{dayjs().format('YYYY 年 M 月 D 日 dddd')}</span>}
      />

      <div className="stack">
        <section className="panel kpi-strip">
          <Kpi label="在线 agent" value={s.agents_online} unit={`/ ${s.members}`}
            note={`已安装 ${s.agents_installed} 台 · 今日活跃 ${activeToday} 人`} spark={ops.map((d) => d.online)} />
          <Kpi label="今日任务" value={s.tasks_today.toLocaleString()} unit="次"
            note={`Token ${tokens(s.tokens_today)}`} spark={data.trend.map((t) => t.tokens)} color={p.green} />
          <div className="kpi">
            <div className="kpi-label">本月模型花费</div>
            <div className="kpi-value num">{yuan(s.cost_month, 0)}</div>
            <div style={{ marginTop: 14 }}>
              <Meter value={budgetPct} />
              <div className="kpi-foot" style={{ marginTop: 8 }}>
                <span className="kpi-note">预算 {yuan(s.budget_month, 0)}</span>
                <span className="kpi-note num">{budgetPct}%</span>
              </div>
            </div>
          </div>
          <Kpi label={<><ShieldAlert />今日越权拦截</>} value={s.denied_today} unit="次" valueColor="var(--red)"
            note="权限在中枢强制执行" spark={ops.map((d) => d.denied)} color={p.red} />
        </section>

        <div className="grid g-main">
          <Panel title="中枢运行拓扑" sub="实时" extra={<span className="muted">所有调用都经过中枢鉴权与留痕</span>}>
            <Topology data={data} />
          </Panel>
          <Panel title="实时活动" tight extra={<a onClick={() => nav('/audit')} className="muted">全部 <ArrowRight /></a>}>
            <div className="rows" style={{ maxHeight: 352, overflow: 'auto' }}>
              {data.recent.slice(0, 7).map((t) => (
                <div key={t.id} className="row-item clickable" onClick={() => nav(`/audit?trace=${t.id}`)}>
                  <Avatar name={t.member} size={30} />
                  <div className="row-main">
                    <div className="row-title">{t.summary}</div>
                    <div className="row-meta">
                      {t.member} · {t.dept_name} · {fromNow(t.started_at)}
                      {t.channel !== '官方 agent' && <span style={{ color: 'var(--violet)' }}> · {t.channel}</span>}
                    </div>
                  </div>
                  <Pill>{t.outcome}</Pill>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <div className="grid g-main">
          <Panel title="Token 用量" sub="近 14 天">
            <EChart option={trendOption} height={240} />
          </Panel>
          <Panel title="本月花费" sub="按部门">
            <div className="stack" style={{ gap: 13 }}>
              {data.cost_by_dept.map((d) => (
                <div key={d.dept} style={{ display: 'grid', gridTemplateColumns: '92px 1fr 64px', alignItems: 'center', gap: 10 }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 7, whiteSpace: 'nowrap' }}>
                    <span className="dot" style={{ background: deptColor(d.dept) }} />{d.dept}
                  </span>
                  <Meter value={maxDept ? (d.cost / maxDept) * 100 : 0} color={deptColor(d.dept)} height={8} />
                  <span className="num" style={{ textAlign: 'right', color: d.cost ? 'var(--ink)' : 'var(--ink-3)' }}>
                    {d.cost ? yuan(d.cost, 0) : '本地'}
                  </span>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <div className="grid g-3">
          <Panel title="GPU 能力节点" sub="全公司共享">
            <div className="stack" style={{ gap: 18 }}>
              {data.gpu_nodes.map((n) => (
                <div key={n.id}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 600 }}>{n.name}</span>
                    <Pill>{n.status}</Pill>
                  </div>
                  <div className="muted" style={{ fontSize: 12, margin: '4px 0 10px' }}>
                    {n.gpu} · {n.workflows.join(' / ')}
                  </div>
                  <Meter value={n.utilization} />
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }} className="muted num">
                    <span>负载 {n.utilization}%</span>
                    <span>排队 {n.queue} · 今日 {n.jobs_today} 个</span>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
          <Panel title={<><Clock style={{ color: 'var(--amber)' }} />待员工确认</>} tight>
            {data.pending.length === 0 ? <Empty>没有待确认的动作</Empty> : (
              <div className="rows">
                {data.pending.slice(0, 4).map((p) => (
                  <div key={p.trace_id + p.tool} className="row-item clickable" onClick={() => nav(`/audit?trace=${p.trace_id}`)}>
                    <Avatar name={p.member} size={28} />
                    <div className="row-main">
                      <div className="row-title">{p.detail}</div>
                      <div className="row-meta">{p.member} · {p.dept_name} · {fromNow(p.time)}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Panel>
          <Panel title={<><ShieldAlert style={{ color: 'var(--red)' }} />越权拦截</>} tight
            extra={<a className="muted" onClick={() => nav('/audit?outcome=被拦截')}>全部 <ArrowRight /></a>}>
            <div className="rows">
              {data.recent_denied.slice(0, 4).map((t) => (
                <div key={t.id} className="row-item clickable" onClick={() => nav(`/audit?trace=${t.id}`)}>
                  <Avatar name={t.member} size={28} />
                  <div className="row-main">
                    <div className="row-title">{t.summary}</div>
                    <div className="row-meta">
                      {t.member} · {t.dept_name} · {fromNow(t.started_at)}
                      {t.channel !== '官方 agent' && <span style={{ color: 'var(--violet)' }}> · {t.channel}</span>}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </>
  )
}

function Kpi({ label, value, unit, note, spark, color, valueColor }: {
  label: React.ReactNode
  value: React.ReactNode
  unit?: string
  note: string
  spark: number[]
  color?: string
  valueColor?: string
}) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value num" style={{ color: valueColor }}>{value}{unit && <small>{unit}</small>}</div>
      <div className="kpi-foot">
        <span className="kpi-note">{note}</span>
        <Sparkline data={spark} color={color} width={88} height={28} />
      </div>
    </div>
  )
}

/** 中枢拓扑：左侧接入方 → 中枢 → 右侧能力 */
function Topology({ data }: { data: OverviewData }) {
  const { p } = useTheme()
  const s = data.stats
  const gpuQueue = data.gpu_nodes.reduce((n, g) => n + g.queue, 0)
  const svc = (name: string) => data.services.find((x) => x.name === name)
  const right = [
    { y: 34, title: '知识检索', sub: `RAGFlow · ${s.knowledge_docs} 份文档`, ms: svc('知识检索')?.latency_ms, color: p.blue },
    { y: 106, title: '模型网关', sub: `New API · 云端 + 本地`, ms: svc('模型网关')?.latency_ms, color: p.green },
    { y: 178, title: 'GPU 能力节点', sub: `${data.gpu_nodes.length} 台 · 排队 ${gpuQueue}`, ms: undefined, color: p.amber },
    { y: 250, title: '技能仓库', sub: `${s.skills} 个技能 · git 下发`, ms: undefined, color: p.violet },
  ]
  const hub = { x: 262, y: 92, w: 176, h: 160 }
  const cy = hub.y + hub.h / 2

  return (
    <svg className="topo" viewBox="0 0 680 300" width="100%" style={{ display: 'block', maxHeight: 340 }}>
      {/* 左侧 → 中枢 */}
      <path d={`M176,96 C222,96 222,${cy - 22} ${hub.x},${cy - 22}`} fill="none" stroke={p.accent} strokeOpacity=".22" strokeWidth="2" />
      <path className="flow" d={`M176,96 C222,96 222,${cy - 22} ${hub.x},${cy - 22}`} fill="none" stroke={p.accent} strokeWidth="2" />
      <path d={`M176,214 C222,214 222,${cy + 22} ${hub.x},${cy + 22}`} fill="none" stroke={p.violet} strokeOpacity=".18" strokeWidth="2" strokeDasharray="4 4" />
      <path className="flow slow" d={`M176,214 C222,214 222,${cy + 22} ${hub.x},${cy + 22}`} fill="none" stroke={p.violet} strokeWidth="2" />
      <g transform="translate(206,198)">
        <rect x="-16" y="-9" width="32" height="18" rx="5" fill="var(--violet-soft)" />
        <text x="0" y="4" textAnchor="middle" className="t3" fill="var(--violet)">只读</text>
      </g>

      {/* 中枢 → 右侧 */}
      {right.map((r) => {
        const d = `M${hub.x + hub.w},${cy} C${hub.x + hub.w + 46},${cy} ${hub.x + hub.w + 46},${r.y + 22} 504,${r.y + 22}`
        return (
          <g key={r.title}>
            <path d={d} fill="none" stroke={r.color} strokeOpacity=".2" strokeWidth="2" />
            <path className="flow" d={d} fill="none" stroke={r.color} strokeWidth="2" style={{ animationDelay: `${r.y / 200}s` }} />
          </g>
        )
      })}

      {/* 左侧节点 */}
      <g transform="translate(16,64)">
        <rect className="node" width="160" height="64" rx="12" />
        <circle cx="22" cy="32" r="12" fill="var(--accent-soft)" />
        <circle cx="22" cy="32" r="4" fill="var(--accent)" />
        <text x="42" y="28" className="t1">员工 agent</text>
        <text x="42" y="46" className="t2">在线 {s.agents_online} / {s.members} 人</text>
      </g>
      <g transform="translate(16,182)">
        <rect className="node" width="160" height="64" rx="12" strokeDasharray="4 3" />
        <circle cx="22" cy="32" r="12" fill="var(--violet-soft)" />
        <circle cx="22" cy="32" r="4" fill="var(--violet)" />
        <text x="42" y="28" className="t1">外部智能体</text>
        <text x="42" y="46" className="t2">ChatGPT 等 · MCP</text>
      </g>

      {/* 中枢 */}
      <g transform={`translate(${hub.x},${hub.y})`}>
        <rect width={hub.w} height={hub.h} rx="16" fill="url(#hubg)" />
        <rect width={hub.w} height={hub.h} rx="16" fill="none" stroke="#fff" strokeOpacity=".22" />
        <text x={hub.w / 2} y="34" textAnchor="middle" style={{ fontSize: 15, fontWeight: 650, fill: '#fff' }}>智能体中枢</text>
        <text x={hub.w / 2} y="52" textAnchor="middle" style={{ fontSize: 11, fill: '#fff', opacity: 0.7 }}>MCP Server · 私有化</text>
        {['身份', '权限', '审计', '路由'].map((t, i) => (
          <g key={t} transform={`translate(${18 + (i % 2) * 74},${70 + Math.floor(i / 2) * 30})`}>
            <rect width="66" height="22" rx="6" fill="#fff" fillOpacity=".14" />
            <text x="33" y="15" textAnchor="middle" style={{ fontSize: 11.5, fill: '#fff', fontWeight: 500 }}>{t}</text>
          </g>
        ))}
        <g transform={`translate(${hub.w - 14},-8)`}>
          <rect x="-50" width="64" height="22" rx="11" style={{ fill: 'var(--surface)', stroke: 'var(--red-line)' }} />
          <text x="-18" y="15" textAnchor="middle" className="t3" fill="var(--red)">拦截 {s.denied_today}</text>
        </g>
      </g>
      <defs>
        <linearGradient id="hubg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={p.accent} />
          <stop offset="1" stopColor={p.accentDeep} />
        </linearGradient>
      </defs>

      {/* 右侧节点 */}
      {right.map((r) => (
        <g key={r.title} transform={`translate(504,${r.y})`}>
          <rect className="node" width="164" height="44" rx="10" />
          <rect x="12" y="15" width="14" height="14" rx="4" fill={r.color} fillOpacity=".16" />
          <rect x="16" y="19" width="6" height="6" rx="2" fill={r.color} />
          <text x="34" y="20" className="t1" style={{ fontSize: 12 }}>{r.title}</text>
          <text x="34" y="35" className="t2">{r.sub}</text>
          {r.ms !== undefined && <text x="154" y="20" textAnchor="end" className="t2 mono" style={{ fontSize: 10 }}>{r.ms}ms</text>}
        </g>
      ))}
    </svg>
  )
}

