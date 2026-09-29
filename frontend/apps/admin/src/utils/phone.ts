/** O'zbekiston telefon raqami: +998 XX XXX XX XX. Backend core/phone.py bilan bir xil qoida. */
const CODES = new Set(['20', '33', '50', '55', '77', '88', '90', '91', '93', '94', '95', '97', '98', '99',
  '61', '62', '65', '66', '67', '69', '70', '71', '72', '73', '74', '75', '76', '78', '79'])

function digits(v: string) {
  let d = (v || '').replace(/\D/g, '')
  if (d.startsWith('998')) {
    d = d.slice(3)
    while (d.length > 9 && d.startsWith('998')) d = d.slice(3)     // "+998 998 90…" — kod ikki marta yozilgan
  } else if (d.length === 10 && d.startsWith('8')) d = d.slice(1)
  return d.slice(0, 9)
}

/** Yozilayotgan raqamni chiroyli ko'rinishga keltirish: "+998 90 123 45 67" */
export function formatUz(v: string): string {
  const d = digits(v)
  const p = [d.slice(0, 2), d.slice(2, 5), d.slice(5, 7), d.slice(7, 9)].filter(Boolean)
  return '+998' + (p.length ? ' ' + p.join(' ') : ' ')
}

/** Xato matni yoki '' (to'g'ri) */
export function checkUz(v: string): string {
  const d = digits(v)
  if (d.length >= 2 && !CODES.has(d.slice(0, 2))) return `«${d.slice(0, 2)}» — O'zbekiston operator kodi emas (90, 91, 93, 94, 97, 99, 33, 88, 77, 50…)`
  if (d.length < 9) return d.length ? `Raqam to'liq emas: yana ${9 - d.length} ta raqam kerak` : 'Telefon raqamni yozing'
  return ''
}
