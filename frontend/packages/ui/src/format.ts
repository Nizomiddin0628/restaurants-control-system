export type I18n = Record<string, string | undefined>
/** 36000 → "36 000" */
export const money = (v: number | string | null | undefined) =>
  v === null || v === undefined || v === '' ? '' : Number(v).toLocaleString('ru-RU').replace(/,/g, ' ')
/** 3 tilli JSON → matn (uz → ru → en) */
export const t = (v: I18n | string | null | undefined, lang = 'uz') =>
  typeof v === 'string' ? v : (v && (v[lang] || v.uz || v.ru || v.en)) || ''
