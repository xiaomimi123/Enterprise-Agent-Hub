import { CirclePlay } from 'lucide-react'
import { Drawer, Image, Table } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type GpuTask } from '../api'
import { fmtTime, useRequest } from '../lib'
import { Avatar, Empty, PageHeader, Panel, Pill, Seg } from '../ui'

const KIND = { image: '图片', video: '视频' } as const
const secs = (v: number | null) => (v == null ? '—' : v < 60 ? `${v} 秒` : `${Math.floor(v / 60)} 分 ${v % 60} 秒`)

export default function Tasks() {
  const nav = useNavigate()
  const res = useRequest(api.gpuTasks)
  const [status, setStatus] = useState('全部')
  const [kind, setKind] = useState('全部')
  const [openId, setOpenId] = useState<string>()

  // 排队和生成中的任务状态会变，每 5 秒刷新一次
  const { reload } = res
  useEffect(() => {
    const t = setInterval(reload, 5000)
    return () => clearInterval(t)
  }, [reload])

  const tasks = res.data?.tasks
  const rows = useMemo(
    () => tasks?.filter((t) => (status === '全部' || t.status === status) && (kind === '全部' || KIND[t.kind] === kind)),
    [tasks, status, kind],
  )
  const open = tasks?.find((t) => t.id === openId)
  const s = res.data?.summary

  return (
    <>
      <PageHeader
        title="生成任务"
        sub="员工通过 agent 或接口提交的图片、视频任务。每个 GPU 节点同一时间只跑一个，其余在这里排队；成品可直接预览和下载。"
      />
      <div className="stack">
        <section className="panel kpi-strip">
          <div className="kpi"><div className="kpi-label">排队中</div><div className="kpi-value num" style={{ color: 'var(--amber)' }}>{s?.queued ?? '-'}</div></div>
          <div className="kpi"><div className="kpi-label">生成中</div><div className="kpi-value num" style={{ color: 'var(--blue)' }}>{s?.running ?? '-'}</div></div>
          <div className="kpi"><div className="kpi-label">今日完成</div><div className="kpi-value num" style={{ color: 'var(--green)' }}>{s?.done_today ?? '-'}</div></div>
          <div className="kpi"><div className="kpi-label">失败</div><div className="kpi-value num" style={{ color: 'var(--red)' }}>{s?.failed ?? '-'}</div></div>
        </section>

        <Panel
          tight
          title={<Seg value={status} onChange={setStatus} options={['全部', '排队中', '生成中', '已完成', '失败'].map((v) => ({ value: v, label: v }))} />}
          extra={<Seg value={kind} onChange={setKind} options={['全部', '图片', '视频'].map((v) => ({ value: v, label: v }))} />}
        >
          <Table<GpuTask>
            rowKey="id" loading={res.loading && !res.data} dataSource={rows} scroll={{ x: 900 }}
            locale={{ emptyText: <Empty>还没有生成任务</Empty> }}
            pagination={{ pageSize: 12, showSizeChanger: false, size: 'small' }}
            onRow={(t) => ({ onClick: () => setOpenId(t.id), style: { cursor: 'pointer' } })}
            columns={[
              { title: '提交时间', dataIndex: 'created_at', width: 110, render: (v) => <span className="mono muted">{fmtTime(v)}</span> },
              {
                title: '成员', dataIndex: 'member', width: 130, render: (v) => (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Avatar name={v} size={24} />
                    <span style={{ fontWeight: 500 }}>{v}</span>
                  </div>
                ),
              },
              { title: '类型', dataIndex: 'kind', width: 70, render: (v: GpuTask['kind']) => <Pill tone={v === 'video' ? 'violet' : 'blue'} dot={false}>{KIND[v]}</Pill> },
              {
                title: '内容', dataIndex: 'prompt', render: (v, t) => (
                  <div style={{ maxWidth: 360, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={v}>
                    {t.title || v}
                  </div>
                ),
              },
              {
                title: '状态', dataIndex: 'status', width: 150, render: (v: string, t) => (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    <Pill>{v}</Pill>
                    {v === '排队中' && t.ahead != null && <span className="muted num" style={{ fontSize: 11.5 }}>前面 {t.ahead} 个</span>}
                  </span>
                ),
              },
              { title: '节点', dataIndex: 'node_id', width: 80, render: (v) => <span className="mono muted">{v ?? '—'}</span> },
              { title: '耗时', dataIndex: 'run_seconds', width: 90, align: 'right', render: (v) => <span className="num">{secs(v)}</span> },
              {
                title: '成品', dataIndex: 'files', width: 120, render: (files: GpuTask['files'], t) => (
                  <div style={{ display: 'flex', gap: 4 }} onClick={(e) => e.stopPropagation()}>
                    {files.slice(0, 3).map((f, i) =>
                      f.type === 'image' ? (
                        <Image key={i} src={f.url} width={32} height={32} style={{ objectFit: 'cover', borderRadius: 6 }} />
                      ) : (
                        <CirclePlay key={i} style={{ fontSize: 28, color: 'var(--violet)', cursor: 'pointer' }} onClick={() => setOpenId(t.id)} />
                      ),
                    )}
                  </div>
                ),
              },
            ]}
          />
        </Panel>
      </div>

      <Drawer open={!!open} size={560} onClose={() => setOpenId(undefined)} title={open && <span className="mono">{open.id}</span>}>
        {open && (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
              <Avatar name={open.member} size={40} />
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 650, fontSize: 15 }}>{open.member}</div>
                <div className="muted" style={{ marginTop: 3 }}>
                  {KIND[open.kind]} · {open.size || '—'}{open.kind === 'image' ? ` · ${open.count} 张` : ''} · {fmtTime(open.created_at)}
                </div>
              </div>
              <Pill>{open.status}</Pill>
            </div>
            <div className="trace-card" style={{ whiteSpace: 'pre-wrap', marginBottom: 16 }}>{open.prompt}</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', border: '1px solid var(--line-2)', borderRadius: 10, marginBottom: 20 }}>
              {[['节点', open.node_id ?? '—'], ['排队等待', secs(open.wait_seconds)], ['生成耗时', secs(open.run_seconds)]].map(([k, v], i) => (
                <div key={k} style={{ padding: '10px 14px', borderLeft: i ? '1px solid var(--line-2)' : undefined }}>
                  <div className="muted" style={{ fontSize: 11.5 }}>{k}</div>
                  <div className="num" style={{ fontWeight: 650, fontSize: 15, marginTop: 2 }}>{v}</div>
                </div>
              ))}
            </div>
            {open.error && <div className="trace-card deny" style={{ marginBottom: 16 }}>{open.error}</div>}
            <Image.PreviewGroup>
              <div style={{ display: 'grid', gridTemplateColumns: open.kind === 'video' ? '1fr' : 'repeat(2, 1fr)', gap: 10 }}>
                {open.files.map((f, i) =>
                  f.type === 'video' ? (
                    <video key={i} src={f.url} controls style={{ width: '100%', borderRadius: 10, background: '#000' }} />
                  ) : (
                    <Image key={i} src={f.url} style={{ width: '100%', borderRadius: 10 }} />
                  ),
                )}
              </div>
            </Image.PreviewGroup>
            <div style={{ marginTop: 20 }}>
              <a onClick={() => nav(`/audit?trace=${encodeURIComponent(open.trace_id)}`)}>查看审计链路 {open.trace_id} →</a>
            </div>
          </>
        )}
      </Drawer>
    </>
  )
}
