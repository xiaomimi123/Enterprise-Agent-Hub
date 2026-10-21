import { App, Button, Drawer, Empty, Input, Modal, Popconfirm, Segmented, Skeleton, Table } from 'antd'
import dayjs from 'dayjs'
import { FileText, Pencil, Plus, RefreshCw, Settings, Trash2 } from 'lucide-react'
import { useState } from 'react'
import Markdown from 'react-markdown'
import { api, type KbDocDetail, type KbDocument, type KbResult, type KbReview, type KnowledgeBase } from '../api'
import { useSession } from '../auth'
import DiffView from '../components/DiffView'
import { DEPT_META, fmtTime, useRequest } from '../lib'
import { DeptTile, Pill, Token } from '../ui'
import { KbSettingsModal, reviewText } from './KbSettings'

type Mode = 'direct' | 'review' | null
const STATUS_TONE: Record<string, string> = { published: 'green', pending: 'amber', rejected: 'red' }
const STATUS_TEXT: Record<string, string> = { published: '已发布', pending: '待审核', rejected: '已驳回' }

/** 当前登录的人改这个知识库：直接生效 / 提交审核 / 不能改（与服务端 plan_for 一致，服务端为准）。 */
export function usePlan(dept: string): Mode {
  const u = useSession().user
  if (u.role === 'admin' || u.role === 'boss') return 'direct'
  if (u.role === 'manager') return u.depts?.includes(dept) ? 'direct' : dept === 'all' ? 'review' : null
  return null
}

function resultText(r: KbResult, what: string) {
  const sync = r.synced === false ? '；但检索索引同步失败，稍后在文档列表里点「重试同步」' : ''
  return r.status === 'published' ? `${what}成功，已生效（第 ${r.version} 版）${sync}` : `已提交审核（第 ${r.version} 版），老板或管理员通过后生效`
}

