import { App, Form, Input, InputNumber, Modal, Select, Switch } from 'antd'
import { useEffect } from 'react'
import { api, type KbFields, type KnowledgeBase } from '../api'
import { useSession } from '../auth'
import { useRequest } from '../lib'

export const CATEGORIES = ['制度', '产品', '品牌', '案例素材', '话术', '合规', '其他']
export const CLASSIFICATIONS = ['公开', '内部', '机密']

/** 复核状态的简短文字：还剩几天 / 已逾期几天 / 不需要复核。 */
export function reviewText(k: Pick<KnowledgeBase, 'due_in_days' | 'review_every_days'>) {
  if (k.due_in_days === null) return '不需要复核'
  if (k.due_in_days < 0) return `已逾期 ${-k.due_in_days} 天`
  return `还剩 ${k.due_in_days} 天`
}

/** 新建知识库（管理员 / 老板）或修改知识库属性。部门主管只能改负责人、内容类型、复核周期和说明。 */
export function KbSettingsModal({ kb, open, onClose, onSaved }: { kb?: KnowledgeBase; open: boolean; onClose: () => void; onSaved: (k: KnowledgeBase) => void }) {
  const { message } = App.useApp()
  const role = useSession().user.role
  const full = role !== 'manager' // 管理员和老板：能改名称、部门、密级、是否开放外部
  const [form] = Form.useForm<KbFields>()
  const depts = useRequest(() => (open && full ? api.departments() : Promise.resolve([])), [open, full])
  const members = useRequest(() => (open ? api.members() : Promise.resolve([])), [open])

  useEffect(() => {
    if (open) form.setFieldsValue(kb ? { ...kb } : { category: '其他', review_every_days: 90, external_access: false, classification: '内部' })
  }, [open, kb, form])

  const submit = async () => {
    const v = await form.validateFields()
    try {
      const saved = kb ? await api.patchKb(kb.id, pick(v, full)) : await api.createKb(v as KbFields & { name: string; dept: string; classification: string })
      message.success(kb ? '已保存' : '知识库已创建。要让员工的 agent 检索到它，请管理员在「岗位包」里授权。')
      onSaved(saved)
      onClose()
    } catch (e) {
      message.error((e as Error).message)
    }
  }
  const confidential = Form.useWatch('classification', form) === '机密'

  return (
    <Modal open={open} onCancel={onClose} onOk={submit} okText="保存" cancelText="取消" title={kb ? `知识库设置 · ${kb.name}` : '新建知识库'} width={560} destroyOnHidden>
      <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
        {full && <Form.Item name="name" label="名称" rules={[{ required: true, message: '请填写名称' }, { max: 30 }]}><Input placeholder="如：新品卖点资料" /></Form.Item>}
        {full && (
          <div style={{ display: 'flex', gap: 12 }}>
            <Form.Item name="dept" label="所属部门" rules={[{ required: true, message: '请选择部门' }]} style={{ flex: 1 }}>
              <Select options={[{ value: 'all', label: '全公司' }, ...(depts.data ?? []).filter((d) => d.id !== 'unassigned').map((d) => ({ value: d.id, label: d.name }))]} />
            </Form.Item>
            <Form.Item name="classification" label="密级" rules={[{ required: true }]} style={{ width: 130 }}>
              <Select options={CLASSIFICATIONS.map((c) => ({ value: c, label: c }))} />
            </Form.Item>
          </div>
        )}
        <div style={{ display: 'flex', gap: 12 }}>
          <Form.Item name="category" label="内容类型" style={{ flex: 1 }}><Select options={CATEGORIES.map((c) => ({ value: c, label: c }))} /></Form.Item>
          <Form.Item name="review_every_days" label="复核周期（天，0 = 不需要）" style={{ flex: 1 }}><InputNumber min={0} max={3650} style={{ width: '100%' }} /></Form.Item>
        </div>
        <Form.Item name="owner" label="负责人" extra="负责人对内容准确性负责；逾期没复核会在列表和老板日报里提示。">
          <Select allowClear showSearch optionFilterProp="label" placeholder="选择负责人"
            options={(members.data ?? []).map((m) => ({ value: m.id, label: `${m.name}（${m.dept_name}）` }))} />
        </Form.Item>
        <Form.Item name="description" label="说明（选填）"><Input.TextArea rows={2} maxLength={200} placeholder="这个知识库里放什么、给谁用" /></Form.Item>
        {full && (
          <Form.Item name="external_access" label="开放给外部智能体（只读）" valuePropName="checked" extra={confidential ? '机密知识库不能开放给外部智能体。' : '密级和是否开放外部直接决定信息会不会外泄，只有管理员和老板能改。'}>
            <Switch disabled={confidential} />
          </Form.Item>
        )}
      </Form>
    </Modal>
  )
}

function pick(v: KbFields, full: boolean): KbFields {
  const keys: (keyof KbFields)[] = full ? ['name', 'dept', 'classification', 'external_access', 'category', 'owner', 'review_every_days', 'description']
    : ['category', 'owner', 'review_every_days', 'description']
  const out: KbFields = {}
  for (const k of keys) if (v[k] !== undefined) (out as Record<string, unknown>)[k] = k === 'owner' ? (v[k] ?? '') : v[k]
  return out
}
