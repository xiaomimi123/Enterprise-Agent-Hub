import { Skeleton, Table } from 'antd'
import dayjs from 'dayjs'
import { useState } from 'react'
import { api, type WorkCounts, type WorkItem, type WorkPerson, type WorkRole } from '../api'
import { useRequest } from '../lib'
import { Avatar, PageHeader, Panel, Pill, Seg } from '../ui'

const STATUS_TONE: Record<string, string> = { 已完成: 'green', 待审核: 'blue', 进行中: 'amber', 受阻: 'red' }

function Counts({ c }: { c: WorkCounts }) {
  if (!c.total) return <span className="muted">—</span>
  return (
    <span className="num" style={{ fontSize: 13 }}>
      <b style={{ color: 'var(--green)' }}>{c.已完成}</b>
      <span className="muted"> 完成 · {c.待审核} 待审 · {c.进行中} 进行</span>
      {c.受阻 > 0 && <b style={{ color: 'var(--red)' }}> · {c.受阻} 受阻</b>}
    </span>
  )
}

const kindsText = (k: Record<string, number>) => Object.entries(k).map(([n, v]) => `${n} ${v}`).join('、') || '—'

export default function WorkPage() {
  const [days, setDays] = useState(7)
  const [view, setView] = useState<'role' | 'person'>('role')
  const { data, loading } = useRequest(() => api.workReport(days), [days])
  if (loading || !data) return <Skeleton active paragraph={{ rows: 12 }} style={{ marginTop: 24 }} />
  const t = data.totals

  return (
    <>
      <PageHeader
        title="工作看板"
        sub="各岗位、各成员做成了什么：成果由员工的 agent 调用 report_work 上报（笔记、对标报告、封面、视频等的状态和进度）；出图出视频、调用数是自动统计的活动，仅供参考，不是绩效。"
        extra={<Seg value={days} onChange={setDays} options={[{ value: 1, label: '今天' }, { value: 7, label: '近 7 天' }, { value: 30, label: '近 30 天' }]} />}
      />
      <div className="stack">
        <section className="panel kpi-strip">
          <div className="kpi"><div className="kpi-label">已完成成果</div><div className="kpi-value num" style={{ color: 'var(--green)' }}>{t.items.已完成}</div></div>
          <div className="kpi"><div className="kpi-label">待审核 / 进行中</div><div className="kpi-value num">{t.items.待审核}<small> / {t.items.进行中}</small></div></div>
          <div className="kpi"><div className="kpi-label">受阻</div><div className="kpi-value num" style={{ color: t.items.受阻 ? 'var(--red)' : undefined }}>{t.items.受阻}</div></div>
          <div className="kpi"><div className="kpi-label">有活动的人</div><div className="kpi-value num">{t.active_people}<small> / {t.people}</small></div></div>
          <div className="kpi"><div className="kpi-label">出图 / 视频</div><div className="kpi-value num">{t.images}<small> 张 / </small>{t.videos}<small> 条</small></div></div>
        </section>

        {t.items.total === 0 && (
          <div className="panel" style={{ padding: '14px 18px' }}>
            这段时间没有人上报成果，下面只有活动量。让员工的 agent 在完成工作后调用 <code>report_work</code>（中枢的 MCP 说明里已经写了），这里才会出现成果和进度。
          </div>
        )}

        <Panel title={view === 'role' ? '按岗位' : '按个人'} extra={<Seg value={view} onChange={setView} options={[{ value: 'role', label: '岗位' }, { value: 'person', label: '个人' }]} />} tight>
          {view === 'role' ? (
            <Table<WorkRole>
              rowKey="role" dataSource={data.roles} pagination={false} scroll={{ x: 760 }} locale={{ emptyText: '暂无数据' }}
              columns={[
                { title: '岗位', dataIndex: 'role', render: (v) => <span style={{ fontWeight: 500 }}>{v}</span> },
                { title: '人数（有活动）', key: 'p', width: 120, render: (_, r) => <span className="num">{r.active_people} / {r.people}</span> },
                { title: '成果', key: 'i', render: (_, r) => <Counts c={r.items} /> },
                { title: '类型', key: 'k', render: (_, r) => <span className="muted" style={{ fontSize: 12 }}>{kindsText(r.kinds)}</span> },
                { title: '出图 / 视频', key: 'g', width: 100, align: 'right', render: (_, r) => <span className="num">{r.images} / {r.videos}</span> },
                { title: '调用', dataIndex: 'calls', width: 70, align: 'right', render: (v) => <span className="num">{v}</span> },
              ]}
            />
          ) : (
            <Table<WorkPerson>
              rowKey="user_name" dataSource={data.people} pagination={{ pageSize: 10, showSizeChanger: false, size: 'small' }} scroll={{ x: 820 }}
              locale={{ emptyText: '暂无数据' }}
              columns={[
                {
                  title: '成员', dataIndex: 'display_name', render: (v, r) => (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <Avatar name={v} size={24} /><span style={{ fontWeight: 500 }}>{v}</span>
                      <span className="muted" style={{ fontSize: 12 }}>{r.role}</span>
                    </div>
                  ),
                },
                { title: '成果', key: 'i', render: (_, r) => <Counts c={r.items} /> },
                { title: '类型', key: 'k', render: (_, r) => <span className="muted" style={{ fontSize: 12 }}>{kindsText(r.kinds)}</span> },
                { title: '出图 / 视频', key: 'g', width: 100, align: 'right', render: (_, r) => <span className="num">{r.images} / {r.videos}</span> },
                { title: '活跃天数', dataIndex: 'active_days', width: 80, align: 'right', render: (v) => <span className="num">{v}</span> },
                {
                  title: '最近活动', dataIndex: 'last_active', width: 110,
                  render: (v: string | null) => v ? <span className="muted">{dayjs(v).format('M/D HH:mm')}</span> : <Pill tone="gray" dot={false}>无活动</Pill>,
                },
              ]}
            />
          )}
        </Panel>

        <Panel title="成果清单" sub={`按更新时间，最多 ${data.items.length} 条`} tight>
          <Table<WorkItem>
            rowKey="id" dataSource={data.items} pagination={{ pageSize: 10, showSizeChanger: false, size: 'small' }} scroll={{ x: 760 }}
            locale={{ emptyText: '这段时间没有上报' }}
            columns={[
              {
                title: '成果', dataIndex: 'title', render: (v, r) => (
                  <div>
                    <div style={{ fontWeight: 500 }}>{r.link ? <a href={r.link} target="_blank" rel="noreferrer">{v}</a> : v}</div>
                    {r.note && <div className="muted" style={{ fontSize: 12 }}>{r.note}</div>}
                  </div>
                ),
              },
              { title: '类型', dataIndex: 'kind', width: 100, render: (v) => <Pill tone="gray" dot={false}>{v}</Pill> },
              { title: '状态', dataIndex: 'status', width: 100, render: (v, r) => <Pill tone={STATUS_TONE[v] ?? 'gray'}>{v}{v === '进行中' || v === '待审核' ? ` ${r.progress}%` : ''}</Pill> },
              { title: '负责人', dataIndex: 'display_name', width: 140, render: (v, r) => <span>{v} <span className="muted" style={{ fontSize: 12 }}>{r.role}</span></span> },
              { title: '更新', dataIndex: 'updated_at', width: 110, render: (v) => <span className="muted">{dayjs(v).format('M/D HH:mm')}</span> },
            ]}
          />
        </Panel>
      </div>
    </>
  )
}