export function DocsDrawer({ kb, onClose, onChanged }: { kb: KnowledgeBase; onClose: () => void; onChanged: () => void }) {
  const { message } = App.useApp()
  const docs = useRequest(() => api.kbDocuments(kb.id), [kb.id])
  const deleted = useRequest(() => api.kbDeleted(kb.id).catch(() => []), [kb.id])
  const mode = usePlan(kb.dept)
  const canReview = useSession().user.role !== 'manager'
  const [open, setOpen] = useState<string>()
  const [creating, setCreating] = useState(false)
  const [reviewing, setReviewing] = useState(false)
  const [settings, setSettings] = useState(false)
  const session = useSession().user
  const canMark = session.role !== 'manager' || (kb.dept !== 'all' && !!session.depts?.includes(kb.dept)) || kb.owner === session.name
  const canSettings = session.role !== 'manager' || (kb.dept !== 'all' && !!session.depts?.includes(kb.dept))
  const reloadAll = () => { docs.reload(); deleted.reload(); onChanged() }
  const unsynced = docs.data?.some((d) => d.status === '待同步')
  const pending = docs.data?.reduce((n, d) => n + (d.pending ?? 0), 0) ?? 0

  return (
    <Drawer
      open size={760} onClose={onClose}
      title={
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <DeptTile dept={kb.dept} size={32} />
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>{kb.name}<Pill>{kb.classification}</Pill></div>
            <div className="muted" style={{ fontSize: 12, fontWeight: 400 }}>{kb.dept_name} · {mode === 'direct' ? '你可以直接编辑' : mode === 'review' ? '你的修改需要审核后生效' : '只读'}</div>
          </div>
        </div>
      }
      extra={<div style={{ display: 'flex', gap: 8 }}>
        {canSettings && <Button icon={<Settings size={13} />} onClick={() => setSettings(true)}>库设置</Button>}
        {unsynced && mode && <Button icon={<RefreshCw size={13} />} onClick={async () => {
          const r = await api.resyncKb(kb.id)
          message[r.failed ? 'warning' : 'success'](r.failed ? `${r.failed} 篇同步失败` : `已同步 ${r.synced} 篇`)
          reloadAll()
        }}>重试同步</Button>}
        <Button onClick={() => setReviewing(true)}>{canReview ? '待审核' : '我提交的审核'}{pending ? `（${pending}）` : ''}</Button>
        {mode && <Button type="primary" icon={<Plus size={14} />} onClick={() => setCreating(true)}>新建文档</Button>}
      </div>}
    >
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', marginBottom: 12 }}>
        <Pill tone="gray" dot={false}>{kb.category}</Pill>
        <span className="muted">负责人：{kb.owner_name || '未指定'}</span>
        <span style={{ color: kb.overdue ? 'var(--red)' : undefined, fontWeight: kb.overdue ? 600 : undefined }} className={kb.overdue ? '' : 'muted'}>复核：{reviewText(kb)}</span>
        {canMark && kb.review_every_days > 0 && (
          <Button size="small" onClick={async () => {
            try { await api.kbReviewed(kb.id); message.success('已标记为已复核'); onChanged() } catch (e) { message.error((e as Error).message) }
          }}>标记已复核</Button>
        )}
      </div>
      {kb.description && <div className="muted" style={{ marginBottom: 12 }}>{kb.description}</div>}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 16 }}>
        <span className="muted">授权给</span>
        {kb.role_packs.length ? kb.role_packs.map((x) => <Token key={x}>{x}</Token>) : <span className="muted">无</span>}
      </div>
      <Table<KbDocument>
        rowKey="id" size="small" loading={docs.loading} dataSource={docs.data} pagination={false} locale={{ emptyText: '这个知识库里还没有文档' }}
        onRow={(d) => ({ onClick: () => setOpen(d.id), style: { cursor: 'pointer' } })}
        columns={[
          {
            title: '文档', dataIndex: 'title', render: (v, d) => (
              <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
                <FileText style={{ color: DEPT_META[kb.dept]?.color }} />{v}
                {!!d.pending && <Pill tone="amber" dot={false}>待审核</Pill>}
              </span>
            ),
          },
          { title: '版本', dataIndex: 'version', width: 60, align: 'right', render: (v) => <span className="num">{v}</span> },
          { title: '片段', dataIndex: 'chunks', width: 60, align: 'right', render: (v) => <span className="num">{v}</span> },
          { title: '状态', dataIndex: 'status', width: 90, render: (v) => <Pill>{v}</Pill> },
          { title: '更新', dataIndex: 'updated_at', width: 100, render: (v) => <span className="muted num">{fmtTime(v)}</span> },
        ]}
      />
      {!!deleted.data?.length && (
        <div style={{ marginTop: 20 }}>
          <div className="muted" style={{ fontSize: 12.5, marginBottom: 6 }}>已删除的文档（点开可在历史里找回）</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>{deleted.data.map((d) => <Token key={d.name}><span style={{ cursor: 'pointer' }} onClick={() => setOpen(d.name)}>{d.name}</span></Token>)}</div>
        </div>
      )}
      <KbSettingsModal kb={kb} open={settings} onClose={() => setSettings(false)} onSaved={() => onChanged()} />
      {open && <DocDrawer kb={kb} name={open} onClose={() => setOpen(undefined)} onChanged={reloadAll} />}
      <NewDocModal kb={kb} open={creating} onClose={() => setCreating(false)} onCreated={(name) => { reloadAll(); setOpen(name) }} />
      <KbReviewDrawer open={reviewing} onClose={() => setReviewing(false)} onChanged={reloadAll} canReview={canReview} kbId={kb.id} />
    </Drawer>
  )
}

