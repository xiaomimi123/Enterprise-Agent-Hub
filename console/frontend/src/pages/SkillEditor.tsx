import { App, Button, Drawer, Empty, Input, Modal, Select, Skeleton } from 'antd'
import dayjs from 'dayjs'
import { useState } from 'react'
import { api, type SkillHistory, type SkillReview } from '../api'
import DiffView from '../components/DiffView'
import { useRequest } from '../lib'
import { Pill } from '../ui'

const STATUS_TONE: Record<string, string> = { published: 'green', pending: 'amber', rejected: 'red' }
const STATUS_TEXT: Record<string, string> = { published: '已发布', pending: '待审核', rejected: '已驳回' }
const TEMPLATE = `---
name: 技能名称
description: 一句话说明这个技能做什么、什么时候用
---

# 技能名称

## 什么时候用

## 步骤
1.
2.

## 注意事项
`

/** 编辑一个技能：本部门的直接生效，全公司的提交审核。 */
export function SkillEditor({ id, content, baseVersion, mode, onDone, onCancel }: {
  id: string; content: string; baseVersion: number; mode: 'direct' | 'review'; onDone: () => void; onCancel: () => void
}) {
  const { message, modal } = App.useApp()
  const [text, setText] = useState(content)
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const submit = async () => {
    setSaving(true)
    try {
      const r = await api.saveSkill(id, { content: text, note, base_version: baseVersion })
      message.success(r.status === 'published' ? `已保存为第 ${r.version} 版，立即生效（员工下次同步 / 读取技能时拿到新版本）` : `已提交审核（第 ${r.version} 版），老板或管理员通过后生效`)
      onDone()
    } catch (e) {
      modal.error({ title: '保存失败', content: (e as Error).message })
    } finally {
      setSaving(false)
    }
  }
  return (
    <div>
      <Input.TextArea value={text} onChange={(e) => setText(e.target.value)} autoSize={{ minRows: 18, maxRows: 34 }} className="mono"
        style={{ fontSize: 13, lineHeight: 1.65 }} spellCheck={false} />
      <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
        <Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={100} placeholder="这次改了什么（选填，方便以后查看历史）" style={{ flex: 1, minWidth: 220 }} />
        <Button onClick={onCancel}>取消</Button>
        <Button type="primary" loading={saving} disabled={text === content} onClick={submit}>{mode === 'direct' ? '保存并生效' : '提交审核'}</Button>
      </div>
      <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
        {mode === 'direct' ? '保存后立即对员工生效；每次保存都是新版本，可在「历史版本」里回滚。' : '这是全公司的技能，修改要经老板或管理员审核后才生效。'}
        开头的 <code>---</code> 部分必须有 name 和 description。
      </div>
    </div>
  )
}

