// RestoPOS platforma sayti: tema, menyu, jonli sahna, bo'limlar, diagrammalar, ariza formasi, kirish va AI maslahatchi.
(() => {
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)]
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches
  const root = document.documentElement
  const store = { get: (k) => { try { return localStorage.getItem(k) } catch { return null } }, set: (k, v) => { try { localStorage.setItem(k, v) } catch { /* yopiq */ } } }
  const ss = { get: (k) => { try { return sessionStorage.getItem(k) } catch { return null } }, set: (k, v) => { try { sessionStorage.setItem(k, v) } catch { /* yopiq */ } } }

  // ---------- tema
  const isDark = () => root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches
  $('#theme')?.addEventListener('click', () => { const t = isDark() ? 'light' : 'dark'; root.dataset.theme = t; store.set('rp.theme', t) })

  // ---------- yuqori panel va mobil menyu
  const top = $('#top')
  const onScroll = () => top?.classList.toggle('scrolled', scrollY > 8)
  addEventListener('scroll', onScroll, { passive: true }); onScroll()
  const mb = $('#menuBtn'), mnav = $('#mnav')
  mb?.addEventListener('click', () => { const open = mnav.hidden; mnav.hidden = !open; mb.setAttribute('aria-expanded', String(open)) })
  mnav?.addEventListener('click', (e) => { if (e.target.closest('a')) { mnav.hidden = true; mb.setAttribute('aria-expanded', 'false') } })

  // ---------- jonli sahna: manbalardan buyurtma «chiptasi» panelga uchib boradi
  const stage = $('#stage')
  if (stage) {
    const fmt = (n) => Math.round(n).toLocaleString('ru-RU').replace(/,/g, ' ')
    const items = [
      ['pos', 'Kassa', 'Stol 3 · Osh ×2', 96000], ['tg', 'Telegram', 'Olib ketish · Lag\'mon', 42000], ['web', 'Sayt', 'Yetkazish · Manti ×10', 85000],
      ['pos', 'Kassa', 'Stol 11 · Shashlik ×6', 138000], ['tg', 'Telegram', 'Somsa ×6, choy', 63000], ['web', 'Sayt', 'QR menyu · Salat, sho\'rva', 57000],
      ['pos', 'Kassa', 'Stol 2 · Qozon kabob', 124000], ['tg', 'Telegram', 'Osh ×3', 135000],
    ]
    const lane = { pos: [0, $('.src.s1', stage)], tg: [1, $('.src.s2', stage)], web: [2, $('.src.s3', stage)] }
    const rev = $('#rev'), cnt = $('#cnt'), avg = $('#avg'), kit = $('#kit'), feed = $('#feed'), bars = $$('#bars i')
    let revenue = 4860000, count = 38, kitchen = 3, i = 0
    const bump = (el) => { el.classList.remove('bump'); void el.offsetWidth; el.classList.add('bump') }
    const ptAt = (pathId, t) => {           // SVG yo'ldagi nuqta → sahnadagi px
      const p = $('#' + pathId, stage), L = p.getTotalLength(), pt = p.getPointAtLength(L * t)
      const svg = p.ownerSVGElement, vb = svg.viewBox.baseVal, r = svg.getBoundingClientRect(), sr = stage.getBoundingClientRect()
      return [(pt.x / vb.width) * r.width + r.left - sr.left, (pt.y / vb.height) * r.height + r.top - sr.top]
    }
    const land = ([kind, label, text, sum]) => {
      revenue += sum; count += 1; kitchen = Math.max(1, Math.min(7, kitchen + (Math.random() < .55 ? 1 : -1)))
      rev.textContent = fmt(revenue); cnt.textContent = count; avg.textContent = fmt(revenue / count); kit.textContent = kitchen
      bump(rev); bump(cnt)
      const now = bars[bars.length - 1]; const h = Math.min(1, parseFloat(getComputedStyle(now).getPropertyValue('--h')) + .05)
      now.style.setProperty('--h', h >= 1 ? .45 : h)
      const li = document.createElement('li'); li.className = 'new'
      li.innerHTML = `<span class="tag t-${kind}">${label}</span>${text}<b>${fmt(sum)}</b>`
      feed.prepend(li); while (feed.children.length > 3) feed.lastElementChild.remove()
    }
    const fly = () => {
      const it = items[i++ % items.length], [n, src] = lane[it[0]]
      src.classList.remove('pulse'); void src.offsetWidth; src.classList.add('pulse')
      if (reduce) { land(it); return }
      const t = document.createElement('div'); t.className = 'ticket k-' + it[0]; t.textContent = `${it[2].split(' · ')[0]} · ${fmt(it[3])}`
      stage.appendChild(t)
      const steps = [0, .25, .5, .75, 1].map(k => ptAt('r' + (n + 1), k)), w = t.offsetWidth / 2, h = t.offsetHeight / 2
      const a = t.animate(steps.map(([x, y], k) => ({ transform: `translate(${x - w}px, ${y - h}px) scale(${k === 4 ? .6 : 1})`, opacity: k === 0 ? 0 : k === 4 ? 0 : 1 })),
        { duration: 1500, easing: 'cubic-bezier(.45,.05,.35,1)' })
      a.onfinish = () => { t.remove(); land(it) }
    }
    let timer = null
    const start = () => { if (!timer) { fly(); timer = setInterval(fly, 2300) } }
    const stop = () => { clearInterval(timer); timer = null }
    new IntersectionObserver(([e]) => (e.isIntersecting && !document.hidden ? start() : stop()), { threshold: .2 }).observe(stage)
    document.addEventListener('visibilitychange', () => (document.hidden ? stop() : stage.getBoundingClientRect().top < innerHeight && start()))
  }

  // ---------- bo'limlar (tablar)
  const tabs = $$('[role=tab][data-tab]'), panes = $$('[data-pane]')
  const pick = (k, focus) => {
    tabs.forEach(b => { const on = b.dataset.tab === String(k); b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1; if (on && focus) b.focus() })
    panes.forEach(p => { const on = p.dataset.pane === String(k); p.hidden = !on; p.classList.toggle('show', on) })
  }
  tabs.forEach((b, idx) => {
    b.addEventListener('click', () => pick(b.dataset.tab))
    b.addEventListener('keydown', (e) => {
      const d = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[e.key]
      if (d) { e.preventDefault(); pick((idx + d + tabs.length) % tabs.length, true) }
    })
  })
  if (tabs.length) pick(0)

  // ---------- ko'rinishga kirganda bir marta: diagrammalar va AI telefoni
  const once = (el, fn, th = .3) => { if (!el) return; if (reduce || !('IntersectionObserver' in window)) { fn(); return }
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { fn(); io.disconnect() } }, { threshold: th }); io.observe(el) }
  once($('#charts'), () => $('#charts').classList.add('in'), .25)
  const tl = $('#timeline')
  if (tl && !reduce && innerWidth > 1080) { tl.classList.add('armed'); once(tl, () => tl.classList.add('in'), .4) }
  const phone = $('#phone')
  if (phone && !reduce) { phone.classList.add('armed'); once(phone, () => phone.classList.add('play'), .35) }

  // ---------- kirish oynasi (restoran manzili → panel)
  const dlg = $('#loginDlg')
  $$('[data-login]').forEach(b => b.addEventListener('click', () => { if (dlg?.showModal) { dlg.showModal(); $('input', dlg).focus() } }))
  dlg?.addEventListener('close', () => {
    if (dlg.returnValue !== 'go') return
    const slug = ($('input', dlg).value || '').trim().toLowerCase()
    if (/^[a-z0-9][a-z0-9-]{1,30}$/.test(slug)) location.href = `${location.protocol}//${slug}.${location.host}/admin/`
  })

  // ---------- ariza formasi
  const lf = $('#leadForm'), lm = $('#leadMsg')
  lf?.addEventListener('submit', async (e) => {
    e.preventDefault()
    const data = Object.fromEntries(new FormData(lf))
    if ((data.phone || '').replace(/\D/g, '').length < 9) { lm.className = 'form-msg err'; lm.textContent = 'Telefon raqamini to\'liq yozing'; $('input[name=phone]', lf).focus(); return }
    const btn = $('button[type=submit]', lf); btn.disabled = true
    try {
      const r = await fetch('/api/v1/sales/lead', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
      const j = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(j.detail || 'Yuborib bo\'lmadi')
      lm.className = 'form-msg ok'; lm.textContent = 'Rahmat! Mutaxassisimiz tez orada qo\'ng\'iroq qiladi.'; lf.reset()
    } catch (err) { lm.className = 'form-msg err'; lm.textContent = err.message || 'Xato — qayta urinib ko\'ring' } finally { btn.disabled = false }
  })

  // ---------- AI maslahatchi
  const box = $('#aicBox'); if (!box) { $$('[data-open-ai]').forEach(b => b.remove()); return }
  const fab = $('#aicFab'), list = $('#aicList'), form = $('#aicForm'), q = $('#aicQ'), send = $('#aicSend'), file = $('#aicFile'), prev = $('#aicPrev'), hint = $('#aicHint')
  const KEY = 'rp.aichat'
  let hist = []; try { hist = JSON.parse(ss.get(KEY) || '[]') } catch { hist = [] }
  let busy = false, ctrl = null, img = ''
  const esc = (s) => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))
  const safe = (h) => esc(h.replace(/<(\/?)(b|i)>/g, '\u0001$1$2\u0002')).replace(/\u0001(\/?)(b|i)\u0002/g, '<$1$2>')
  const scroll = () => list.scrollTo({ top: list.scrollHeight, behavior: reduce ? 'auto' : 'smooth' })
  const add = (cls, html) => { const d = document.createElement('div'); d.className = 'm ' + cls; d.innerHTML = html; list.appendChild(d); scroll(); return d }
  const save = () => ss.set(KEY, JSON.stringify(hist.slice(-20)))
  hist.forEach(h => add(h.role === 'ai' ? 'ai' : 'me', h.role === 'ai' ? safe(h.text) : esc(h.text)))
  if (hist.length) $('#aicSug')?.remove()

  const open = (v) => {
    box.hidden = !v; fab.setAttribute('aria-expanded', String(v)); if (hint) hint.hidden = true
    if (v) { ss.set('rp.aiseen', '1'); setTimeout(() => q.focus(), 50); scroll() }
  }
  fab.addEventListener('click', () => open(box.hidden))
  $('#aicClose').addEventListener('click', () => open(false))
  $$('[data-open-ai]').forEach(b => b.addEventListener('click', () => open(true)))
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !box.hidden) open(false) })
  $('#aicClear').addEventListener('click', () => { if (busy) return; hist = []; save(); $$('.m, .lead-ok', list).slice(1).forEach(x => x.remove()) })
  list.addEventListener('click', (e) => { const b = e.target.closest('.sug button'); if (b) { q.value = b.textContent; $('#aicSug')?.remove(); ask() } })
  if (hint && !ss.get('rp.aiseen')) setTimeout(() => { if (box.hidden) hint.hidden = false }, 9000)
  hint?.addEventListener('click', () => open(true))

  // rasm: brauzerda kichraytiriladi (≤1600 px, JPEG) — tez yuboriladi
  file.addEventListener('change', async () => {
    const f = file.files[0]; file.value = ''
    if (!f) return
    try {
      const bmp = await createImageBitmap(f), k = Math.min(1, 1600 / Math.max(bmp.width, bmp.height))
      const c = document.createElement('canvas'); c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k)
      c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height); img = c.toDataURL('image/jpeg', .85)
    } catch { img = await new Promise(r => { const fr = new FileReader(); fr.onload = () => r(String(fr.result)); fr.readAsDataURL(f) }) }
    $('#aicImg').src = img; prev.hidden = false; q.focus()
  })
  $('#aicImgX').addEventListener('click', () => { img = ''; prev.hidden = true })
  q.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask() } })
  form.addEventListener('submit', (e) => { e.preventDefault(); busy ? ctrl?.abort() : ask() })

  const setBusy = (v) => {
    busy = v; send.classList.toggle('stop', v); send.setAttribute('aria-label', v ? 'To\'xtatish' : 'Yuborish')
    send.innerHTML = v ? '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" stroke="none"/></svg>'
      : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12h15M13 6l6 6-6 6"/></svg>'
    q.disabled = v; $('#aicSt').textContent = v ? 'yozmoqda…' : 'AI · odatda bir necha soniyada javob beradi'
  }
  async function ask() {
    const text = q.value.trim()
    if (busy || (!text && !img)) return
    $('#aicSug')?.remove()
    add('me', (img ? `<img src="${img}" alt="Yuborilgan rasm">` : '') + esc(text || '📷'))
    const history = hist.slice(-10), image = img
    hist.push({ role: 'me', text: text || '(rasm yubordi)' }); save()
    q.value = ''; img = ''; prev.hidden = true
    setBusy(true)
    const m = add('ai live', '<span class="typing"><i></i><i></i><i></i></span>')
    let raw = '', done = false
    ctrl = new AbortController()
    try {
      const r = await fetch('/api/v1/sales/ask-stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: ctrl.signal,
        body: JSON.stringify({ question: text, history, image }) })
      if (!r.ok || !r.body) { const j = await r.json().catch(() => ({})); throw new Error(j.detail || 'Javob olib bo\'lmadi') }
      const rd = r.body.getReader(), dec = new TextDecoder(); let buf = ''
      for (;;) {
        const { value, done: end } = await rd.read(); if (end) break
        buf += dec.decode(value, { stream: true }); let nl
        while ((nl = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, nl).trim(); buf = buf.slice(nl + 1); if (!line) continue
          let x; try { x = JSON.parse(line) } catch { continue }
          if (x.reset) { raw = ''; m.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>' }
          else if (typeof x.t === 'string') { raw += x.t; m.innerHTML = safe(raw.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')); scroll() }
          else if (x.done) {
            done = true; m.classList.remove('live')
            if (x.ok) { m.innerHTML = safe(x.answer); hist.push({ role: 'ai', text: x.answer.replace(/<[^>]+>/g, '') }); save()
              if (x.lead) { const d = document.createElement('div'); d.className = 'lead-ok'; d.textContent = '✅ Arizangiz qabul qilindi — mutaxassisimiz tez orada bog\'lanadi.'; list.appendChild(d) } }
            else { m.classList.add('err'); m.textContent = '⚠️ ' + (x.error || 'Xato') }
            scroll()
          }
        }
      }
      if (!done) { m.classList.remove('live'); if (!raw) { m.classList.add('err'); m.textContent = '⚠️ Javob kelmadi — qayta urinib ko\'ring' } }
    } catch (e) {
      m.classList.remove('live')
      if (e.name === 'AbortError') { m.innerHTML = (raw ? safe(raw) + '\n\n' : '') + '<i>⏹ To\'xtatildi</i>' }
      else { m.classList.add('err'); m.textContent = '⚠️ ' + (e.message || 'Xato') }
    } finally { setBusy(false); ctrl = null; q.focus() }
  }
})()
