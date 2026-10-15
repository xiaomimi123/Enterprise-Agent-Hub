import { SearchOutlined } from '@ant-design/icons'
import { Drawer, Input, Select, Table } from 'antd'
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, type TraceBrief } from '../api'
import { fmtSec, fmtTime, tokens, useRequest, yuan } from '../lib'
import { Avatar, PageHeader, Panel, Pill, Seg } from '../ui'

const NODE: Record<string, string> = { 通过: '#30a46c', 拒绝: '#e5484d', 待确认: '#f5a524' }

export default function Audit() {
  const [params, setParams] = useSearchParams()
  const [outcome, setOutcome] = useState(params.get('outcome') ?? '全部')
  const [dept, setDept] = useState<string>()
  const [q, setQ] = useState<string>()
  const depts = useRequest(api.departments)
  const all = useRequest(() => api.traces({ dept, q }), [dept, q])
  const rows = useMemo(() => all.data?.filter((t) => outcome === '全部' || t.outcome === outcome), [all.data, outcome])

  const openId = params.get('trace') ?? undefined
  const setOpenId = (id?: string) => {
    const next = new URLSearchParams(params)
    if (id) next.set('trace', id)
    else next.delete('trace')
    setParams(next, { replace: true })
  }

  const count = (o: string) => all.data?.filter((t) => t.outcome === o).length ?? 0
  const external = all.data?.filter((t) => t.channel !== '官方 agent').length ?? 0

  return (
    <>
      <PageHeader
        title="审计日志"
        sub="每一次调用都留痕。同一个任务从登录、检索、模型调用到本机动作，每一步都带同一个追踪 ID：查了什么、被拒绝了什么、生成了什么、花了多少钱。"
      />
      <div className="stack">
        <section className="panel kpi-strip">
          <div className="kpi"><div className="kpi-label">近 7 天链路</div><div className="kpi-value num">{all.data?.length ?? '-'}</div></div>
          <div className="kpi"><div className="kpi-label">被拦截</div><div className="kpi-value num" style={{ color: 'var(--red)' }}>{count('被拦截')}</div></div>
          <div className="kpi"><div className="kpi-label">待员工确认</div><div className="kpi-value num" style={{ color: 'var(--amber)' }}>{count('待审批')}</div></div>
          <div className="kpi"><div className="kpi-label">外部智能体调用</div><div className="kpi-value num" style={{ color: 'var(--violet)' }}>{external}</div></div>
        </section>

        <Panel
          tight
          title={<Seg value={outcome} onChange={setOutcome} options={['全部', '成功', '被拦截', '待审批'].map((v) => ({ value: v, label: v }))} />}
          extra={
            <div style={{ display: 'flex', gap: 8 }}>
              <Select allowClear placeholder="全部部门" style={{ width: 130 }} value={dept} onChange={setDept} variant="filled"
                options={depts.data?.map((d) => ({ value: d.id, label: d.name }))} />
              <Input allowClear prefix={<SearchOutlined className="muted" />} placeholder="搜索成员或任务" variant="filled"
                onChange={(e) => setQ(e.target.value || undefined)} style={{ width: 200 }} />
            </div>
          }
        >
          <Table<TraceBrief>
            rowKey="id" loading={all.loading} dataSource={rows} scroll={{ x: 900 }}
            pagination={{ pageSize: 14, showSizeChanger: false, size: 'small' }}
            onRow={(t) => ({ onClick: () => setOpenId(t.id), style: { cursor: 'pointer' } })}
            columns={[
              { title: '时间', dataIndex: 'started_at', width: 110, render: (v) => <span className="mono muted">{fmtTime(v)}</span> },
              {
                title: '成员', dataIndex: 'member', width: 150, render: (v, t) => (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Avatar name={v} size={24} />
                    <div style={{ lineHeight: 1.3 }}>
                      <div style={{ fontWeight: 500 }}>{v}</div>
                      <div className="muted" style={{ fontSize: 11.5 }}>{t.dept_name}</div>
                    </div>
                  </div>
                ),
              },
              {
                title: '任务', dataIndex: 'summary', render: (v, t) => (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span>{v}</span>
                    {t.channel !== '官方 agent' && <Pill tone="violet" dot={false}>{t.channel.replace('外部智能体 · ', '')}</Pill>}
                  </div>
                ),
              },
              { title: '步骤', dataIndex: 'step_count', width: 60, align: 'right', render: (v) => <span className="num muted">{v}</span> },
              { title: 'Token', dataIndex: 'tokens', width: 90, align: 'right', render: (v) => <span className="num">{v ? tokens(v) : '—'}</span> },
              { title: '花费', dataIndex: 'cost', width: 80, align: 'right', render: (v) => <span className="num">{v ? yuan(v) : '—'}</span> },
              { title: '结果', dataIndex: 'outcome', width: 90, render: (v) => <Pill>{v}</Pill> },
            ]}
          />
        </Panel>
      </div>
      {openId && <TraceDrawer id={openId} onClose={() => setOpenId(undefined)} />}
    </>
  )
}

function TraceDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const trace = useRequest(() => api.trace(id), [id])
  const t = trace.data
  return (
    <Drawer
      open size={600} onClose={onClose} loading={trace.loading}
      title={t && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span className="mono" style={{ fontWeight: 500 }}>{t.id}</span>
          <Pill>{t.outcome ?? ''}</Pill>
        </div>
      )}
    >
      {t && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
            <Avatar name={t.member} size={40} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 650, fontSize: 15 }}>{t.summary}</div>
              <div className="muted" style={{ marginTop: 3 }}>{t.member} · {t.dept_name} · {t.channel}</div>
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', border: '1px solid var(--line-2)', borderRadius: 10, marginBottom: 24 }}>
            {[['步骤', t.steps.length], ['Token', t.tokens ? tokens(t.tokens) : '—'], ['花费', t.cost ? yuan(t.cost) : '—']].map(([k, v], i) => (
              <div key={k} style={{ padding: '10px 14px', borderLeft: i ? '1px solid var(--line-2)' : undefined }}>
                <div className="muted" style={{ fontSize: 11.5 }}>{k}</div>
                <div className="num" style={{ fontWeight: 650, fontSize: 16, marginTop: 2 }}>{v}</div>
              </div>
            ))}
          </div>
          {t.steps.map((s, i) => (
            <div className="trace-step" key={i}>
              <div className="trace-time">{fmtSec(s.time)}</div>
              <div className="trace-rail"><span className="trace-node" style={{ background: NODE[s.result] ?? 'var(--ink-4)' }} /></div>
              <div className="trace-body">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontWeight: 600 }}>{s.kind}</span>
                  <span className="mono muted">{s.tool}</span>
                  <span style={{ marginLeft: 'auto' }}><Pill>{s.result}</Pill></span>
                </div>
                <div className={`trace-card ${s.result === '拒绝' ? 'deny' : s.result === '待确认' ? 'wait' : ''}`}>
                  {s.detail}
                  {s.tokens > 0 && (
                    <div className="mono muted" style={{ marginTop: 4, fontSize: 11 }}>
                      {s.model} · {tokens(s.tokens)} tokens · {yuan(s.cost)}
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
        </>
      )}
    </Drawer>
  )
}
