import { Copy, Download } from 'lucide-react'
import { App, Button, Drawer, Form, Input, Modal, Select, Table, Upload } from 'antd'
import { useState } from 'react'
import { api, type Department as Dept, type ImportResult, type Member } from '../api'
import { copyText } from '../lib'
import { Pill } from '../ui'

const TEMPLATE = 'username,display_name,dept,title,phone,email,password\nzhangsan,张三,运营部,运营专员,13800000000,,\n'

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob(['﻿' + text], { type: 'text/csv;charset=utf-8' }))
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  a.click()
  URL.revokeObjectURL(url)
}

/** 创建 / 重置密码后展示初始密码，只显示这一次。 */
export function PasswordNotice({ info, onClose }: { info?: { id: string; name?: string; password: string }; onClose: () => void }) {
  const { message } = App.useApp()
  return (
    <Modal open={!!info} title="初始密码（只显示这一次）" onCancel={onClose} footer={<Button type="primary" onClick={onClose}>我已记下</Button>}>
      {info && (
        <>
          <p>请把账号和初始密码告诉 <b>{info.name || info.id}</b>。首次登录会要求修改密码，关闭后将无法再查看这个密码。</p>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', padding: 12, background: 'var(--bg-sunk, #f5f5f5)', borderRadius: 8 }}>
            <span className="mono" style={{ userSelect: 'all' }}>账号 {info.id}</span>
            <span className="mono" style={{ fontWeight: 700, userSelect: 'all' }}>密码 {info.password}</span>
            <Button size="small" icon={<Copy size={13} />} onClick={async () => ((await copyText(`账号：${info.id}\n初始密码：${info.password}`)) ? message.success('已复制') : message.error('复制失败，请手动选中密码复制'))}>复制</Button>
          </div>
        </>
      )}
    </Modal>
  )
}

/** 新建 / 编辑成员。 */
export function MemberDrawer({ target, depts, onClose, onDone }: {
  target: Member | 'new'
  depts: Dept[]
  onClose: () => void
  onDone: (created?: { id: string; name: string; password: string }) => void
}) {
  const isNew = target === 'new'
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const options = depts.filter((d) => d.id !== 'unassigned').map((d) => ({ value: d.id, label: d.name }))

  const save = async () => {
    const v = await form.validateFields()
    setSaving(true)
    try {
      if (isNew) {
        const out = await api.createMember({ username: v.username, display_name: v.display_name, dept: v.dept, title: v.title ?? '', phone: v.phone ?? '', email: v.email ?? '', password: v.password ?? '' })
        onDone({ id: out.id, name: out.name, password: out.initial_password })
      } else {
        await api.updateMember(target.id, { display_name: v.display_name, dept: v.dept, title: v.title ?? '', phone: v.phone ?? '', email: v.email ?? '' })
        message.success('已保存')
        onDone()
      }
      onClose()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Drawer open width={460} title={isNew ? '新建成员' : `编辑「${target.name}」`} onClose={onClose}
      footer={<div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}><Button onClick={onClose}>取消</Button><Button type="primary" loading={saving} onClick={save}>保存</Button></div>}>
      <Form form={form} layout="vertical"
        initialValues={isNew ? {} : { display_name: target.name, dept: target.dept, title: target.title, phone: target.phone, email: target.email }}>
        {isNew && (
          <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请填写用户名' }]} extra="登录用，小写字母、数字、点、下划线、短横线，2–31 位，创建后不能改">
            <Input placeholder="例如 zhangsan" autoComplete="off" />
          </Form.Item>
        )}
        <Form.Item name="display_name" label="姓名" rules={[{ required: true, message: '请填写姓名' }]}><Input /></Form.Item>
        <Form.Item name="dept" label="部门" rules={[{ required: true, message: '请选择部门' }]}><Select options={options} /></Form.Item>
        <Form.Item name="title" label="职位"><Input /></Form.Item>
        <Form.Item name="phone" label="手机"><Input /></Form.Item>
        <Form.Item name="email" label="邮箱"><Input /></Form.Item>
        {isNew && (
          <Form.Item name="password" label="初始密码（留空则随机生成）" extra="至少 8 位，同时包含字母和数字；员工首次登录必须修改">
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        )}
      </Form>
    </Drawer>
  )
}

/** CSV 批量导入。 */
export function ImportModal({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const { message } = App.useApp()
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<ImportResult>()

  const close = () => {
    if (result?.created) onDone()
    setText('')
    setResult(undefined)
    onClose()
  }
  const run = async () => {
    setBusy(true)
    try {
      setResult(await api.importMembers(text))
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const exportResult = () => {
    if (!result) return
    const lines = result.results.map((r) => [r.row, r.username, r.ok ? '成功' : '失败', r.initial_password ?? '', r.error ?? ''].join(','))
    download('导入结果.csv', ['行,用户名,结果,初始密码,原因', ...lines].join('\n'))
  }

  return (
    <Modal open={open} title="批量导入成员" width={720} onCancel={close} footer={null} destroyOnHidden>
      {!result ? (
        <>
          <div style={{ display: 'flex', gap: 8, marginBottom: 10, alignItems: 'center' }}>
            <Upload accept=".csv,text/csv" showUploadList={false} beforeUpload={(f) => { f.text().then(setText); return false }}>
              <Button>选择 CSV 文件</Button>
            </Upload>
            <Button icon={<Download size={14} />} onClick={() => download('成员导入模板.csv', TEMPLATE)}>下载模板</Button>
            <span className="muted" style={{ fontSize: 12 }}>表头：username,display_name,dept,title,phone,email,password；dept 填部门名称；password 留空则随机生成，一次最多 500 人</span>
          </div>
          <Input.TextArea rows={10} value={text} onChange={(e) => setText(e.target.value)} placeholder="也可以直接粘贴 CSV 内容（第一行是表头）" className="mono" />
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}>
            <Button onClick={close}>取消</Button>
            <Button type="primary" loading={busy} disabled={!text.trim()} onClick={run}>开始导入</Button>
          </div>
        </>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 10 }}>
            <Pill tone="green">成功 {result.created}</Pill>
            {result.failed > 0 && <Pill tone="red">失败 {result.failed}</Pill>}
            <span className="muted" style={{ fontSize: 12 }}>初始密码只在这里显示一次，请导出结果后发给员工；失败的行改好后可重新导入。</span>
          </div>
          <Table size="small" rowKey="row" dataSource={result.results} pagination={{ pageSize: 8, hideOnSinglePage: true, size: 'small' }}
            columns={[
              { title: '行', dataIndex: 'row', width: 56 },
              { title: '用户名', dataIndex: 'username' },
              { title: '结果', dataIndex: 'ok', width: 70, render: (ok) => (ok ? <Pill tone="green">成功</Pill> : <Pill tone="red">失败</Pill>) },
              { title: '初始密码 / 原因', render: (_, r) => (r.ok ? <span className="mono">{r.initial_password}</span> : <span className="muted">{r.error}</span>) },
            ]} />
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}>
            <Button icon={<Download size={14} />} onClick={exportResult}>导出结果</Button>
            <Button type="primary" onClick={close}>完成</Button>
          </div>
        </>
      )}
    </Modal>
  )
}
