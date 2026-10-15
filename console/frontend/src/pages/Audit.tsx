import { Alert, Card, Descriptions, Drawer, Input, Segmented, Select, Space, Table, Tag, Timeline, Typography } from 'antd'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, type TraceBrief } from '../api'
import { fmtSec, fmtTime, StatusTag, tokens, useRequest, yuan } from '../components/common'

const { Text } = Typography

const STEP_COLOR: Record<string, string> = { 通过: 'green', 拒绝: 'red', 待确认: 'gold' }

export default function Audit() {
  const [params, setParams] = useSearchParams()
  const [outcome, setOutcome] = useState(params.get('outcome') ?? '全部')
  const [dept, setDept] = useState<string>()
  const [q, setQ] = useState<string>()
  const depts = useRequest(api.departments)
  const traces = useRequest(
    () => api.traces({ outcome: outcome === '全部' ? undefined : outcome, dept, q }),
    [outcome, dept, q],
  )
  const openId = params.get('trace') ?? undefined
  const setOpenId = (id?: string) => {
    const next = new URLSearchParams(params)
    if (id) next.set('trace', id)
    else next.delete('trace')
    setParams(next, { replace: true })
  }

  return (
    <>
      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        title="每一次调用都留痕"
        description="从登录、检索、模型调用到本机动作，同一个任务的每一步都带同一个追踪 ID：查了什么、被拒绝了什么、生成了什么、花了多少钱，一目了然。"
      />
      <Card
        title="调用链路"
        extra={
          <Space wrap>
            <Segmented value={outcome} onChange={setOutcome} options={['全部', '成功', '被拦截', '待审批']} />
            <Select allowClear placeholder="部门" style={{ width: 130 }} value={dept} onChange={setDept}
              options={depts.data?.map((d) => ({ value: d.id, label: d.name }))} />
            <Input.Search allowClear placeholder="搜索成员或任务" onSearch={(v) => setQ(v || undefined)} style={{ width: 200 }} />
          </Space>
        }
      >
        <Table<TraceBrief>
          rowKey="id" loading={traces.loading} dataSource={traces.data}
          pagination={{ pageSize: 15, showSizeChanger: false }}
          onRow={(t) => ({ onClick: () => setOpenId(t.id), style: { cursor: 'pointer' } })}
          columns={[
            { title: '时间', dataIndex: 'started_at', width: 120, render: (v) => fmtTime(v) },
            { title: '成员', dataIndex: 'member', width: 100, render: (v) => <Text strong>{v}</Text> },
            { title: '部门', dataIndex: 'dept_name', width: 100 },
            {
              title: '任务', dataIndex: 'summary', render: (v, t) => (
                <Space>
                  <span>{v}</span>
                  {t.channel !== '官方 agent' && <Tag color="purple">{t.channel}</Tag>}
                </Space>
              ),
            },
            { title: '步骤', dataIndex: 'step_count', width: 70 },
            { title: 'Token', dataIndex: 'tokens', width: 90, render: (v) => (v ? tokens(v) : '-') },
            { title: '花费', dataIndex: 'cost', width: 90, render: (v) => (v ? yuan(v) : '-') },
            { title: '结果', dataIndex: 'outcome', width: 90, render: (v) => <StatusTag value={v} /> },
          ]}
        />
      </Card>
      {openId && <TraceDrawer id={openId} onClose={() => setOpenId(undefined)} />}
    </>
  )
}

function TraceDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const trace = useRequest(() => api.trace(id), [id])
  const t = trace.data
  return (
    <Drawer open size={640} onClose={onClose} loading={trace.loading}
      title={t && <Space>链路 {t.id}<StatusTag value={t.outcome ?? ''} /></Space>}>
      {t && (
        <>
          <Descriptions size="small" column={2} bordered items={[
            { key: 'm', label: '成员', children: `${t.member} · ${t.dept_name}` },
            { key: 'c', label: '入口', children: t.channel },
            { key: 's', label: '任务', span: 2, children: t.summary },
            { key: 'tk', label: 'Token', children: t.tokens ? tokens(t.tokens) : '-' },
            { key: 'cost', label: '花费', children: t.cost ? yuan(t.cost) : '-' },
          ]} />
          <Timeline
            style={{ marginTop: 24 }}
            items={t.steps.map((s) => ({
              color: STEP_COLOR[s.result] ?? 'gray',
              title: <Text type="secondary">{fmtSec(s.time)}</Text>,
              content: (
                <div>
                  <Space size={6}>
                    <Tag>{s.kind}</Tag>
                    <Text code>{s.tool}</Text>
                    <StatusTag value={s.result} />
                  </Space>
                  <div style={{ marginTop: 4 }}>{s.detail}</div>
                  {s.tokens > 0 && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {s.model} · {tokens(s.tokens)} token · {yuan(s.cost)}
                    </Text>
                  )}
                </div>
              ),
            }))}
          />
        </>
      )}
    </Drawer>
  )
}
