import * as echarts from 'echarts'
import { useEffect, useRef } from 'react'

const INK3 = '#8e8d85'
const LINE = '#efeee9'

// 全站图表主题：细线、浅网格、无多余装饰
echarts.registerTheme('hub', {
  color: ['#5b5bd6', '#30a46c', '#f5a524', '#e5484d', '#0090ff', '#8e4ec6', '#12a594', '#d6409f', '#6f6e66'],
  textStyle: { fontFamily: 'Inter, -apple-system, "PingFang SC", sans-serif', color: INK3 },
  categoryAxis: {
    axisLine: { lineStyle: { color: LINE } },
    axisTick: { show: false },
    axisLabel: { color: INK3, fontSize: 11 },
    splitLine: { show: false },
  },
  valueAxis: {
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: INK3, fontSize: 11 },
    splitLine: { lineStyle: { color: LINE, type: [3, 3] } },
    nameTextStyle: { color: INK3, fontSize: 11 },
  },
  legend: { textStyle: { color: '#57564f', fontSize: 12 }, itemWidth: 10, itemHeight: 10, icon: 'roundRect' },
  tooltip: {
    backgroundColor: '#1b1a17',
    borderWidth: 0,
    padding: [8, 12],
    textStyle: { color: '#f6f6f3', fontSize: 12 },
    extraCssText: 'border-radius:8px;box-shadow:0 8px 24px -6px rgba(0,0,0,.3);',
    axisPointer: { lineStyle: { color: '#c9c8c1' }, shadowStyle: { color: 'rgba(91,91,214,0.05)' } },
  },
})

/** ECharts 的轻量封装：option 变化时更新，容器尺寸变化时自适应 */
export default function EChart({ option, height = 280 }: { option: echarts.EChartsOption; height?: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts>(null)

  useEffect(() => {
    if (!ref.current) return
    chart.current = echarts.init(ref.current, 'hub')
    const ro = new ResizeObserver(() => chart.current?.resize())
    ro.observe(ref.current)
    return () => {
      ro.disconnect()
      chart.current?.dispose()
    }
  }, [])

  useEffect(() => {
    chart.current?.setOption(option, true)
  }, [option])

  return <div ref={ref} style={{ width: '100%', height }} />
}

/** 面积图渐变 */
export const areaGradient = (color: string, top = 0.22) =>
  new echarts.graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: color + Math.round(top * 255).toString(16).padStart(2, '0') },
    { offset: 1, color: color + '00' },
  ])
