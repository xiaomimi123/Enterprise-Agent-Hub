import { App, Button, Checkbox, Empty, Input, Segmented, Skeleton } from 'antd'
import dayjs from 'dayjs'
import { useState } from 'react'
import Markdown from 'react-markdown'
import { api, type Proposal } from '../api'
import DiffView from '../components/DiffView'
import { useRequest } from '../lib'
import { PageHeader, Panel, Pill } from '../ui'

const KIND: Record<string, string> = { skill: '改技能', doc: '改文档', new_doc: '新增文档' }
const STATUS: Record<string, { text: string; tone: string }> = { open: { text: '待处理', tone: 'amber' }, accepted: { text: '已采纳', tone: 'green' }, rejected: { text: '已驳回', tone: 'red' } }

export default function ProposalsPage() {
  const [tab, setTab] = useState<'open' | 'closed'>('open')
  const list = useRequest(() => api.proposals(tab), [tab])
  const [sel, setSel] = useState<number>()
  const rows = list.data ?? []
  const current = rows.some((r) => r.id === sel) ? sel : rows[0]?.id

  return (
    <>
      <PageHeader
        title="改进建议"
        sub="员工的 agent 发现技能或知识库有错、过时、缺步骤时会提交修改建议。这里审核：采纳会生成新版本并生效，也可以改过之后再采纳。本部门内容的建议由部门主管处理，全公司内容的由老板和管理员处理。agent 不能直接修改任何内容。"
        extra={<Segmented value={tab} onChange={(v) => { setTab(v as 'open' | 'closed'); setSel(undefined) }} options={[{ value: 'open', label: '待处理' }, { value: 'closed', label: '已处理' }]} />}
      />
      <div className="split wide">
        <Panel tight title={`${tab === 'open' ? '待处理' : '已处理'}（${rows.length}）`}>
          {list.loading && !list.data ? <div style={{ padding: 18 }}><Skeleton active /></div> : !rows.length ? <Empty description={tab === 'open' ? '没有待处理的建议' : '还没有处理过的建议'} style={{ padding: 24 }} /> : (
            <div className="rows" style={{ maxHeight: 'calc(100vh - 230px)', overflow: 'auto' }}>
              {rows.map((r) => <Row key={r.id} r={r} active={r.id === current} onClick={() => setSel(r.id)} />)}
            </div>
          )}
        </Panel>
        {current ? <Detail key={current} id={current} onDone={() => { setSel(undefined); list.reload() }} /> : <Panel><Empty description="选择左侧的建议查看" /></Panel>}
      </div>
    </>
  )
}

