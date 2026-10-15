import { Skeleton, Table } from 'antd'
import dayjs from 'dayjs'
import type { EChartsOption } from 'echarts'
import { useMemo, useState } from 'react'
import { api } from '../api'
import EChart from '../components/EChart'
import { deptColor, tokens, useRequest, yuan } from '../lib'
import { Avatar, Meter, PageHeader, Panel, Seg } from '../ui'

const MODEL_COLOR: Record<string, string> = {
  'Claude Sonnet': '#d97757', 'GPT-4o': '#1b1a17', 'DeepSeek V3': '#4d6bfe', 'Qwen 本地模型': '#30a46c',
}

export default function UsagePage() {
  const [days, setDays] = useState(30)
  const { data, loading } = useRequest(() => api.usage(days), [days])

  const dailyOption = useMemo<EChartsOption>(() => ({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v) => `¥${Number(v).toFixed(2)}` },
    legend: { top: 0, left: 0, type: 'scroll' },
    grid: { left: 4, right: 4, top: 40, bottom: 0, containLabel: true },
    xAxis: { type: 'category', data: data?.daily.map((d) => dayjs(String(d.date)).format('M/D')) ?? [] },
    yAxis: { type: 'value', axisLabel: { formatter: '¥{value}' }, splitNumber: 4 },
    series: (data?.departments ?? []).map((dept, i, arr) => ({
      name: dept, type: 'bar', stack: 'cost', barMaxWidth: 16,
      itemStyle: { color: deptColor(dept), borderRadius: i === arr.length - 1 ? [3, 3, 0, 0] : 0 },
      emphasis: { focus: 'series' },
      data: data?.daily.map((d) => d[dept] as number) ?? [],
    })),
  }), [data])

  if (loading || !data) return <Skeleton active paragraph={{ rows: 12 }} style={{ marginTop: 24 }} />
  const modelTotal = data.by_model.reduce((n, m) => n + m.tokens, 0)

  return (
    <>
      <PageHeader
        title="用量与成本"
        sub="所有模型调用都经过中枢的模型网关，按人、按部门计量。敏感数据只走本地模型，不出公司。"
        extra={<Seg value={days} onChange={setDays} options={[{ value: 7, label: '近 7 天' }, { value: 30, label: '近 30 天' }]} />}
      />
      <div className="stack">
        <section className="panel kpi-strip">
          <div className="kpi"><div className="kpi-label">模型花费</div><div className="kpi-value num">{yuan(data.total_cost, 0)}</div></div>
          <div className="kpi"><div className="kpi-label">Token 用量</div><div className="kpi-value num">{tokens(data.total_tokens)}</div></div>
          <div className="kpi">
            <div className="kpi-label">人均花费</div>
            <div className="kpi-value num">{yuan(data.total_cost / 50, 1)}<small>/ 人</small></div>
          </div>
          <div className="kpi">
            <div className="kpi-label">本地模型占比</div>
            <div className="kpi-value num" style={{ color: 'var(--green)' }}>{Math.round(data.local_ratio * 100)}<small>%</small></div>
            <div className="kpi-note" style={{ marginTop: 8 }}>财务、人事请求只走本地</div>
          </div>
        </section>

        <div className="grid g-main">
          <Panel title="每日花费" sub="按部门堆叠">
            <EChart option={dailyOption} height={300} />
          </Panel>
          <Panel title="模型分布" sub="按 Token">
            <div style={{ display: 'flex', height: 10, borderRadius: 5, overflow: 'hidden', gap: 2, marginBottom: 20 }}>
              {data.by_model.map((m) => (
                <span key={m.model} style={{ flex: m.tokens, background: MODEL_COLOR[m.model] ?? 'var(--ink-3)' }} />
              ))}
            </div>
            <div className="stack" style={{ gap: 16 }}>
              {data.by_model.map((m) => (
                <div key={m.model} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 3, background: MODEL_COLOR[m.model] ?? 'var(--ink-3)' }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600 }}>{m.model}</div>
                    <div className="muted" style={{ fontSize: 12 }}>{m.location} · {tokens(m.tokens)}</div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div className="num" style={{ fontWeight: 600 }}>{Math.round((m.tokens / modelTotal) * 100)}%</div>
                    <div className="muted num" style={{ fontSize: 12 }}>{m.cost ? yuan(m.cost, 0) : '免费'}</div>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <div className="grid g-2">
          <Panel title="部门额度" sub={days === 30 ? '近 30 天' : '近 7 天折算到月'} tight>
            <Table
              rowKey="dept" pagination={false} dataSource={data.by_dept}
              columns={[
                {
                  title: '部门', dataIndex: 'dept', render: (v) => (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                      <span className="dot" style={{ background: deptColor(v) }} />{v}
                    </span>
                  ),
                },
                { title: '花费', dataIndex: 'cost', align: 'right', render: (v) => <span className="num">{v ? yuan(v, 0) : '—'}</span> },
                {
                  title: '额度使用', key: 'q', width: 220,
                  render: (_, r) => {
                    const monthly = days === 30 ? r.cost : (r.cost / 7) * 30
                    const pct = r.quota ? Math.round((monthly / r.quota) * 100) : 0
                    return (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <div style={{ flex: 1 }}><Meter value={pct} /></div>
                        <span className="num muted" style={{ width: 84, textAlign: 'right', fontSize: 12 }}>{pct}% / ¥{r.quota}</span>
                      </div>
                    )
                  },
                },
              ]}
            />
          </Panel>
          <Panel title="个人用量" sub="本月 TOP 10" tight>
            <Table
              rowKey="member_id" pagination={false} dataSource={data.top_members}
              columns={[
                { title: '', key: 'i', width: 44, render: (_, __, i) => <span className="num muted">{String(i + 1).padStart(2, '0')}</span> },
                {
                  title: '成员', dataIndex: 'member', render: (v, r) => (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <Avatar name={v} size={24} />
                      <span style={{ fontWeight: 500 }}>{v}</span>
                      <span className="muted" style={{ fontSize: 12 }}>{r.dept_name}</span>
                    </div>
                  ),
                },
                { title: '调用', dataIndex: 'calls', align: 'right', render: (v) => <span className="num">{v.toLocaleString()}</span> },
                { title: 'Token', dataIndex: 'tokens', align: 'right', render: (v) => <span className="num">{tokens(v)}</span> },
                { title: '花费', dataIndex: 'cost', align: 'right', render: (v) => <span className="num">{yuan(v, 0)}</span> },
              ]}
            />
          </Panel>
        </div>
      </div>
    </>
  )
}
