import { Drawer, Select, Skeleton, Table } from 'antd'
import dayjs from 'dayjs'
import { useState } from 'react'
import { api, type HealthCode, type HealthDevice, type HealthRate } from '../api'
import { useRequest } from '../lib'
import { Avatar, PageHeader, Panel, Pill, Seg } from '../ui'

const when = (t: string | null) => (t ? dayjs(t).format('MM-DD HH:mm') : '—')
const pct = (r: HealthRate) => (r.rate === null ? '—' : `${Math.round(r.rate * 100)}%`)
const top = (m: Record<string, number>) => Object.entries(m).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k} ×${v}`).join('、')

function Rate({ label, r }: { label: string; r: HealthRate }) {
  const bad = r.rate !== null && r.rate < 0.9
  return (
    <div className="kpi">
      <div className="kpi-label">{label}成功率</div>
      <div className="kpi-value num" style={{ color: bad ? 'var(--red)' : r.rate !== null ? 'var(--green)' : undefined }}>
        {pct(r)}<small> {r.ok} / {r.total}</small>
      </div>
    </div>
  )
}

export default function HealthPage() {
  const [days, setDays] = useState(7)
  const [app, setApp] = useState('')
  const [open, setOpen] = useState<HealthDevice>()
  const { data, loading } = useRequest(() => api.healthSummary(days, app), [days, app])
  if (loading || !data) return <Skeleton active paragraph={{ rows: 12 }} style={{ marginTop: 24 }} />
  const t = data.totals

  return (
    <>
      <PageHeader
        title="应用健康"
        sub="员工电脑上安装、登录、打开应用和运行的结果，由接入器自动回传（成功也记，才算得出成功率；报错原文已去掉用户名、令牌、邮箱等隐私）。只保留 7 天。员工可以设置 HUB_HEALTH=off 关闭。"
        extra={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Select
              size="small" style={{ width: 200 }} value={app} onChange={setApp}
              options={[{ value: '', label: '全部应用' }, ...(data.apps ?? []).map(([id, v]) => ({ value: `${id}@${v}`, label: `${id} ${v}` }))]}
            />
            <Seg value={days} onChange={setDays} options={[{ value: 1, label: '今天' }, { value: 3, label: '近 3 天' }, { value: 7, label: '近 7 天' }]} />
          </div>
        }
      />
      <div className="stack">
        <section className="panel kpi-strip">
          <Rate label="接入" r={t.install} />
          <Rate label="登录" r={t.login} />
          <Rate label="打开应用" r={t.launch} />
          <div className="kpi"><div className="kpi-label">出过错的人</div><div className="kpi-value num" style={{ color: t.fail_people ? 'var(--red)' : undefined }}>{t.fail_people}<small> / {t.people}</small></div></div>
          <div className="kpi"><div className="kpi-label">设备 / 事件</div><div className="kpi-value num">{t.devices}<small> 台 / {t.events} 条</small></div></div>
        </section>

        {t.events === 0 && (
          <div className="panel" style={{ padding: '14px 18px' }}>
            这段时间还没有收到任何事件。员工用新版接入器（0.5.0 起）接入、打开应用后，结果会自动出现在这里；断网时先记在员工本机，连上中枢后补报。
          </div>
        )}

        <Panel title="常见报错" sub="按次数排序；处理办法和员工本机看到的是同一句" tight>
          <Table<HealthCode>
            rowKey="code" dataSource={data.codes} pagination={false} scroll={{ x: 900 }} locale={{ emptyText: '没有报错' }}
            expandable={{
              expandedRowRender: (r) => (
                <div style={{ display: 'grid', gap: 6, fontSize: 13 }}>
                  <div><span className="muted">处理办法：</span>{r.fix}</div>
                  {r.sample && <div><span className="muted">报错原文示例：</span><span className="mono" style={{ fontSize: 12 }}>{r.sample}</span></div>}
                  <div><span className="muted">阶段：</span>{top(r.stages)}　<span className="muted">版本：</span>{top(r.versions)}</div>
                </div>
              ),
            }}
            columns={[
              { title: '错误', key: 'c', render: (_, r) => <div><span style={{ fontWeight: 500 }}>{r.label}</span> <span className="mono muted" style={{ fontSize: 11 }}>{r.code}</span></div> },
              { title: '次数', dataIndex: 'count', width: 70, align: 'right', render: (v) => <span className="num">{v}</span> },
              { title: '人 / 设备', key: 'p', width: 90, align: 'right', render: (_, r) => <span className="num">{r.people} / {r.devices}</span> },
              { title: '系统', key: 'os', render: (_, r) => <span className="muted" style={{ fontSize: 12 }}>{top(r.os)}</span> },
              { title: 'agent', key: 'ag', render: (_, r) => <span className="muted" style={{ fontSize: 12 }}>{top(r.agents)}</span> },
              { title: '最近一次', dataIndex: 'last_at', width: 110, render: (v) => <span className="num muted">{when(v)}</span> },
            ]}
          />
        </Panel>

        <Panel title="设备" sub="最近一次是失败、之后没再成功的排在前面；点一行看这台设备的时间线" tight>
          <Table<HealthDevice>
            rowKey={(r) => `${r.user_name}/${r.device_id}`} dataSource={data.devices} pagination={{ pageSize: 15, showSizeChanger: false, size: 'small' }}
            scroll={{ x: 980 }} locale={{ emptyText: '暂无设备' }} onRow={(r) => ({ onClick: () => setOpen(r), style: { cursor: 'pointer' } })}
            columns={[
              {
                title: '成员', dataIndex: 'display_name', render: (v, r) => (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Avatar name={v} size={24} /><span style={{ fontWeight: 500 }}>{v}</span>
                    <span className="mono muted" style={{ fontSize: 11 }}>{r.device_id.slice(0, 6)}</span>
                  </div>
                ),
              },
              { title: '状态', key: 's', width: 150, render: (_, r) => r.failing ? <Pill tone="red">{data.catalog[r.last_code]?.label ?? r.last_code}</Pill> : <Pill tone="green">正常</Pill> },
              { title: '系统', key: 'os', render: (_, r) => <span style={{ fontSize: 13 }}>{r.os} <span className="muted">{r.arch}</span></span> },
              { title: 'agent', dataIndex: 'agent', render: (v) => v || <span className="muted">—</span> },
              { title: '接入器 / 应用', key: 'v', render: (_, r) => <span className="mono" style={{ fontSize: 12 }}>{r.connector_version || '—'} · {r.app_version || '—'}</span> },
              { title: '最近成功', dataIndex: 'last_ok_at', width: 110, render: (v) => <span className="num muted">{when(v)}</span> },
              { title: '最近失败', dataIndex: 'last_fail_at', width: 110, render: (v) => <span className="num muted">{when(v)}</span> },
            ]}
          />
        </Panel>
      </div>
      {open && <DeviceDrawer d={open} days={days} onClose={() => setOpen(undefined)} />}
    </>
  )
}

function DeviceDrawer({ d, days, onClose }: { d: HealthDevice; days: number; onClose: () => void }) {
  const r = useRequest(() => api.healthDevice(d.user_name, d.device_id, days), [d.user_name, d.device_id, days])
  return (
    <Drawer open size={640} onClose={onClose} loading={r.loading} title={`${d.display_name} · ${d.os} · 设备 ${d.device_id.slice(0, 6)}`}>
      {(r.data?.events ?? []).map((e, i) => (
        <div key={i} style={{ padding: '10px 0', borderBottom: '1px solid var(--line-2)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span className="num muted" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>{dayjs(e.at).format('MM-DD HH:mm:ss')}</span>
            <span style={{ fontWeight: 500 }}>{e.stage_label}</span>
            {e.app_id && <span className="mono muted" style={{ fontSize: 11 }}>{e.app_id} {e.app_version}</span>}
            <span style={{ marginLeft: 'auto' }}>{e.ok ? <Pill tone="green">成功</Pill> : <Pill tone="red">{e.label}</Pill>}</span>
          </div>
          {!e.ok && (
            <div style={{ marginTop: 6, fontSize: 13, display: 'grid', gap: 4 }}>
              {e.message && <div className="mono" style={{ fontSize: 12 }}>{e.message}</div>}
              {e.fix && <div className="muted">处理办法：{e.fix}</div>}
            </div>
          )}
        </div>
      ))}
      {r.data && r.data.events.length === 0 && <div className="muted">没有事件</div>}
    </Drawer>
  )
}
