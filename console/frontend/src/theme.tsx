// 三年级六班集团 · 主题：亮色「作业本」/ 暗色「黑板」。
// CSS 里用同名变量（index.css 的 :root 与 [data-theme="dark"]），这里是给 Ant Design 和 ECharts（Canvas 读不到 CSS 变量）用的同一套颜色。
import { ConfigProvider, theme as antdTheme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export type Mode = 'light' | 'dark'

export interface Palette {
  bg: string
  surface: string
  surface2: string
  surface3: string
  line: string
  line2: string
  ink: string
  ink2: string
  ink3: string
  ink4: string
  accent: string
  accentDeep: string
  green: string
  amber: string
  red: string
  blue: string
  violet: string
  teal: string
  pink: string
  /** 图表系列色：作业本红、黑板绿、荧光黄、钢笔蓝…… */
  series: string[]
}

export const PALETTE: Record<Mode, Palette> = {
  light: {
    bg: '#fbf9f3', surface: '#fffdf8', surface2: '#f7f4ec', surface3: '#f1ede2',
    line: '#e7e1d3', line2: '#efeadf', ink: '#23211c', ink2: '#4f4b42', ink3: '#8b8578', ink4: '#b9b3a5',
    accent: '#e0533c', accentDeep: '#b83a25', green: '#2f7d63', amber: '#c98a0c', red: '#d23f2c', blue: '#3b63c4', violet: '#8150b8',
    teal: '#1d8577', pink: '#c94f8a',
    series: ['#e0533c', '#2f7d63', '#e5a92a', '#3b63c4', '#8150b8', '#1d8577', '#c94f8a', '#8b8578'],
  },
  dark: {
    bg: '#1b2420', surface: '#212c27', surface2: '#1e2823', surface3: '#2a3631',
    line: '#33423a', line2: '#2c3933', ink: '#f0eee4', ink2: '#c8c6ba', ink3: '#8f9b92', ink4: '#66726a',
    accent: '#ff7d62', accentDeep: '#d9583f', green: '#6cc7a1', amber: '#f2c75c', red: '#ff7a66', blue: '#8eabff', violet: '#c39bff',
    teal: '#5fd0c0', pink: '#ff8fc0',
    series: ['#ff7d62', '#6cc7a1', '#f2c75c', '#8eabff', '#c39bff', '#5fd0c0', '#ff8fc0', '#a8b3ab'],
  },
}

const STORAGE_KEY = 'hub-theme'

function initialMode(): Mode {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'light' || saved === 'dark') return saved
  } catch {
    /* 隐私模式等情况下读不到，按系统设置 */
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

interface ThemeCtx {
  mode: Mode
  p: Palette
  setMode: (m: Mode) => void
  toggle: () => void
}

const Ctx = createContext<ThemeCtx>({ mode: 'light', p: PALETTE.light, setMode: () => {}, toggle: () => {} })

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<Mode>(initialMode)

  useEffect(() => {
    document.documentElement.dataset.theme = mode
    document.documentElement.style.colorScheme = mode
  }, [mode])

  const setMode = useCallback((m: Mode) => {
    setModeState(m)
    try {
      localStorage.setItem(STORAGE_KEY, m)
    } catch {
      /* 记不住也不影响使用 */
    }
  }, [])

  const value = useMemo<ThemeCtx>(() => ({
    mode, p: PALETTE[mode], setMode, toggle: () => setMode(mode === 'light' ? 'dark' : 'light'),
  }), [mode, setMode])

  const p = PALETTE[mode]
  const antd = useMemo(() => ({
    algorithm: mode === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: {
      colorPrimary: p.accent,
      colorInfo: p.blue,
      colorSuccess: p.green,
      colorWarning: p.amber,
      colorError: p.red,
      colorText: p.ink,
      colorTextSecondary: p.ink2,
      colorTextTertiary: p.ink3,
      colorTextQuaternary: p.ink4,
      colorBorder: p.line,
      colorBorderSecondary: p.line2,
      colorBgLayout: p.bg,
      colorBgContainer: p.surface,
      colorBgElevated: p.surface,
      colorFillTertiary: p.surface3,
      colorFillSecondary: p.surface3,
      borderRadius: 9,
      borderRadiusLG: 14,
      fontSize: 13,
      fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif",
      controlHeight: 32,
      boxShadowSecondary: mode === 'dark'
        ? '0 12px 32px -8px rgba(0,0,0,.55), 0 0 0 1px rgba(255,255,255,.06)'
        : '0 12px 32px -8px rgba(35,33,28,.18), 0 0 0 1px rgba(35,33,28,.06)',
    },
    components: {
      Table: { headerBg: p.surface2, rowHoverBg: p.surface2, cellPaddingBlock: 12, cellPaddingInline: 16 },
      Drawer: { paddingLG: 24 },
      Segmented: { itemSelectedColor: p.ink, itemSelectedBg: p.surface, trackBg: p.surface3 },
      Button: { primaryShadow: 'none', defaultShadow: 'none', fontWeight: 500 },
    },
  }), [mode, p])

  return (
    <Ctx.Provider value={value}>
      <ConfigProvider locale={zhCN} theme={antd}>{children}</ConfigProvider>
    </Ctx.Provider>
  )
}

export const useTheme = () => useContext(Ctx)