function DocDrawer({ kb, name, onClose, onChanged }: { kb: KnowledgeBase; name: string; onClose: () => void; onChanged: () => void }) {
  const { message, modal } = App.useApp()
  const doc = useRequest(() => api.kbDocument(kb.id, name), [kb.id, name])
  const [view, setView] = useState<'content' | 'history'>('content')
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState('')
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [sel, setSel] = useState<number>()
  const d = doc.data
  const done = () => { setEditing(false); doc.reload(); onChanged() }

  const save = async () => {
    if (!d) return
    setSaving(true)
    try {
      const r = await api.saveKbDoc(kb.id, name, { content: text, note, base_version: d.published_version })
      message.success(resultText(r, '保存'))
      setNote('')
      done()
    } catch (e) {
      modal.error({ title: '保存失败', content: (e as Error).message })
    } finally {
      setSaving(false)
    }
  }
  const remove = async () => {
    try {
      const r = await api.deleteKbDoc(kb.id, name)
      message.success(resultText(r, '删除'))
      if (r.status === 'published') { onChanged(); onClose() } else done()
    } catch (e) {
      message.error((e as Error).message)
    }
  }
  const rollback = (version: number) => modal.confirm({
    title: d?.deleted ? `找回文档（用第 ${version} 版的内容）？` : `回滚到第 ${version} 版？`,
    content: '会用这个版本的内容生成一个新版本，原来的版本仍保留在历史里。', okText: '确定', cancelText: '取消',
    onOk: async () => {
      try {
        const r = await api.rollbackKbDoc(kb.id, name, version)
        message.success(resultText(r, '回滚'))
        setSel(undefined)
        done()
      } catch (e) {
        message.error((e as Error).message)
      }
    },
  })

  const current = d?.versions.find((v) => v.version === d.published_version)
  const shown = d?.versions.find((v) => v.version === sel) ?? d?.versions[0]
  return (
    <Drawer open size={820} onClose={onClose} title={<span>{name}{d?.deleted && <Pill tone="red" dot={false}>已删除</Pill>}</span>}
      extra={d && <div style={{ display: 'flex', gap: 8 }}>
        <Segmented value={view} onChange={(v) => setView(v as 'content' | 'history')} options={[{ value: 'content', label: '内容' }, { value: 'history', label: '历史版本' }]} />
        {d.mode && !d.deleted && view === 'content' && !editing && (
          <Button type="primary" icon={<Pencil size={13} />} onClick={() => { setText(d.content); setEditing(true) }}>{d.mode === 'direct' ? '编辑' : '编辑（提交审核）'}</Button>
        )}
        {d.mode && !d.deleted && (
          <Popconfirm title={`删除文档「${name}」？`} description={d.mode === 'direct' ? '会立即从检索里去掉，可以在历史里找回。' : '删除要提交审核。'} okText="删除" cancelText="取消" onConfirm={remove}>
            <Button danger icon={<Trash2 size={13} />}>删除</Button>
          </Popconfirm>
        )}
      </div>}>
      {doc.loading && !d ? <Skeleton active paragraph={{ rows: 10 }} /> : !d ? <Empty description="文档不存在" /> : view === 'content' ? (
        editing ? (
          <div>
            <Input.TextArea value={text} onChange={(e) => setText(e.target.value)} autoSize={{ minRows: 18, maxRows: 34 }} className="mono" style={{ fontSize: 13, lineHeight: 1.65 }} spellCheck={false} />
            <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
              <Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={100} placeholder="这次改了什么（选填）" style={{ flex: 1, minWidth: 220 }} />
              <Button onClick={() => setEditing(false)}>取消</Button>
              <Button type="primary" loading={saving} disabled={text === d.content} onClick={save}>{d.mode === 'direct' ? '保存并生效' : '提交审核'}</Button>
            </div>
            <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
              {d.mode === 'direct' ? '保存后立即生效并同步到检索索引（员工的 agent 马上查到新内容）；每次保存都是新版本，可在「历史版本」里回滚。' : '这是全公司的知识库，修改要经老板或管理员审核后才生效。'}
            </div>
          </div>
        ) : d.deleted ? <Empty description="这篇文档已删除。到「历史版本」里选一个版本可以找回。" /> : (
          <div className="skill-md"><Markdown>{d.content}</Markdown></div>
        )
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '230px 1fr', gap: 16 }}>
          <div className="stack" style={{ gap: 6 }}>
            {d.versions.map((v) => (
              <div key={v.version} onClick={() => setSel(v.version)} className="row-item clickable"
                style={{ display: 'block', padding: '8px 10px', borderRadius: 8, background: v.version === shown?.version ? 'var(--accent-soft)' : undefined }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                  <b className="num">第 {v.version} 版</b>
                  <Pill tone={STATUS_TONE[v.status]} dot={false}>{v.version === d.published_version && !d.deleted ? '当前生效' : v.is_delete ? '删除' : STATUS_TEXT[v.status]}</Pill>
                </div>
                <div className="muted" style={{ fontSize: 12 }}>{v.author_name} · {dayjs(v.created_at).format('M/D HH:mm')}</div>
                {v.note && <div style={{ fontSize: 12 }}>{v.note}</div>}
              </div>
            ))}
          </div>
          {shown && (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                <span className="muted" style={{ fontSize: 12.5 }}>
                  {shown.version === d.published_version && !d.deleted ? '这是当前生效的版本' : `第 ${shown.version} 版 与 当前生效版本的差异`}
                  {shown.status === 'rejected' && shown.review_note && ` · 驳回原因：${shown.review_note}`}
                </span>
                {d.mode && shown.status === 'published' && !shown.is_delete && (d.deleted || shown.version !== d.published_version) && (
                  <Button size="small" onClick={() => rollback(shown.version)}>{d.deleted ? '找回（用这一版）' : '回滚到此版本'}</Button>
                )}
              </div>
              {shown.version === d.published_version && !d.deleted
                ? <pre className="mono" style={{ whiteSpace: 'pre-wrap', fontSize: 12.5, margin: 0 }}>{shown.content}</pre>
                : <DiffView before={d.deleted ? '' : current?.content ?? ''} after={shown.content} />}
            </div>
          )}
        </div>
      )}
    </Drawer>
  )
}

