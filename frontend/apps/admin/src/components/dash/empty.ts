/** Vidjetda ko'rsatadigan ma'lumot bormi? (bo'sh vidjetlar panelda joy egallamaydi — pastda bitta ixcham ro'yxatga yig'iladi) */
export function widgetEmpty(w: any): boolean {
  if (!w) return true
  if (w.type === 'chart') return !w.points?.length || w.points.every((p: any) => !Number(p.value))
  if (w.type === 'donut') return !w.items?.length || w.items.every((x: any) => !Number(x.value))
  if (w.type === 'rank' || w.type === 'list' || w.type === 'table') return !w.rows?.length
  return false
}
