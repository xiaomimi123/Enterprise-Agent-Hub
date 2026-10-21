import { Cpu, ImageIcon, Plus } from 'lucide-react'
import { App, Button, Drawer, Form, Input, InputNumber, Popconfirm, Select, Switch, Table } from 'antd'
import { useState } from 'react'
import { api, type H3Gateway, type ImageProvider, type ModelPrice, type Upstream } from '../api'
import { useRequest } from '../lib'
import { Empty, PageHeader, Panel, Pill, Seg, Token } from '../ui'

export default function Models() {
  return (
    <>
      <PageHeader
        title="模型"
        sub="在这里接入对话大模型和第三方出图 API，不用再打开 New API 后台。开放的对话模型会出现在「岗位包 → 可用模型」里；出图通道决定员工出图走本机 GPU 还是第三方。密钥只保存、不回显，页面只显示后四位。"
      />
      <div className="stack">
        <Upstreams />
        <Pricing />
        <ImageChannel />
        <H3Channel />
      </div>
    </>
  )
}

/* ---------------- 对话模型 ---------------- */

function Upstreams() {
  const list = useRequest(api.upstreams)
  const { message } = App.useApp()
  const [editing, setEditing] = useState<Upstream | 'new'>()

  const toggle = async (u: Upstream, enabled: boolean) => {
    try {
      await api.patchUpstream(u.id, { enabled })
      list.reload()
    } catch (e) {
      message.error((e as Error).message)
    }
  }
  const remove = async (u: Upstream) => {
    try {
      await api.deleteUpstream(u.id)
      message.success('已删除')
      list.reload()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  return (
    <Panel
      tight
      title={<span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}><Cpu size={16} />对话模型上游</span>}
      sub="DeepSeek、中转平台等 OpenAI 兼容的接口（地址形如 https://xxx/v1）"
      extra={<Button type="primary" icon={<Plus size={14} />} onClick={() => setEditing('new')}>添加上游</Button>}
    >
      {list.error && <div className="muted" style={{ padding: 16 }}>{list.error}</div>}
      <Table<Upstream>
        rowKey="id" loading={list.loading && !list.data} dataSource={list.data} pagination={false} scroll={{ x: 760 }}
        locale={{ emptyText: <Empty>还没有接入任何上游，点右上角「添加上游」</Empty> }}
        columns={[
          { title: '名称', dataIndex: 'name', width: 160, render: (v) => <b>{v}</b> },
          { title: '地址', dataIndex: 'base_url', render: (v) => <span className="mono muted">{v}</span> },
          { title: '开放的模型', dataIndex: 'models', render: (v: string[]) => <div className="tagset">{v.map((m) => <Token key={m}>{m}</Token>)}</div> },
          { title: '密钥', dataIndex: 'key_hint', width: 100, render: (v) => <span className="mono muted">{v || '—'}</span> },
          { title: '启用', dataIndex: 'status', width: 70, render: (v, u) => <Switch size="small" checked={v === 'enabled'} onChange={(c) => toggle(u, c)} /> },
          {
            title: '', width: 110, render: (_, u) => (
              <span style={{ display: 'inline-flex', gap: 4 }}>
                <Button size="small" type="text" onClick={() => setEditing(u)}>编辑</Button>
                <Popconfirm title={`删除上游「${u.name}」？`} description="员工之后将不能再使用它提供的模型。" okText="删除" cancelText="取消" onConfirm={() => remove(u)}>
                  <Button size="small" type="text" danger>删除</Button>
                </Popconfirm>
              </span>
            ),
          },
        ]}
      />
      {editing && <UpstreamDrawer target={editing} onClose={() => setEditing(undefined)} onSaved={list.reload} />}
    </Panel>
  )
}

function UpstreamDrawer({ target, onClose, onSaved }: { target: Upstream | 'new'; onClose: () => void; onSaved: () => void }) {
  const isNew = target === 'new'
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [candidates, setCandidates] = useState<string[]>(isNew ? [] : target.models)
  const [probing, setProbing] = useState(false)
  const [saving, setSaving] = useState(false)

  const probe = async () => {
    const { base_url, key } = form.getFieldsValue()
    if (!base_url || !key) return message.warning('先填写地址和密钥')
    setProbing(true)
    try {
      const r = await api.probeUpstream({ base_url, key })
      setCandidates(r.models)
      form.setFieldValue('models', r.models.filter((m) => (form.getFieldValue('models') ?? []).includes(m)).length ? form.getFieldValue('models') : r.models)
      message.success(`连接成功，拉到 ${r.models.length} 个模型`)
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setProbing(false)
    }
  }

  const save = async () => {
    const v = await form.validateFields()
    setSaving(true)
    try {
      if (isNew) await api.addUpstream(v)
      else await api.patchUpstream(target.id, { name: v.name, base_url: v.base_url, models: v.models, ...(v.key ? { key: v.key } : {}) })
      message.success('已保存')
      onSaved()
      onClose()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Drawer open width={480} title={isNew ? '添加对话模型上游' : `编辑「${target.name}」`} onClose={onClose}
      footer={<div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}><Button onClick={onClose}>取消</Button><Button type="primary" loading={saving} onClick={save}>保存</Button></div>}>
      <Form form={form} layout="vertical" initialValues={isNew ? { models: [] } : { name: target.name, base_url: target.base_url, models: target.models }}>
        <Form.Item name="name" label="名称" rules={[{ required: true, message: '请填写名称' }]}><Input placeholder="例如：DeepSeek 官方 / 中转平台 A" /></Form.Item>
        <Form.Item name="base_url" label="地址" rules={[{ required: true, message: '请填写地址' }]} extra="OpenAI 兼容接口的地址，末尾的 /v1 会自动处理">
          <Input placeholder="https://api.example.com/v1" />
        </Form.Item>
        <Form.Item name="key" label={isNew ? '密钥' : `密钥（当前 ${target.key_hint || '未记录'}，留空不修改）`} rules={isNew ? [{ required: true, message: '请填写密钥' }] : []}>
          <Input.Password autoComplete="off" placeholder={isNew ? 'sk-...' : '不修改请留空'} />
        </Form.Item>
        <Form.Item label="开放的模型" required style={{ marginBottom: 0 }}>
          <Button onClick={probe} loading={probing} style={{ marginBottom: 8 }}>测试连接并拉取模型</Button>
          <Form.Item name="models" noStyle rules={[{ required: true, type: 'array', min: 1, message: '请至少选择一个模型' }]}>
            <Select mode="multiple" optionFilterProp="label" placeholder={isNew ? '先点上面的按钮拉取，或直接输入模型名' : '选择开放的模型'}
              options={[...new Set([...candidates])].map((m) => ({ value: m, label: m }))} />
          </Form.Item>
          {!isNew && <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>想看到上游的全部模型，填写新的密钥后点「测试连接并拉取模型」。</div>}
        </Form.Item>
      </Form>
    </Drawer>
  )
}

/* ---------------- 出图通道 ---------------- */

const ROUTE_NAME = { gpu: '本机 GPU', api: '第三方 API', h3: 'H3 网关' }

function ImageChannel() {
  const cfg = useRequest(api.imageConfig)
  const { message } = App.useApp()
  const [editing, setEditing] = useState<ImageProvider | 'new'>()
  const [testing, setTesting] = useState<string>()
  const [result, setResult] = useState<Record<string, { ok: boolean; seconds: number; error: string; preview?: string }>>({})

  const providers = cfg.data?.providers ?? []
  const route = cfg.data?.route ?? 'gpu'
  const usable = providers.some((p) => p.enabled)

  const h3Usable = !!cfg.data?.h3?.enabled
  const setRoute = async (r: 'gpu' | 'api' | 'h3') => {
    try {
      await api.setImageRoute(r)
      message.success(`之后的出图任务走${ROUTE_NAME[r]}`)
      cfg.reload()
    } catch (e) {
      message.error((e as Error).message)
    }
  }
  const test = async (p: ImageProvider) => {
    setTesting(p.id)
    try {
      const r = await api.testImageProvider(p.id)
      setResult((x) => ({ ...x, [p.id]: r }))
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setTesting(undefined)
    }
  }
  const toggle = async (p: ImageProvider, enabled: boolean) => {
    try {
      await api.patchImageProvider(p.id, { enabled })
      cfg.reload()
    } catch (e) {
      message.error((e as Error).message)
    }
  }
  const remove = async (p: ImageProvider) => {
    try {
      await api.deleteImageProvider(p.id)
      message.success('已删除')
      cfg.reload()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  return (
    <Panel
      tight
      title={<span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}><ImageIcon size={16} />出图通道</span>}
      sub="员工的出图工具不变，这里决定后台走哪条线。切换只影响之后提交的任务，已在排队或生成的任务不受影响。"
      extra={<Button type="primary" icon={<Plus size={14} />} onClick={() => setEditing('new')}>添加出图 API</Button>}
    >
      {cfg.error && <div className="muted" style={{ padding: 16 }}>{cfg.error}</div>}
      <div style={{ padding: '14px 16px', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', borderBottom: '1px solid var(--line-2)' }}>
        <span style={{ fontWeight: 600 }}>当前通道</span>
        <Seg value={route} onChange={setRoute}
          options={[{ value: 'gpu', label: '本机 GPU' }, { value: 'api', label: usable ? '第三方 API' : '第三方 API（需先添加）' },
            { value: 'h3', label: h3Usable ? 'H3 网关' : 'H3 网关（需先配置）' }]} />
        <Pill tone={route === 'gpu' ? 'green' : 'amber'}>{route === 'api' ? '出图走第三方，不占本机 GPU' : route === 'h3' ? '出图走 H3 网关（Z-Image）' : '出图走本机 ComfyUI'}</Pill>
      </div>
      <Table<ImageProvider>
        rowKey="id" loading={cfg.loading && !cfg.data} dataSource={providers} pagination={false} scroll={{ x: 760 }}
        locale={{ emptyText: <Empty>还没有出图 API。添加后就可以把通道切到「第三方 API」</Empty> }}
        columns={[
          { title: '名称', dataIndex: 'name', width: 140, render: (v) => <b>{v}</b> },
          { title: '地址', dataIndex: 'base_url', render: (v) => <span className="mono muted">{v}</span> },
          { title: '模型', dataIndex: 'model', width: 150, render: (v) => <Token>{v}</Token> },
          { title: '密钥', dataIndex: 'key_hint', width: 90, render: (v) => <span className="mono muted">{v || '—'}</span> },
          { title: '启用', dataIndex: 'enabled', width: 70, render: (v, p) => <Switch size="small" checked={v} onChange={(c) => toggle(p, c)} /> },
          {
            title: '测试', width: 280, render: (_, p) => {
              const r = result[p.id]
              return (
                <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
                  <Button size="small" loading={testing === p.id} onClick={() => test(p)}>出一张试试</Button>
                  {r?.preview && <img src={r.preview} alt="测试出图" style={{ height: 56, borderRadius: 4, cursor: 'zoom-in' }} onClick={() => window.open(r.preview)} />}
                  {r && (r.ok ? <Pill tone="green">{r.seconds} 秒</Pill> : <span title={r.error}><Pill tone="red">失败</Pill></span>)}
                </span>
              )
            },
          },
          {
            title: '', width: 110, render: (_, p) => (
              <span style={{ display: 'inline-flex', gap: 4 }}>
                <Button size="small" type="text" onClick={() => setEditing(p)}>编辑</Button>
                <Popconfirm title={`删除出图 API「${p.name}」？`} okText="删除" cancelText="取消" onConfirm={() => remove(p)}>
                  <Button size="small" type="text" danger>删除</Button>
                </Popconfirm>
              </span>
            ),
          },
        ]}
      />
      {Object.values(result).some((r) => !r.ok) && (
        <div className="muted" style={{ padding: '10px 16px', fontSize: 12 }}>
          {Object.entries(result).filter(([, r]) => !r.ok).map(([id, r]) => <div key={id}>测试失败：{r.error}</div>)}
        </div>
      )}
      {editing && <ProviderDrawer target={editing} onClose={() => setEditing(undefined)} onSaved={cfg.reload} />}
    </Panel>
  )
}

function ProviderDrawer({ target, onClose, onSaved }: { target: ImageProvider | 'new'; onClose: () => void; onSaved: () => void }) {
  const isNew = target === 'new'
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  const save = async () => {
    const v = await form.validateFields()
    let params: Record<string, unknown> | undefined
    if (v.params?.trim()) {
      try {
        params = JSON.parse(v.params)
      } catch {
        return message.error('额外参数不是合法的 JSON')
      }
    } else params = isNew ? undefined : {}
    setSaving(true)
    try {
      if (isNew) await api.addImageProvider({ name: v.name, base_url: v.base_url, model: v.model, key: v.key, params })
      else await api.patchImageProvider(target.id, { name: v.name, base_url: v.base_url, model: v.model, params, ...(v.key ? { key: v.key } : {}) })
      message.success('已保存')
      onSaved()
      onClose()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Drawer open width={480} title={isNew ? '添加出图 API' : `编辑「${target.name}」`} onClose={onClose}
      footer={<div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}><Button onClick={onClose}>取消</Button><Button type="primary" loading={saving} onClick={save}>保存</Button></div>}>
      <Form form={form} layout="vertical"
        initialValues={isNew ? { base_url: 'https://api.apimart.ai' } : { name: target.name, base_url: target.base_url, model: target.model, params: Object.keys(target.params).length ? JSON.stringify(target.params) : '' }}>
        <Form.Item name="name" label="名称" rules={[{ required: true, message: '请填写名称' }]}><Input placeholder="例如：apimart" /></Form.Item>
        <Form.Item name="base_url" label="地址" rules={[{ required: true, message: '请填写地址' }]} extra="站点地址即可，例如 https://api.apimart.ai；提交走 /v1/images/generations，结果走 /v1/tasks/{任务号}">
          <Input />
        </Form.Item>
        <Form.Item name="model" label="出图模型名" rules={[{ required: true, message: '请填写模型名' }]}><Input placeholder="按平台文档填写，例如 gpt-image-1" /></Form.Item>
        <Form.Item name="key" label={isNew ? '密钥' : `密钥（当前 ${target.key_hint || '未记录'}，留空不修改）`} rules={isNew ? [{ required: true, message: '请填写密钥' }] : []}>
          <Input.Password autoComplete="off" placeholder={isNew ? 'sk-...' : '不修改请留空'} />
        </Form.Item>
        <Form.Item name="params" label="额外参数（可选，JSON）" extra={'每次出图请求都会附带，例如 {"resolution": "1K"}；不同模型支持的参数以平台文档为准'}>
          <Input.TextArea rows={3} placeholder='{"resolution": "1K"}' />
        </Form.Item>
        <div className="muted" style={{ fontSize: 12 }}>保存后，用列表里的「出一张试试」实际跑一次，确认地址、模型和密钥都正确。</div>
      </Form>
    </Drawer>
  )
}

/* ---------------- H3 网关 ---------------- */

function H3Channel() {
  const cfg = useRequest(api.imageConfig)
  const { message } = App.useApp()
  const [editing, setEditing] = useState(false)
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; seconds: number; error: string; preview?: string }>()
  const g = cfg.data?.h3 ?? null
  const videoRoute = cfg.data?.video_route ?? 'gpu'

  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn()
      if (ok) message.success(ok)
      cfg.reload()
    } catch (e) {
      message.error((e as Error).message)
    }
  }
  const test = async () => {
    setTesting(true)
    try {
      setResult(await api.testH3())
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setTesting(false)
    }
  }

  return (
    <Panel
      tight
      title={<span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}><Cpu size={16} />H3 网关</span>}
      sub="本机 minimax h3 的生成网关（文生图、文生视频、图生视频）。网关单卡串行，中枢自己排队，一次只放少量任务进去。"
      extra={<Button type="primary" icon={<Plus size={14} />} onClick={() => setEditing(true)}>{g ? '修改配置' : '配置网关'}</Button>}
    >
      {cfg.error && <div className="muted" style={{ padding: 16 }}>{cfg.error}</div>}
      {!g ? <Empty>还没有配置 H3 网关。配置后，出图和视频通道都可以切到「H3 网关」</Empty> : (
        <>
          <div style={{ padding: '14px 16px', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', borderBottom: '1px solid var(--line-2)' }}>
            <span className="mono">{g.base_url}</span>
            <Token>{g.key_hint || '—'}</Token>
            {!g.verify_tls && <Pill tone="amber">不校验证书</Pill>}
            <Switch size="small" checked={g.enabled} onChange={(enabled) => run(() => api.saveH3({ base_url: g.base_url, enabled }))} />
            <Button size="small" loading={testing} onClick={test}>出一张试试</Button>
            {result?.preview && <img src={result.preview} alt="测试出图" style={{ height: 56, borderRadius: 4, cursor: 'zoom-in' }} onClick={() => window.open(result.preview)} />}
            {result && (result.ok ? <Pill tone="green">{result.seconds} 秒</Pill> : <span title={result.error}><Pill tone="red">失败：{result.error}</Pill></span>)}
            <Popconfirm title="删除 H3 网关配置？指向它的通道会退回本机 GPU。" okText="删除" cancelText="取消" onConfirm={() => run(() => api.deleteH3(), '已删除')}>
              <Button size="small" type="text" danger>删除</Button>
            </Popconfirm>
          </div>
          <div style={{ padding: '14px 16px', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 600 }}>视频通道</span>
            <Seg value={videoRoute} onChange={(r) => run(() => api.setVideoRoute(r), `之后的视频任务走${ROUTE_NAME[r]}`)}
              options={[{ value: 'gpu', label: '本机 GPU' }, { value: 'h3', label: g.enabled ? 'H3 网关' : 'H3 网关（已停用）' }]} />
            <Pill tone={videoRoute === 'h3' ? 'amber' : 'green'}>{videoRoute === 'h3' ? '视频走 H3 网关（约 2.5 分钟 / 5 秒）' : '视频走本机 ComfyUI'}</Pill>
          </div>
        </>
      )}
      {editing && <H3Drawer current={g} onClose={() => setEditing(false)} onSaved={cfg.reload} />}
    </Panel>
  )
}

function H3Drawer({ current, onClose, onSaved }: { current: H3Gateway | null; onClose: () => void; onSaved: () => void }) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const save = async () => {
    const v = await form.validateFields()
    setSaving(true)
    try {
      await api.saveH3({ base_url: v.base_url, verify_tls: v.verify_tls, ...(v.key ? { key: v.key } : {}) })
      message.success('已保存')
      onSaved()
      onClose()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }
  return (
    <Drawer open width={480} title={current ? '修改 H3 网关' : '配置 H3 网关'} onClose={onClose}
      footer={<div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}><Button onClick={onClose}>取消</Button><Button type="primary" loading={saving} onClick={save}>保存</Button></div>}>
      <Form form={form} layout="vertical" initialValues={{ base_url: current?.base_url ?? 'http://host.docker.internal:8100', verify_tls: current?.verify_tls ?? true }}>
        <Form.Item name="base_url" label="网关地址" rules={[{ required: true, message: '请填写地址' }]}
          extra="中枢所在机器能访问到的地址，例如 http://host.docker.internal:8100（本机 Docker）或 https://公网IP:8443（经云端转发）">
          <Input />
        </Form.Item>
        <Form.Item name="key" label={current ? `API Key（当前 ${current.key_hint || '未记录'}，留空不修改）` : 'API Key'} rules={current ? [] : [{ required: true, message: '请填写 Key' }]}
          extra="网关请求头 X-API-Key 用的 Key，请使用随机长串，不要用默认值">
          <Input.Password autoComplete="off" />
        </Form.Item>
        <Form.Item name="verify_tls" label="校验 HTTPS 证书" valuePropName="checked" extra="网关用自签证书时关闭；只建议在内网或隧道里关闭">
          <Switch />
        </Form.Item>
      </Form>
    </Drawer>
  )
}

/* ---------------- 模型价格 ---------------- */

type Draft = { input?: number | null; output?: number | null }

function Pricing() {
  const data = useRequest(api.modelPricing)
  const { message } = App.useApp()
  const [draft, setDraft] = useState<Record<string, Draft>>({})
  const [saving, setSaving] = useState<string>()
  const info = data.data
  const rate = info?.usd_cny ?? 7.2

  const shown = (p: ModelPrice) => ({
    input: draft[p.model]?.input ?? p.input_per_m,
    output: draft[p.model]?.output ?? p.output_per_m,
  })
  const dirty = (p: ModelPrice) => {
    const d = draft[p.model]
    return !!d && ((d.input !== undefined && d.input !== p.input_per_m) || (d.output !== undefined && d.output !== p.output_per_m))
  }
  const save = async (p: ModelPrice) => {
    const v = shown(p)
    if (!v.input || v.input <= 0) return message.error('请填写大于 0 的输入价')
    setSaving(p.model)
    try {
      await api.setModelPrice(p.model, { input_per_m: v.input, output_per_m: v.output || v.input })
      message.success(`已保存「${p.model}」的价格，立即生效`)
      setDraft((x) => ({ ...x, [p.model]: {} }))
      data.reload()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSaving(undefined)
    }
  }
  const clear = async (p: ModelPrice) => {
    try {
      await api.clearModelPrice(p.model)
      message.success(`已恢复「${p.model}」的默认价格`)
      setDraft((x) => ({ ...x, [p.model]: {} }))
      data.reload()
    } catch (e) {
      message.error((e as Error).message)
    }
  }
  const unset = (info?.models ?? []).filter((m) => !m.configured).length

  return (
    <Panel
      tight
      title={<span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}><Cpu size={16} />模型价格</span>}
      sub="员工的用量费用和月度额度都按这里的价格计算。单位：美元 / 百万 token，按模型厂商的官方价格填写；输出价留空则与输入价相同。"
    >
      {data.error && <div className="muted" style={{ padding: 16 }}>{data.error}</div>}
      {unset > 0 && info && (
        <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--line-2)' }}>
          <Pill tone="amber">{unset} 个模型还没设置价格</Pill>
          <span className="muted" style={{ marginLeft: 8, fontSize: 12.5 }}>
            没设置的模型按默认每百万 token ${info.default_input_per_m} 计费，费用会严重虚高，员工的月度额度很快被「花光」。
          </span>
        </div>
      )}
      <Table<ModelPrice>
        rowKey="model" loading={data.loading && !data.data} dataSource={info?.models ?? []} pagination={false} scroll={{ x: 760 }}
        locale={{ emptyText: <Empty>还没有开放的对话模型。先在上面接入上游并开放模型</Empty> }}
        columns={[
          { title: '模型', dataIndex: 'model', render: (v) => <Token>{v}</Token> },
          { title: '状态', dataIndex: 'configured', width: 110, render: (v) => (v ? <Pill tone="green">已设置</Pill> : <Pill tone="amber">默认（虚高）</Pill>) },
          {
            title: '输入价 $/百万', width: 150, render: (_, p) => (
              <InputNumber size="small" min={0} max={10000} step={0.01} style={{ width: 120 }} value={shown(p).input}
                onChange={(v) => setDraft((x) => ({ ...x, [p.model]: { ...x[p.model], input: v } }))} />
            ),
          },
          {
            title: '输出价 $/百万', width: 150, render: (_, p) => (
              <InputNumber size="small" min={0} max={10000} step={0.01} style={{ width: 120 }} value={shown(p).output}
                onChange={(v) => setDraft((x) => ({ ...x, [p.model]: { ...x[p.model], output: v } }))} />
            ),
          },
          {
            title: '折合人民币 / 百万', width: 170, render: (_, p) => (
              <span className="muted num">输入 ¥{((shown(p).input ?? 0) * rate).toFixed(2)} · 输出 ¥{((shown(p).output ?? 0) * rate).toFixed(2)}</span>
            ),
          },
          {
            title: '', width: 170, render: (_, p) => (
              <span style={{ display: 'inline-flex', gap: 4 }}>
                <Button size="small" type="primary" disabled={!dirty(p)} loading={saving === p.model} onClick={() => save(p)}>保存</Button>
                {p.configured && (
                  <Popconfirm title={`清除「${p.model}」的价格？`} description="会恢复为 New API 的默认虚高价格。" okText="清除" cancelText="取消" onConfirm={() => clear(p)}>
                    <Button size="small" type="text">恢复默认</Button>
                  </Popconfirm>
                )}
              </span>
            ),
          },
        ]}
      />
    </Panel>
  )
}