function NewDocModal({ kb, open, onClose, onCreated }: { kb: KnowledgeBase; open: boolean; onClose: () => void; onCreated: (name: string) => void }) {
  const { message, modal } = App.useApp()
  const [name, setName] = useState('')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    setBusy(true)
    try {
      const r = await api.createKbDoc(kb.id, { name, content: text })
      const n = name.trim().replace(/\.md$/i, '')
      message.success(resultText(r, '新建'))
      setName('')
      setText('')
      onClose()
      if (r.status === 'published') onCreated(n)
      else onCreated('')
    } catch (e) {
      modal.error({ title: '新建失败', content: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open={open} onCancel={onClose} title={`新建文档 · ${kb.name}`} okText="创建" cancelText="取消" onOk={submit} confirmLoading={busy} width={720} okButtonProps={{ disabled: !name.trim() || !text.trim() }}>
      <div className="stack" style={{ gap: 12 }}>
        <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={60} placeholder="文档名，如：2026 秋冬品牌主张" />
        <Input.TextArea value={text} onChange={(e) => setText(e.target.value)} autoSize={{ minRows: 14, maxRows: 24 }} className="mono" style={{ fontSize: 13 }} spellCheck={false}
          placeholder={'用 Markdown 写，如：\n# 标题\n\n正文……\n\n段落之间空一行，检索时会按段落切片。'} />
      </div>
    </Modal>
  )
}

function KbReviewDrawer({ open, onClose, onChanged, canReview, kbId }: { open: boolean; onClose: () => void; onChanged: () => void; canReview: boolean; kbId: string }) {
  const { message } = App.useApp()
  const { data, loading, reload } = useRequest(() => (open ? api.kbReviews() : Promise.resolve([] as KbReview[])), [open])
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [published, setPublished] = useState<Record<string, string>>({})
  const rows = (data ?? []).filter((r) => r.kb_id === kbId)

  const loadPublished = async (r: KbReview) => {
    const key = `${r.kb_id}/${r.name}`
    if (published[key] !== undefined || !r.published_version) return
    try {
      const h: KbDocDetail = await api.kbDocument(r.kb_id, r.name)
      setPublished((p) => ({ ...p, [key]: h.content }))
    } catch { /* 取不到就显示全文 */ }
  }
  const act = async (r: KbReview, approve: boolean) => {
    const key = `${r.kb_id}/${r.name}/${r.version}`
    if (!approve && !notes[key]?.trim()) { message.warning('驳回要写一下原因'); return }
    try {
      await api.reviewKbDoc(r.kb_id, r.name, r.version, approve, notes[key] ?? '')
      message.success(approve ? '已通过并生效' : '已驳回')
      reload()
      onChanged()
    } catch (e) {
      message.error((e as Error).message)
    }
  }
  return (
    <Drawer open={open} onClose={onClose} size={760} title={canReview ? '待审核的文档修改' : '我提交的待审核修改'}>
      {loading && !data ? <Skeleton active /> : !rows.length ? <Empty description="没有待审核的修改" /> : (
        <div className="stack" style={{ gap: 20 }}>
          {rows.map((r) => {
            const key = `${r.kb_id}/${r.name}/${r.version}`
            return (
              <div key={key} className="panel" style={{ padding: 14 }} onMouseEnter={() => loadPublished(r)}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <b>{r.name}{r.is_delete && <Pill tone="red" dot={false}>申请删除</Pill>}</b>
                  <span className="muted" style={{ fontSize: 12 }}>{r.author_name} · {dayjs(r.created_at).format('M/D HH:mm')}</span>
                </div>
                {r.note && <div style={{ margin: '4px 0 10px' }}>修改说明：{r.note}</div>}
                {r.is_delete ? <div className="muted">申请删除这篇文档。</div>
                  : r.published_version ? <DiffView before={published[`${r.kb_id}/${r.name}`] ?? ''} after={r.content} />
                    : <pre className="mono" style={{ whiteSpace: 'pre-wrap', fontSize: 12.5 }}>{r.content}</pre>}
                {canReview ? (
                  <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                    <Input value={notes[key] ?? ''} onChange={(e) => setNotes((n) => ({ ...n, [key]: e.target.value }))} placeholder="审核意见（驳回必填）" maxLength={100} />
                    <Button danger onClick={() => act(r, false)}>驳回</Button>
                    <Button type="primary" onClick={() => act(r, true)}>通过并生效</Button>
                  </div>
                ) : <div className="muted" style={{ marginTop: 8 }}>等待老板或管理员审核</div>}
              </div>
            )
          })}
        </div>
      )}
    </Drawer>
  )
}