/** 版本历史：看每个版本与当前版本的差异，一键回滚（回滚也是生成新版本）。 */
export function HistoryDrawer({ id, open, onClose, onChanged }: { id: string; open: boolean; onClose: () => void; onChanged: () => void }) {
  const { message, modal } = App.useApp()
  const { data, loading, reload } = useRequest(() => (open ? api.skillHistory(id) : Promise.resolve(undefined as SkillHistory | undefined)), [id, open])
  const [sel, setSel] = useState<number>()
  const current = data?.versions.find((v) => v.version === data.skill.published_version)
  const shown = data?.versions.find((v) => v.version === sel) ?? data?.versions[0]

  const rollback = (version: number) => modal.confirm({
    title: `回滚到第 ${version} 版？`,
    content: data?.mode === 'review' ? '会生成一个新版本并提交审核。' : '会用第 ' + version + ' 版的内容生成一个新版本并立即生效，原来的版本仍保留在历史里。',
    okText: '回滚', cancelText: '取消',
    onOk: async () => {
      try {
        const r = await api.rollbackSkill(id, version)
        message.success(r.status === 'published' ? `已回滚，新版本是第 ${r.version} 版` : '已提交审核')
        setSel(undefined)
        reload()
        onChanged()
      } catch (e) {
        message.error((e as Error).message)
      }
    },
  })

  return (
    <Drawer open={open} onClose={onClose} size={760} title={`历史版本 · ${data?.skill.name ?? id}`}>
      {loading && !data ? <Skeleton active /> : !data ? <Empty description="没有版本记录" /> : (
        <div style={{ display: 'grid', gridTemplateColumns: '230px 1fr', gap: 16 }}>
          <div className="stack" style={{ gap: 6 }}>
            {data.versions.map((v) => (
              <div key={v.version} onClick={() => setSel(v.version)} className="row-item clickable"
                style={{ display: 'block', padding: '8px 10px', borderRadius: 8, background: v.version === shown?.version ? 'var(--accent-soft)' : undefined }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                  <b className="num">第 {v.version} 版</b>
                  <Pill tone={STATUS_TONE[v.status]} dot={false}>{v.version === data.skill.published_version ? '当前生效' : STATUS_TEXT[v.status]}</Pill>
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
                  {shown.version === data.skill.published_version ? '这是当前生效的版本' : `第 ${shown.version} 版 与 当前生效版本（第 ${data.skill.published_version} 版）的差异`}
                  {shown.status === 'rejected' && shown.review_note && ` · 驳回原因：${shown.review_note}`}
                </span>
                {data.mode && shown.status === 'published' && shown.version !== data.skill.published_version && (
                  <Button size="small" onClick={() => rollback(shown.version)}>回滚到此版本</Button>
                )}
              </div>
              {shown.version === data.skill.published_version
                ? <pre className="mono" style={{ whiteSpace: 'pre-wrap', fontSize: 12.5, margin: 0 }}>{shown.content}</pre>
                : <DiffView before={current?.content ?? ''} after={shown.content} />}
            </div>
          )}
        </div>
      )}
    </Drawer>
  )
}

/** 待审核的修改：老板 / 管理员审核；主管看到自己提交的进度。 */
export function ReviewDrawer({ open, onClose, onChanged, canReview }: { open: boolean; onClose: () => void; onChanged: () => void; canReview: boolean }) {
  const { message } = App.useApp()
  const { data, loading, reload } = useRequest(() => (open ? api.skillReviews() : Promise.resolve([] as SkillReview[])), [open])
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [published, setPublished] = useState<Record<string, string>>({})

  const loadPublished = async (r: SkillReview) => {
    if (published[r.skill_id] !== undefined || !r.published_version) return
    try {
      const h = await api.skillHistory(r.skill_id)
      setPublished((p) => ({ ...p, [r.skill_id]: h.versions.find((v) => v.version === h.skill.published_version)?.content ?? '' }))
    } catch { /* 取不到就当作新技能显示全文 */ }
  }
  const act = async (r: SkillReview, approve: boolean) => {
    const key = `${r.skill_id}-${r.version}`
    if (!approve && !notes[key]?.trim()) { message.warning('驳回要写一下原因'); return }
    try {
      await api.reviewSkill(r.skill_id, r.version, approve, notes[key] ?? '')
      message.success(approve ? '已通过并生效' : '已驳回')
      reload()
      onChanged()
    } catch (e) {
      message.error((e as Error).message)
    }
  }
  return (
    <Drawer open={open} onClose={onClose} size={760} title={canReview ? '待审核的技能修改' : '我提交的待审核修改'}>
      {loading && !data ? <Skeleton active /> : !data?.length ? <Empty description="没有待审核的修改" /> : (
        <div className="stack" style={{ gap: 20 }}>
          {data.map((r) => {
            const key = `${r.skill_id}-${r.version}`
            return (
              <div key={key} className="panel" style={{ padding: 14 }} onMouseEnter={() => loadPublished(r)}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <b>{r.skill_name}</b>
                  <span className="muted" style={{ fontSize: 12 }}>{r.dept_name} · {r.author_name} · {dayjs(r.created_at).format('M/D HH:mm')}</span>
                </div>
                {r.note && <div style={{ margin: '4px 0 10px' }}>修改说明：{r.note}</div>}
                {r.published_version ? <DiffView before={published[r.skill_id] ?? ''} after={r.content} /> : <pre className="mono" style={{ whiteSpace: 'pre-wrap', fontSize: 12.5 }}>{r.content}</pre>}
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

/** 新建技能。新技能要加进岗位包后，员工的 agent 才会用到。 */
export function NewSkillModal({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: () => void }) {
  const { message, modal } = App.useApp()
  const depts = useRequest(() => (open ? api.departments() : Promise.resolve([])), [open])
  const [id, setId] = useState('')
  const [dept, setDept] = useState<string>()
  const [text, setText] = useState(TEMPLATE)
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    if (!dept) { message.warning('选一个部门'); return }
    setBusy(true)
    try {
      const r = await api.createSkill({ id: id.trim(), dept, content: text })
      modal.success({
        title: r.status === 'published' ? '技能已创建并生效' : '已提交审核',
        content: '新技能要由管理员在「岗位包」里加到对应岗位，员工的 agent 才会用到它。' + (r.status === 'pending' ? '全公司的技能需要老板或管理员审核通过后才生效。' : ''),
      })
      onCreated()
      onClose()
      setId('')
      setText(TEMPLATE)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open={open} onCancel={onClose} title="新建技能" okText="创建" cancelText="取消" onOk={submit} confirmLoading={busy} width={720}>
      <div className="stack" style={{ gap: 12 }}>
        <div style={{ display: 'flex', gap: 8 }}>
          <Input value={id} onChange={(e) => setId(e.target.value)} placeholder="技能 id，如 xhs-topic（小写字母、数字、短横线）" />
          <Select value={dept} onChange={setDept} placeholder="所属部门" style={{ width: 180 }}
            options={[{ value: 'all', label: '全公司（需审核）' }, ...(depts.data ?? []).filter((d) => d.id !== 'unassigned').map((d) => ({ value: d.id, label: d.name }))]} />
        </div>
        <Input.TextArea value={text} onChange={(e) => setText(e.target.value)} autoSize={{ minRows: 14, maxRows: 24 }} className="mono" style={{ fontSize: 13 }} spellCheck={false} />
      </div>
    </Modal>
  )
}
