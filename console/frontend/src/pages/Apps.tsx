import { Table, Tabs } from 'antd'
import { Link } from 'react-router-dom'
import { api, type PublishedApp } from '../api'
import { fmtTime, useRequest } from '../lib'
import { Empty, PageHeader, Panel, Pill, Token } from '../ui'

const size = (n: number) => (n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`)

/** app.json 的 requires 翻成管理员看得懂的话 */
export function describeRequires(r: PublishedApp['requires']): string[] {
  const out: string[] = []
  if (r.node) out.push(`Node.js ${String(r.node)}`)
  if (r.agent_cli === 'codebuddy') out.push('CodeBuddy CLI（员工要在自己的终端登录一次）')
  const caps = Array.isArray(r.capabilities) ? r.capabilities : []
  if (caps.includes('browser')) out.push('能控制浏览器（WorkBuddy 浏览器插件，或系统浏览器 + Playwright）')
  if (r.base_min) out.push(`安装底座 ≥ ${String(r.base_min)}（过旧只提示重新运行安装命令，不拦打开）`)
  return out
}

function List({ items }: { items: string[] }) {
  return <ul className="app-guide-list">{items.map((t, i) => <li key={i}>{t}</li>)}</ul>
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="stack-sm">
      <div style={{ fontWeight: 600 }}>{title}</div>
      {children}
    </div>
  )
}

/** 一个应用的接入说明；没有 guide.json 时只显示从 app.json 自动得到的部分，并提示补上 */
function AppGuideView({ app }: { app: PublishedApp }) {
  const g = app.guide
  const needs = describeRequires(app.requires)
  return (
    <div className="stack" data-testid={`guide-${app.id}`}>
      <div className="stack-sm">
        <div>{g?.summary || app.description || app.id}</div>
        <div className="tagset">
          {(g?.audience ?? []).map((a) => <Token key={a}>{a}</Token>)}
          <Pill tone="gray" dot={false}>v{app.version}</Pill>
          {app.auto_upgrade && <Pill tone="green" dot={false}>双击图标自动升级</Pill>}
        </div>
      </div>
      {!g && (
        <div className="muted">
          这个应用还没有接入说明。在 <span className="mono">apps/{app.id}/guide.json</span> 里补上（给谁用、怎么打开、员工首次要做什么、限制、常见问题），
          这里就会显示；写法见 <span className="mono">docs/app-integration-guide.md</span>「接入说明」。
        </div>
      )}
      {g?.open && <Section title="怎么打开"><div>{g.open}</div></Section>}
      {needs.length > 0 && (
        <Section title="需要的环境（打开时自动预检，缺什么只拦对应功能）">
          <List items={needs} />
          <div className="muted" style={{ fontSize: 12 }}>
            一键安装脚本会准备 Node.js 并询问是否安装 CodeBuddy CLI，详见<Link to="/connect">「接入方式」</Link>。
          </div>
        </Section>
      )}
      {g && g.employee_steps.length > 0 && (
        <Section title="员工首次使用要做的事">
          <div className="stack-sm">
            {g.employee_steps.map((s, i) => (
              <div key={i}><Pill tone="accent" dot={false}>{i + 1}</Pill> <b>{s.title}</b>：{s.body}</div>
            ))}
          </div>
        </Section>
      )}
      {g && g.admin_notes.length > 0 && <Section title="管理员须知"><List items={g.admin_notes} /></Section>}
      {g && g.limits.length > 0 && <Section title="限制与红线"><List items={g.limits} /></Section>}
      {g && g.faq.length > 0 && (
        <Section title="常见问题">
          <div className="stack-sm">{g.faq.map((f, i) => <div key={i}><b>{f.q}</b>：{f.a}</div>)}</div>
        </Section>
      )}
      {g && g.docs.length > 0 && (
        <Section title="相关文档（仓库内）">
          <List items={g.docs.map((d) => `${d.title}：${d.path}`)} />
        </Section>
      )}
    </div>
  )
}

export default function Apps() {
  const res = useRequest(api.apps)
  const rows = res.data

  return (
    <>
      <PageHeader
        title="应用"
        sub="在中枢统一发布、员工对 agent 说一句话就能在本机打开的工具。每个岗位的应用各自一份接入说明（给谁用、怎么打开、员工首次要做什么），中枢本身怎么接入见「接入方式」。程序放在 apps/ 目录（zip + app.json），替换文件即发布新版；员工端每次打开都会校验 SHA-256，只执行这里发布的版本。"
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
        {rows && rows.length > 0 && (
          <Panel title="接入说明" sub="按应用分开：员工要做什么、管理员要注意什么、已知限制。说明在 apps/<应用 id>/guide.json，改说明不用升版本号">
            <Tabs items={rows.map((a) => ({ key: a.id, label: a.name, children: <AppGuideView app={a} /> }))} />
          </Panel>
        )}
        <Panel title="员工怎么用">
          <div className="muted" style={{ lineHeight: 1.8 }}>
            员工的 agent 已通过 MCP 接入中枢，对它说「打开小红书工作台」这类话即可：本机接入器先向中枢确认权限，再下载、校验并在本机启动，最后把浏览器网址交给员工。
            没有 Node.js 的电脑会收到按系统给出的安装指引；声明了自动升级的应用，员工双击桌面图标就会升级到新版（旧版本空闲才停，有任务在跑不会打断）。
          </div>
        </Panel>
      </div>
    </>
  )
}
