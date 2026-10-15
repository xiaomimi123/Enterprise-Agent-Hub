import { Button, Spin } from 'antd'
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError, type AuthUser } from './api'

interface Session {
  mode: string
  user: AuthUser
  logout: () => Promise<void>
}

const AuthContext = createContext<Session | null>(null)
const NEXT_KEY = 'hub.loginNext'

export function useSession() {
  const s = useContext(AuthContext)
  if (!s) throw new Error('useSession 必须在 AuthGate 内使用')
  return s
}

async function goLogin() {
  try {
    sessionStorage.setItem(NEXT_KEY, location.pathname + location.search)
  } catch {
    // 无痕模式等情况下 sessionStorage 不可用，登录后回到首页
  }
  const { url } = await api.loginUrl()
  location.href = url
}

function FullScreen({ children }: { children: ReactNode }) {
  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: 'var(--bg)' }}>
      <div style={{ textAlign: 'center', maxWidth: 380, padding: 24 }}>{children}</div>
    </div>
  )
}

function Brand() {
  return (
    <div className="brand-mark" style={{ width: 44, height: 44, borderRadius: 12, margin: '0 auto 18px' }}>
      <svg width="22" height="22" viewBox="0 0 16 16" fill="none">
        <circle cx="8" cy="8" r="2.4" fill="#fff" />
        <path d="M8 1.5v3M8 11.5v3M1.5 8h3M11.5 8h3" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" opacity=".85" />
      </svg>
    </div>
  )
}

/** 登录守卫：演示模式直接放行；Casdoor 模式下未登录则跳转到 Casdoor 登录页 */
export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ status: 'loading' | 'ok' | 'forbidden' | 'error'; session?: Omit<Session, 'logout'>; msg?: string }>({ status: 'loading' })

  useEffect(() => {
    api.me()
      .then((s) => setState({ status: 'ok', session: s }))
      .catch((e: Error) => {
        if (e instanceof ApiError && e.status === 401) {
          goLogin().catch((err: Error) => setState({ status: 'error', msg: err.message }))
        } else if (e instanceof ApiError && e.status === 403) {
          setState({ status: 'forbidden', msg: e.message })
        } else {
          setState({ status: 'error', msg: e.message })
        }
      })
  }, [])

  const logout = async () => {
    const r = await api.logout()
    location.href = r.casdoor_logout_url ?? '/'
  }

  if (state.status === 'ok' && state.session) {
    return <AuthContext.Provider value={{ ...state.session, logout }}>{children}</AuthContext.Provider>
  }
  if (state.status === 'forbidden' || state.status === 'error') {
    return (
      <FullScreen>
        <Brand />
        <div style={{ fontSize: 18, fontWeight: 650 }}>{state.status === 'forbidden' ? '无权访问控制台' : '暂时无法连接中枢'}</div>
        <div className="muted" style={{ margin: '8px 0 20px', lineHeight: 1.6 }}>{state.msg}</div>
        {state.status === 'forbidden'
          ? <Button onClick={logout}>换个账号登录</Button>
          : <Button onClick={() => location.reload()}>重试</Button>}
      </FullScreen>
    )
  }
  return (
    <FullScreen>
      <Brand />
      <Spin />
      <div className="muted" style={{ marginTop: 12 }}>正在验证登录状态…</div>
    </FullScreen>
  )
}

/** Casdoor 登录回调页：用 code 换取会话，然后回到登录前的页面 */
export function CallbackPage() {
  const [params] = useSearchParams()
  const nav = useNavigate()
  const [error, setError] = useState<string>()
  const done = useRef(false)

  useEffect(() => {
    // StrictMode 下 effect 会执行两次，code 只能用一次
    if (done.current) return
    done.current = true
    const code = params.get('code')
    const st = params.get('state')
    if (!code || !st) return
    api.authCallback(code, st)
      .then(() => {
        let next = '/'
        try {
          next = sessionStorage.getItem(NEXT_KEY) || '/'
          sessionStorage.removeItem(NEXT_KEY)
        } catch {
          // 忽略
        }
        nav(next, { replace: true })
      })
      .catch((e: Error) => setError(e.message))
  }, [params, nav])

  const shown = error ?? (!params.get('code') || !params.get('state') ? '回调参数缺失' : undefined)
  return (
    <FullScreen>
      <Brand />
      {shown ? (
        <>
          <div style={{ fontSize: 18, fontWeight: 650 }}>登录失败</div>
          <div className="muted" style={{ margin: '8px 0 20px' }}>{shown}</div>
          <Button type="primary" onClick={() => goLogin()}>重新登录</Button>
        </>
      ) : (
        <>
          <Spin />
          <div className="muted" style={{ marginTop: 12 }}>正在登录…</div>
        </>
      )}
    </FullScreen>
  )
}