function Row({ r, active, onClick }: { r: Proposal; active: boolean; onClick: () => void }) {
  return (
    <div className="row-item clickable" onClick={onClick} style={{ background: active ? 'var(--accent-soft)' : undefined, display: 'block', padding: '10px 14px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
        <span style={{ fontWeight: 600 }}>{r.summary}</span>
        {r.status !== 'open' && <Pill tone={STATUS[r.status].tone}>{STATUS[r.status].text}</Pill>}
      </div>
      <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
        {KIND[r.kind]} · {r.target_name}{r.kb_name ? ` · ${r.kb_name}` : ''} · {r.dept_name}
      </div>
      <div className="muted" style={{ fontSize: 12 }}>{r.proposer_name} · {dayjs(r.created_at).format('M/D HH:mm')}{r.stale && ' · 目标已被修改'}</div>
    </div>
  )
}

function Detail({ id, onDone }: { id: number; onDone: () => void }) {
  const { message, modal } = App.useApp()
  const d = useRequest(() => api.proposal(id), [id])
  const p = d.data
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState<string>()
  const [note, setNote] = useState('')
  const [confirmStale, setConfirmStale] = useState(false)
  const [busy, setBusy] = useState(false)
  if (!p) return <Panel><Skeleton active paragraph={{ rows: 8 }} /></Panel>
  const open = p.status === 'open'
  const mustEdit = open && !p.has_content // 建议没带新内容：审核人自己写
  const showEditor = open && (editing || mustEdit)

  const value = text ?? (p.proposed_content || p.current_content) // 没动过就用建议原文（没带内容的建议就从目标现在的内容开始改）
  const accept = async () => {
    setBusy(true)
    try {
      const r = await api.acceptProposal(id, { content: showEditor ? value : undefined, note, confirm_stale: confirmStale })
      message.success(`已采纳，生成第 ${r.version} 版并生效${r.synced === false ? '；检索索引同步失败，稍后在知识库页重试同步' : ''}`)
      onDone()
    } catch (e) {
      modal.error({ title: '采纳失败', content: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }
  const reject = async () => {
    if (!note.trim()) { message.warning('驳回要写一下原因，会反馈给提出建议的人'); return }
    try {
      await api.rejectProposal(id, note)
      message.success('已驳回')
      onDone()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  return (
    <Panel title={<span>{p.summary}</span>} extra={<Pill tone={STATUS[p.status].tone}>{STATUS[p.status].text}</Pill>}>
      <div className="muted" style={{ marginBottom: 12 }}>
        {KIND[p.kind]} · {p.target_name}{p.kb_name ? ` · ${p.kb_name}` : ''} · {p.dept_name} · 提出人 {p.proposer_name} · {dayjs(p.created_at).format('YYYY-M-D HH:mm')}
      </div>
      {p.rationale && <Section title="原因">{p.rationale}</Section>}
      {p.evidence && <Section title="依据">{p.evidence}</Section>}
      {p.stale && open && (
        <div className="panel" style={{ padding: '10px 14px', marginBottom: 12, borderColor: 'var(--amber)' }}>
          这条建议是基于第 {p.base_version} 版提出的，目标现在已经是第 {p.current_version} 版。下面的差异是和**最新内容**的对比，请确认后再采纳。
          <div style={{ marginTop: 6 }}><Checkbox checked={confirmStale} onChange={(e) => setConfirmStale(e.target.checked)}>我已对照最新内容确认</Checkbox></div>
        </div>
      )}
      {showEditor ? (
        <>
          <div className="muted" style={{ fontSize: 12.5, marginBottom: 6 }}>
            {mustEdit ? '这条建议没有带新内容，请在这里写出修改后的完整内容再采纳（下面是目标现在的内容）。' : '在建议的基础上修改，采纳时会用这里的内容。'}
          </div>
          <Input.TextArea value={value} onChange={(e) => setText(e.target.value)} autoSize={{ minRows: 14, maxRows: 30 }} className="mono" style={{ fontSize: 13 }} spellCheck={false} />
          {!mustEdit && <Button size="small" style={{ marginTop: 6 }} onClick={() => { setEditing(false); setText(undefined) }}>放弃修改，用建议原文</Button>}
        </>
      ) : p.has_content ? (
        <Section title={p.kind === 'new_doc' ? '建议新增的文档' : '建议的修改（与当前内容对比）'}>
          {p.kind === 'new_doc' ? <div className="skill-md"><Markdown>{p.proposed_content}</Markdown></div> : <DiffView before={p.current_content} after={p.proposed_content} />}
        </Section>
      ) : null}

      {open ? (
        <div style={{ display: 'flex', gap: 8, marginTop: 14, flexWrap: 'wrap' }}>
          <Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={100} placeholder="审核意见（驳回必填）" style={{ flex: 1, minWidth: 220 }} />
          {!editing && !mustEdit && <Button onClick={() => setEditing(true)}>修改后采纳</Button>}
          <Button danger onClick={reject}>驳回</Button>
          <Button type="primary" loading={busy} disabled={(p.stale && !confirmStale) || (showEditor && !value.trim())} onClick={accept}>采纳并生效</Button>
        </div>
      ) : (
        <div className="muted" style={{ marginTop: 14 }}>
          {p.status === 'accepted' ? `已采纳，生成第 ${p.result_version ?? ''} 版` : '已驳回'}（{p.reviewer}）{p.review_note && `：${p.review_note}`}
        </div>
      )}
    </Panel>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>{title}</div>
      <div style={{ whiteSpace: 'pre-wrap' }}>{children}</div>
    </div>
  )
}
