/**
 * Dashboard joylashuvi (v28): bo'sh joy qolmasin.
 *  - useMasonry: kartalar balandligiga qarab eng qisqa ustunga tushadi (CSS grid + 2px qatorlar),
 *    so'ng har ustunning oxirgi kartasi pastki chiziqqa cho'ziladi — ostida bo'sh joy qolmaydi.
 *  - useBalancedCols: KPI kartalari qatorlarni teng to'ldiradi (6 ta → 3×2, 5 ta → 5×1), yolg'iz karta qolmaydi.
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'

const ROW = 2

export function useMasonry(grid: Ref<HTMLElement | null>, deps: () => unknown, gap = 14) {
  let raf = 0, lastW = 0
  function layout() {
    const g = grid.value
    if (!g) return
    const cells = Array.from(g.children).filter(c => c instanceof HTMLElement) as HTMLElement[]
    if (!cells.length) return
    for (const c of cells) { c.style.gridRowEnd = ''; c.style.alignSelf = 'start'; c.style.marginBottom = `${gap}px` }
    const spans = cells.map(c => Math.max(1, Math.ceil((c.getBoundingClientRect().height + gap) / ROW)))
    cells.forEach((c, i) => { c.style.gridRowEnd = `span ${spans[i]}` })
    // ustunlar pastini tenglash: har bo'lakda (keng kartalar orasida) har ustunning oxirgi kartasini cho'zamiz
    const gTop = g.getBoundingClientRect().top
    let seg: number[] = []
    const flush = () => {
      if (seg.length < 2) { seg = []; return }
      const last = new Map<number, number>()
      for (const i of seg) {
        const r = cells[i].getBoundingClientRect(), key = Math.round(r.left)
        const prev = last.get(key)
        if (prev === undefined || cells[prev].getBoundingClientRect().top < r.top) last.set(key, i)
      }
      if (last.size < 2) { seg = []; return }
      const bottom = (i: number) => Math.round(cells[i].getBoundingClientRect().top - gTop) + spans[i] * ROW
      const maxB = Math.max(...[...last.values()].map(bottom))
      for (const i of last.values()) {
        const extra = Math.floor((maxB - bottom(i)) / ROW)
        if (extra > 0) { cells[i].style.gridRowEnd = `span ${spans[i] + extra}`; cells[i].style.alignSelf = 'stretch' }
      }
      seg = []
    }
    cells.forEach((c, i) => {
      if (c.classList.contains('wide')) flush()
      else seg.push(i)
    })
    flush()
  }
  function schedule() {
    cancelAnimationFrame(raf)
    raf = requestAnimationFrame(() => requestAnimationFrame(layout))
  }
  let ro: ResizeObserver | null = null
  onMounted(() => {
    schedule()
    document.fonts?.ready.then(schedule).catch(() => {})
    window.addEventListener('resize', schedule)
    ro = new ResizeObserver(([e]) => { const w = Math.round(e.contentRect.width); if (w !== lastW) { lastW = w; schedule() } })
    if (grid.value) ro.observe(grid.value)
  })
  watch(grid, (g, old) => { if (old) ro?.unobserve(old); if (g) { ro?.observe(g); schedule() } })
  watch(deps, () => nextTick(schedule), { deep: false })
  onBeforeUnmount(() => { cancelAnimationFrame(raf); ro?.disconnect(); window.removeEventListener('resize', schedule) })
  return { relayout: schedule }
}

/** n ta kartani qatorlarga teng bo'lish: har karta kamida minW px, oxirgi qatorda bo'sh joy eng kam.
 *  Qolgan bo'sh joyni flex-grow to'ldiradi (CSS: flex: 1 1 calc(100% / var(--cols) - gap)). */
export function useBalancedCols(box: Ref<HTMLElement | null>, count: () => number, minW = 200, gap = 10) {
  const cols = ref(4)
  const W = ref(0)
  function calc() {
    const n = count()
    if (!n) return
    const fit = Math.max(1, Math.floor((W.value + gap) / (minW + gap)))
    let best = 1, waste = Infinity
    const top = Math.min(fit, n)
    for (let c = top; c >= Math.max(1, Math.ceil(top / 2)); c--) {
      const w = Math.ceil(n / c) * c - n
      if (w < waste) { waste = w; best = c }
      if (w === 0) break
    }
    cols.value = best
  }
  let ro: ResizeObserver | null = null
  onMounted(() => {
    ro = new ResizeObserver(([e]) => { W.value = e.contentRect.width; calc() })
    if (box.value) { W.value = box.value.clientWidth; ro.observe(box.value) }
    calc()
  })
  watch(box, (b, old) => { if (old) ro?.unobserve(old); if (b) { W.value = b.clientWidth; ro?.observe(b); calc() } })
  watch(count, calc)
  onBeforeUnmount(() => ro?.disconnect())
  return cols
}
