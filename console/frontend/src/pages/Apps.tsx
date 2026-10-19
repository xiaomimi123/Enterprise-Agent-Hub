import { Table } from 'antd'
import { api, type PublishedApp } from '../api'
import { fmtTime, useRequest } from '../lib'
import { Empty, PageHeader, Panel, Pill, Token } from '../ui'

const size = (n: number) => (n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`)

export default function Apps() {
  const res = useRequest(api.apps)
  const rows = res.data

  return (
    <>
      <PageHeader
        title="应用"
        sub="在中枢统一发布、员工对 agent 说一句话就能在本机打开的工具。程序放在 apps/ 目录（zip + app.json），替换文件即发布新版；员工端每次打开都会校验 SHA-256，只执行这里发布的版本。"
      />
      <div className="stack">
        <Panel tight title="已发布的应用" sub="谁能打开由岗位包决定（岗位包 → 可打开的应用）">
          <Table<PublishedApp>
            rowKey="id" loading={res.loading && !res.data} dataSource={rows} pagination={false} scroll={{ x: 820 }}
            locale={{ emptyText: <Empty>还没有发布任何应用：把 zip 和 app.json 放进中枢的 apps/ 目录即可，说明见 apps/README.md</Empty> }}
            columns={[
              {
                title: '应用', dataIndex: 'name', render: (v, a) => (
                  <div style={{ lineHeight: 1.4 }}>
                    <div style={{ fontWeight: 600 }}>{v}</div>
                    <div className="muted" style={{ fontSize: 12 }}>{a.description || a.id}</div>
                  </div>
                ),
              },
              { title: '版本', dataIndex: 'version', width: 90, render: (v) => <span className="mono">v{v}</span> },
              {
                title: 'SHA-256', dataIndex: 'sha256', width: 160,
                render: (v: string, a) => <span className="mono muted" title={`${v}\n包大小 ${size(a.size)}`}>{v.slice(0, 12)}… · {size(a.size)}</span>,
              },
              {
                title: '可打开的岗位', dataIndex: 'allowed_packs', render: (v: PublishedApp['allowed_packs']) =>
                  v.length ? <div className="tagset">{v.map((p) => <Token key={p.id}>{p.name}</Token>)}</div> : <Pill tone="amber" dot={false}>没有岗位可打开</Pill>,
              },
              { title: '近 7 天打开', dataIndex: 'opens_7d', width: 100, align: 'right', render: (v) => <span className="num">{v}</span> },
              { title: '最近一次', dataIndex: 'last_open', width: 110, render: (v) => <span className="mono muted">{v ? fmtTime(v) : '—'}</span> },
            ]}
          />
        </Panel>
        <Panel title="员工怎么用">
          <div className="muted" style={{ lineHeight: 1.8 }}>
            员工的 agent 已通过 MCP 接入中枢，对它说「打开小红书工作台」即可：本机接入器先向中枢确认权限，再下载、校验并在本机启动，最后把浏览器网址交给员工。
            没有 Node.js 的电脑会收到按系统给出的安装指引；正在运行的旧版本不会被强制重启，只提示关闭后再打开即可升级。
          </div>
        </Panel>
      </div>
    </>
  )
}
