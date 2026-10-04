// RestoPOS platforma sayti — «Restoraningiz bilan gaplashing»: suhbat sahnasi, buyurtma yo'li, solishtirish, AI maslahatchi (matn, rasm, ovoz).
(() => {
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)]
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches
  const root = document.documentElement
  const safeLS = (o) => ({ get: (k) => { try { return o.getItem(k) } catch { return null } }, set: (k, v) => { try { o.setItem(k, v) } catch { /* yopiq */ } } })
  const store = safeLS(window.localStorage), ss = safeLS(window.sessionStorage)
  const easeOut = (t) => 1 - Math.pow(1 - t, 3), easeInOut = (t) => (t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)
  const lerp = (a, b, k) => a + (b - a) * k, clamp = (v, a, b) => Math.min(b, Math.max(a, v))
  const fmt = (n) => Math.round(n).toLocaleString('ru-RU').replace(/[\s,]/g, ' ')
  const sleep = (ms) => new Promise(r => setTimeout(r, ms))
  const css = (name) => getComputedStyle(root).getPropertyValue(name).trim()
  // silliq raqam: eski qiymatdan yangisiga easeOut bilan
  const tween = (el, to, { dur = 900, prefix = '', suffix = '', from } = {}) => {
    if (!el) return
    const start = from ?? (parseFloat((el.dataset.v ?? el.textContent).replace(/[^\d.-]/g, '')) || 0)
    el.dataset.v = to
    if (reduce) { el.textContent = prefix + fmt(to) + suffix; return }
    const t0 = performance.now()
    const step = (now) => { const k = clamp((now - t0) / dur, 0, 1); el.textContent = prefix + fmt(lerp(start, to, easeOut(k))) + suffix; if (k < 1) requestAnimationFrame(step) }
    requestAnimationFrame(step)
  }
  const visible = (el, cb, th = .2) => {
    if (!el) return
    if (!('IntersectionObserver' in window)) { cb(true); return }
    new IntersectionObserver(([e]) => cb(e.isIntersecting), { threshold: th }).observe(el)
  }
  const once = (el, fn, th = .3) => {
    if (!el) return
    if (reduce || !('IntersectionObserver' in window)) { fn(); return }
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { fn(); io.disconnect() } }, { threshold: th }); io.observe(el)
  }

  // ---------- tema
  const isDark = () => root.dataset.theme !== 'light'
  const themeListeners = []
  $('#theme')?.addEventListener('click', () => { const t = isDark() ? 'light' : 'dark'; root.dataset.theme = t; store.set('rp.theme', t); themeListeners.forEach(f => f()) })

  // ---------- yuqori panel va mobil menyu
  const top = $('#top')
  const onScroll = () => top?.classList.toggle('scrolled', scrollY > 8)
  addEventListener('scroll', onScroll, { passive: true }); onScroll()
  const mb = $('#menuBtn'), mnav = $('#mnav')
  mb?.addEventListener('click', () => { const open = mnav.hidden; mnav.hidden = !open; mb.setAttribute('aria-expanded', String(open)) })
  mnav?.addEventListener('click', (e) => { if (e.target.closest('a')) { mnav.hidden = true; mb.setAttribute('aria-expanded', 'false') } })

  // ---------- bo'lim sarlavhalari: bir marta, yumshoq paydo bo'lish
  if (!reduce) $$('.sec-head, .feat, .plan, .inc-box, .ch, .built-grid > div, .stations li, .checks li, .score').forEach((el, i) => {
    el.style.opacity = '0'; el.style.transform = 'translateY(16px)'; el.style.filter = 'blur(4px)'
    el.style.transition = 'opacity .9s cubic-bezier(.2,.8,.2,1), transform .9s cubic-bezier(.2,.8,.2,1), filter .9s'
    el.style.transitionDelay = (el.matches('.feat, .plan, .ch, .built-grid > div, .stations li, .checks li') ? ([...el.parentElement.children].indexOf(el) % 3) * 90 : 0) + 'ms'
    once(el, () => { el.style.opacity = ''; el.style.transform = ''; el.style.filter = ''; setTimeout(() => { el.style.transition = ''; el.style.transitionDelay = '' }, 1400) }, .15)
  })

  // raqamlar (hero)
  once($('.facts'), () => $$('.facts [data-count]').forEach((b, i) => setTimeout(() => tween(b, +b.dataset.count, { from: 0, dur: 1400, suffix: b.dataset.suffix || '' }), i * 120)))
  $$('[data-scroll]').forEach(b => b.addEventListener('click', () => $(b.dataset.scroll)?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth' })))

  // ko'rinmaganda to'xtaydigan kutish: sahna ekrandan chiqsa yoki tab yashirilsa — pauza
  const gateFor = (el) => {
    let vis = false, waiters = []
    const open = () => vis && !document.hidden
    const flush = () => { if (open()) { waiters.forEach(r => r()); waiters = [] } }
    visible(el, (v) => { vis = v; flush() }, .15)
    document.addEventListener('visibilitychange', flush)
    return async (ms) => { if (ms) await sleep(ms); if (!open()) await new Promise(r => waiters.push(r)) }
  }
  // kometa: SVG yo'l bo'ylab bosh + so'nib boruvchi dum
  const NS = 'http://www.w3.org/2000/svg'
  const comet = (p, dur = 950) => new Promise(res => {
    if (reduce) { res(); return }
    const tail = Math.min(120, p.L * .5)
    p.line.style.transition = p.glow.style.transition = p.head.style.transition = ''
    p.line.style.strokeDasharray = `${tail} ${p.L + tail}`; p.glow.style.strokeDasharray = `${tail * .7} ${p.L + tail}`
    p.line.style.opacity = p.glow.style.opacity = p.head.style.opacity = '1'
    const t0 = performance.now()
    const step = (now) => {
      const k = clamp((now - t0) / dur, 0, 1), at = easeInOut(k) * p.L
      p.line.style.strokeDashoffset = String(tail - at); p.glow.style.strokeDashoffset = String(tail * .7 - at)
      const pt = p.line.getPointAtLength(at); p.head.setAttribute('cx', pt.x); p.head.setAttribute('cy', pt.y)
      if (k < 1) { requestAnimationFrame(step); return }
      p.line.style.transition = 'stroke-dasharray .9s ease, opacity 1.4s ease'; p.line.style.strokeDasharray = `${p.L} 0`; p.line.style.strokeDashoffset = '0'; p.line.style.opacity = '.5'
      p.glow.style.transition = 'opacity .9s ease'; p.glow.style.opacity = '0'; p.head.style.transition = 'opacity .5s'; p.head.style.opacity = '0'
      res()
    }
    requestAnimationFrame(step)
  })

  // ---------- HERO: «Restoraningiz bilan gaplashing» — suhbat dvigateli
  const talk = $('#talk'), pb = $('#phBody')
  if (talk && pb) {
    const svg = $('#talkLines'), phone = $('#heroPhone'), st = $('#phSt'), chips = $$('#srcs li')
    const wait = gateFor(talk)
    let lines = {}
    const layout = () => {
      lines = {}
      if (!svg || getComputedStyle(svg).display === 'none') return
      const tr = talk.getBoundingClientRect(), pr = phone.getBoundingClientRect()
      svg.setAttribute('viewBox', `0 0 ${tr.width} ${tr.height}`); svg.innerHTML = ''
      chips.forEach((li, i) => {
        const r = li.getBoundingClientRect(), x0 = r.right - tr.left, y0 = r.top + r.height / 2 - tr.top
        const x1 = pr.left - tr.left + 4, y1 = pr.top - tr.top + pr.height * (.42 + i * .07), k = Math.max(30, (x1 - x0) * .55)
        const d = `M${x0} ${y0} C${x0 + k} ${y0}, ${x1 - k} ${y1}, ${x1} ${y1}`, c = getComputedStyle(li).getPropertyValue('--c').trim()
        const mk = (cls, w) => { const e = document.createElementNS(NS, 'path'); e.setAttribute('d', d); e.setAttribute('fill', 'none'); if (cls) e.setAttribute('class', cls); else { e.setAttribute('stroke', c); e.setAttribute('stroke-width', w); e.setAttribute('stroke-linecap', 'round'); e.style.opacity = '0' } svg.appendChild(e); return e }
        mk('base'); const glow = mk('', 7); glow.style.filter = 'blur(5px)'; const line = mk('', 2.2)
        const head = document.createElementNS(NS, 'circle'); head.setAttribute('r', '4'); head.setAttribute('fill', c); head.style.opacity = '0'; head.style.filter = `drop-shadow(0 0 6px ${c})`; svg.appendChild(head)
        lines[li.dataset.s] = { line, glow, head, L: line.getTotalLength() }
      })
    }
    const fade = () => Object.values(lines).forEach(p => { p.line.style.transition = 'opacity 1.2s ease'; p.line.style.opacity = '0' })
    const light = async (keys) => {
      chips.forEach(li => li.classList.toggle('on', keys.includes(li.dataset.s)))
      fade(); await Promise.all(keys.map((k, i) => lines[k] ? sleep(i * 160).then(() => comet(lines[k])) : null))
    }
    // FLIP: yangi xabar qo'shilganda eskilar yumshoq yuqoriga suriladi
    const flip = (fn) => {
      const kids = [...pb.children], before = kids.map(k => k.getBoundingClientRect().top)
      fn()
      if (!reduce) kids.forEach((k, i) => { if (!k.isConnected) return; const dy = before[i] - k.getBoundingClientRect().top; if (Math.abs(dy) > .5) k.animate([{ transform: `translateY(${dy}px)` }, { transform: 'none' }], { duration: 620, easing: 'cubic-bezier(.2,.8,.2,1)' }) })
      const top = pb.getBoundingClientRect().top
      ;[...pb.children].forEach(k => { if (k.getBoundingClientRect().bottom < top - 40) k.remove() })
    }
    const enter = (d) => { if (!reduce) d.animate([{ opacity: 0, transform: 'translateY(14px) scale(.97)' }, { opacity: 1, transform: 'none' }], { duration: 560, easing: 'cubic-bezier(.2,.8,.2,1)' }) }
    const el = (cls, html) => { const d = document.createElement('div'); d.className = 'msg ' + cls; d.innerHTML = html; return d }
    const say = (cls, html) => { const d = el(cls, html); flip(() => pb.appendChild(d)); enter(d); return d }
    const status = (t) => { st.textContent = t ? 'yozmoqda…' : 'restoran boti'; st.classList.toggle('typing-st', !!t) }
    const think = () => { status(true); return say('ai typing', '<span></span><span></span><span></span>') }
    const answer = (t, html) => { const d = el('ai', html); flip(() => t.replaceWith(d)); enter(d); status(false); return d }
    const grow = (d) => setTimeout(() => $('.mbars, .mhb', d)?.classList.add('in'), 120)
    const voice = (sec) => say('me v', '<span class="play"></span><span class="wave" aria-hidden="true">' + '<i></i>'.repeat(16) + `</span><em>0:0${sec}</em>`)
    const bars = '<div class="mbars">' + [.45, .6, .4, .75, .62, 1, .85].map((h, i) => `<i style="--h:${h};transition-delay:${i * 70}ms"${i === 5 ? ' class="hl"' : ''}></i>`).join('') + '</div><small>7 kunlik savdo · shanba eng yaxshi kun</small>'
    const scenes = [
      async () => {
        voice(6); await wait(900); say('me tr', '🗣 «Kecha savdo qanday bo\'ldi?»'); await wait(500)
        const t = think(); await light(['kassa', 'rep']); await wait(500)
        answer(t, '<b>📊 Kecha: 12,4 mln so\'m</b> — 96 chek, o\'rtacha chek 129 000.<br>O\'tgan dushanbadan <b>+12%</b>. Eng ko\'p: Osh (64), Lag\'mon (41).'); await wait(1200)
        grow(say('ai', bars)); await wait(1800)
        const t2 = think(); await light(['stock']); await wait(400)
        answer(t2, '<b>🎯 Tavsiya:</b> guruch 2 kunga yetadi — bugun buyurtma bering.')
      },
      async () => {
        say('me', 'Omborda nima tugayapti?'); await wait(600)
        const t = think(); await light(['stock']); await wait(500)
        answer(t, '🔴 <b>Guruch</b> — 2 kunga yetadi<br>🟠 <b>Kungaboqar yog\'i</b> — 3 kunga<br>🟠 <b>Pomidor</b> — 3 kunga<br>🟢 Go\'sht va un — yetarli')
      },
      async () => {
        voice(4); await wait(900); say('me tr', '🗣 «Mantini bugunga stop-listga qo\'y»'); await wait(500)
        const t = think(); await light(['kds', 'kassa']); await wait(400)
        const a = answer(t, '🛑 <b>Manti</b> stop-listga qo\'yiladi — bugun kassa va saytda ko\'rinmaydi.<br>Tasdiqlaysizmi?<div class="mbtns"><span>✅ Tasdiqlash</span><span>✖️ Bekor</span></div>')
        await wait(1900); $('.mbtns span', a)?.classList.add('tap'); await wait(800)
        answer(think(), '✅ Bajarildi — Manti stop-listda. Ertaga o\'zim eslataman.')
      },
      async () => {
        say('me', 'Qaysi filial yaxshi ishlayapti?'); await wait(600)
        const t = think(); await light(['rep', 'kassa']); await wait(400)
        grow(answer(t, '<b>Shu oy savdo, mln so\'m:</b><div class="mhb"><span>Chilonzor<i style="--v:1"></i><em>412</em></span><span>Yunusobod<i style="--v:.86"></i><em>356</em></span><span>Sergeli<i style="--v:.58"></i><em>241</em></span></div>')); await wait(1700)
        answer(think(), '💡 Sergeli\'da o\'rtacha chek boshqalardan <b>18%</b> past — kechki menyuni ko\'rib chiqish kerak.')
      },
      async () => {
        voice(3); await wait(900); say('me tr', '🗣 «Bugun kim kechikdi?»'); await wait(500)
        const t = think(); await light(['staff', 'task']); await wait(400)
        answer(t, '⏰ <b>2 kishi kechikdi:</b><br>Jasur — 09:14 (+14 daq)<br>Malika — 09:06 (+6 daq)<br>Qolgan 11 kishi vaqtida keldi.')
      },
    ]
    let rt = 0
    addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(layout, 150) })
    themeListeners.push(layout)
    document.fonts?.ready.then(layout)
    layout()
    ;(async () => {
      if (reduce) { await scenes[0](); return }
      await wait(600)
      for (let i = 0; ; i = (i + 1) % scenes.length) {
        await scenes[i](); await wait(2600)
        chips.forEach(li => li.classList.remove('on')); fade(); await wait(700)
      }
    })()
  }

  // ---------- BITTA SOTUV: tomirlar bo'ylab oqim
  const flow = $('#flow')
  if (flow) {
    const svg = $('#veins'), hub = $('#hub'), cards = $$('.mcard', flow), rBody = $('#rBody'), stamp = $('#stamp'), cashier = $('#rCashier')
    const NS = 'http://www.w3.org/2000/svg'
    const sales = [
      { who: 'Dilnoza', items: [['Osh, choyxona', 2, 64000], ['Achchiq-chuchuk', 1, 12000], ['Non', 2, 8000]], disc: 0, stock: ['−0,4 kg', 'Guruch: 18,6 kg qoldi'], kds: ['#1044', '3 ta taom tayyorlanmoqda'], staff: 19, crm: ['Aziz K.', 840] },
      { who: 'Jasur', items: [['Shashlik (qo\'y)', 6, 108000], ['Lag\'mon', 2, 56000], ['Kompot', 2, 16000]], disc: 9000, stock: ['−1,2 kg', 'Go\'sht: 23,4 kg qoldi'], kds: ['#1045', '10 ta sikh grilda'], staff: 27, crm: ['Malika R.', 1710] },
      { who: 'Nodira', items: [['Manti', 10, 70000], ['Sho\'rva', 2, 44000], ['Choy', 1, 6000]], disc: 0, stock: ['−1,5 kg', 'Un: 41 kg qoldi'], kds: ['#1046', '2 ta taom tayyorlanmoqda'], staff: 22, crm: ['Bobur T.', 1200] },
    ]
    let si = 0, paths = [], running = false, cycle = null
    const layout = () => {
      if (getComputedStyle(svg).display === 'none') return
      const fr = flow.getBoundingClientRect(), hr = hub.getBoundingClientRect()
      const x0 = hr.left + hr.width / 2 - fr.left, y0 = hr.top + hr.height / 2 - fr.top
      svg.setAttribute('viewBox', `0 0 ${fr.width} ${fr.height}`); svg.innerHTML = ''
      const defs = document.createElementNS(NS, 'defs'); svg.appendChild(defs)
      // chekdan markazga
      const rc = $('#receipt').getBoundingClientRect()
      const feed = document.createElementNS(NS, 'path')
      feed.setAttribute('d', `M${rc.right - fr.left - 4} ${y0} L${x0} ${y0}`); feed.setAttribute('class', 'base'); svg.appendChild(feed)
      paths = cards.map((c, i) => {
        const r = c.getBoundingClientRect(), x1 = r.left - fr.left + 2, y1 = r.top + r.height / 2 - fr.top
        const k = Math.max(50, (x1 - x0) * .45)
        const d = `M${x0} ${y0} C${x0 + k} ${y0}, ${x1 - k} ${y1}, ${x1} ${y1}`
        const color = getComputedStyle(c).getPropertyValue('--c').trim() || css('--brand')
        const g = document.createElementNS(NS, 'linearGradient'); g.id = 'vg' + i; g.setAttribute('gradientUnits', 'userSpaceOnUse')
        g.setAttribute('x1', x0); g.setAttribute('y1', y0); g.setAttribute('x2', x1); g.setAttribute('y2', y1)
        g.innerHTML = `<stop offset="0" stop-color="${css('--green')}"/><stop offset="1" stop-color="${color}"/>`; defs.appendChild(g)
        const base = document.createElementNS(NS, 'path'); base.setAttribute('d', d); base.setAttribute('class', 'base'); svg.appendChild(base)
        const glow = document.createElementNS(NS, 'path'); glow.setAttribute('d', d); glow.setAttribute('fill', 'none'); glow.setAttribute('stroke', `url(#vg${i})`)
        glow.setAttribute('stroke-width', '7'); glow.setAttribute('stroke-linecap', 'round'); glow.style.opacity = '0'; glow.style.filter = 'blur(5px)'; svg.appendChild(glow)
        const line = document.createElementNS(NS, 'path'); line.setAttribute('d', d); line.setAttribute('fill', 'none'); line.setAttribute('stroke', `url(#vg${i})`)
        line.setAttribute('stroke-width', '2.6'); line.setAttribute('stroke-linecap', 'round'); line.style.opacity = '0'; svg.appendChild(line)
        const head = document.createElementNS(NS, 'circle'); head.setAttribute('r', '4.5'); head.setAttribute('fill', color); head.style.opacity = '0'
        head.style.filter = `drop-shadow(0 0 6px ${color})`; svg.appendChild(head)
        const L = line.getTotalLength()
        return { line, glow, head, L, color, lit: false }
      })
    }
    // kometa: boshi + so'nib boruvchi dum
    const pulse = (p, dur = 1050) => new Promise(res => {
      const tail = Math.min(140, p.L * .45)
      p.line.style.strokeDasharray = `${tail} ${p.L + tail}`; p.glow.style.strokeDasharray = `${tail * .7} ${p.L + tail}`
      p.line.style.opacity = p.glow.style.opacity = p.head.style.opacity = '1'
      const t0 = performance.now()
      const step = (now) => {
        const k = clamp((now - t0) / dur, 0, 1), e = easeInOut(k), at = e * p.L
        p.line.style.strokeDashoffset = String(tail - at); p.glow.style.strokeDashoffset = String(tail * .7 - at)
        const pt = p.line.getPointAtLength(at); p.head.setAttribute('cx', pt.x); p.head.setAttribute('cy', pt.y)
        if (k < 1) requestAnimationFrame(step)
        else {   // yetib keldi — iz qoladi, bosh so'nadi
          p.line.style.transition = 'stroke-dasharray .8s ease, opacity 1.2s ease'; p.line.style.strokeDasharray = `${p.L} 0`; p.line.style.strokeDashoffset = '0'; p.line.style.opacity = '.55'
          p.glow.style.transition = 'opacity .8s ease'; p.glow.style.opacity = '0'; p.head.style.transition = 'opacity .5s'; p.head.style.opacity = '0'
          setTimeout(() => { p.line.style.transition = p.glow.style.transition = p.head.style.transition = '' }, 1300)
          res()
        }
      }
      requestAnimationFrame(step)
    })
    const val = (k) => $(`[data-k="${k}"]`, flow)
    const setCard = (i, s, total) => {
      const c = cards[i]; c.classList.add('on')
      if (i === 0) { val('stock').textContent = s.stock[0]; val('stockN').textContent = s.stock[1] }
      if (i === 1) { tween(val('cash'), total, { prefix: '+', suffix: ' so\'m', from: 0, dur: 1100 }); val('cashN').textContent = total > 100000 ? 'Karta orqali' : 'Naqd pul' }
      if (i === 2) { val('kds').textContent = s.kds[0]; val('kdsN').textContent = s.kds[1] }
      if (i === 3) tween(val('rep'), Math.round(total * .36), { prefix: '+', suffix: ' so\'m', from: 0, dur: 1100 })
      if (i === 4) { tween(val('staff'), s.staff, { suffix: ' chek', from: s.staff - 1, dur: 700 }); val('staffN').textContent = `${s.who} · bugungi savdo` }
      if (i === 5) { tween(val('crm'), Math.round(total / 100), { prefix: '+', suffix: ' bonus', from: 0, dur: 1000 }); val('crmN').textContent = `${s.crm[0]} kartasiga yozildi` }
    }
    const renderReceipt = (s) => {
      const total = s.items.reduce((a, [, , p]) => a + p, 0) - s.disc
      cashier.textContent = s.who
      rBody.innerHTML = s.items.map(([n, q, p], i) => `<span style="animation-delay:${i * 120}ms">${n}${q > 1 ? ' ×' + q : ''}<em>${fmt(p)}</em></span>`).join('')
        + (s.disc ? `<span class="disc" style="animation-delay:${s.items.length * 120}ms">Chegirma<em>−${fmt(s.disc)}</em></span>` : '')
        + `<hr><span class="tot" style="animation-delay:${(s.items.length + 1) * 120}ms">Jami<em>${fmt(total)}</em></span>`
      return total
    }
    const play = async () => {
      if (running) return
      running = true
      while (running) {
        const s = sales[si++ % sales.length]
        stamp.classList.remove('on'); cards.forEach(c => c.classList.remove('on'))
        paths.forEach(p => { p.line.style.opacity = '0'; p.glow.style.opacity = '0' })
        const total = renderReceipt(s)
        await sleep(900); if (!running) break
        stamp.classList.add('on'); hub.classList.remove('fire'); void hub.offsetWidth; hub.classList.add('fire')
        await sleep(350)
        if (paths.length && !reduce) {
          await Promise.all(paths.map((p, i) => sleep(i * 170).then(() => running && pulse(p)).then(() => running && setCard(i, s, total))))
        } else { cards.forEach((_, i) => setTimeout(() => setCard(i, s, total), i * 200)); await sleep(1400) }
        await sleep(3200)
      }
    }
    const relayout = () => { layout() }
    let rt = 0
    addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(relayout, 150) })
    themeListeners.push(relayout)
    document.fonts?.ready.then(relayout)
    relayout()
    visible(flow, (v) => { if (v) { relayout(); if (!running) { cycle = play() } } else running = false }, .25)
    void cycle
  }

  // ---------- TARMOQ: bo'limlar tugunlari, zarrachalar va jonli oqim
  const cv = $('#netCanvas')
  if (cv) {
    const ctx = cv.getContext('2d'), list = $$('#netList li'), live = $('#live')
    const MODS = [
      ['Kassa', '--green', ['Chek #1047 — 92 000 so\'m', 'Smena ochildi', 'Kassa topshirildi, farq yo\'q']],
      ['Oshxona', '--orange', ['Buyurtma #1047 tushdi', '#1045 tayyor — 6:40 da', 'Stol 4: Osh ×2']],
      ['Ombor', '--teal', ['Guruch −0,4 kg', 'Qoldiq yangilandi', 'Yog\' tugayapti — ogohlantirish']],
      ['Zakup', '--amber', ['Bozorlik: 1 840 000 so\'m', 'Ta\'minotchiga buyurtma', 'Qarz to\'landi']],
      ['Xodimlar', '--amber', ['Nodira keldi — 08:57', 'Jasur: 27 chek', 'Smena jadvali saqlandi']],
      ['Telegram', '--sky', ['Vazifa yuborildi', '«Keldim» qabul qilindi', 'Kassa qabul tasdiqlandi']],
      ['Sayt', '--sky', ['QR menyudan buyurtma', 'Stop-list yangilandi', 'Menyu e\'lon qilindi']],
      ['Bron', '--pink', ['Stol 7 — 19:00 bron', 'Bron tasdiqlandi', 'Zalda 3 ta bo\'sh stol']],
      ['Mijozlar', '--pink', ['+840 bonus yozildi', 'Yangi mijoz', 'Xabar tarqatildi']],
      ['Hisobotlar', '--brand', ['Bugungi foyda qayta hisoblandi', 'Z-hisobot saqlandi', 'Food cost: 29%']],
      ['Filiallar', '--brand', ['Chilonzor ma\'lumoti yangilandi', 'Sergeli: smena yopildi', 'Narxlar sinxronlandi']],
      ['AI Kotib', '--brand-2', ['Ertalabki hisobot yuborildi', '«Kecha qancha savdo?» — javob berildi', 'Diagramma chizildi']],
    ]
    let W = 0, H = 0, dpr = 1, nodes = [], edges = [], parts = [], active = 0, colors = {}, ink = '#000', muted = '#888', run = false, raf = 0, last = 0, auto = true
    const readColors = () => { MODS.forEach(m => { colors[m[1]] = css(m[1]) }); ink = css('--ink'); muted = css('--muted') }
    const build = () => {
      const r = cv.getBoundingClientRect(); dpr = Math.min(2, devicePixelRatio || 1); W = r.width; H = r.height
      cv.width = W * dpr; cv.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      const cx = W / 2, cy = H / 2, rx = W * .39, ry = H * .39
      nodes = [{ x: cx, y: cy, bx: cx, by: cy, r: 24, c: '--brand', center: true, ph: 0 }]
      MODS.forEach((m, i) => { const a = -Math.PI / 2 + i * (Math.PI * 2 / MODS.length); const x = cx + Math.cos(a) * rx, y = cy + Math.sin(a) * ry
        nodes.push({ x, y, bx: x, by: y, r: 9, c: m[1], label: m[0], i, ph: Math.random() * 6.28 }) })
      const seed = (k) => { const x = Math.sin(k * 99.13) * 43758.55; return x - Math.floor(x) }
      for (let k = 0; k < 26; k++) { const a = seed(k) * 6.28, d = .18 + seed(k + 50) * .62; const x = cx + Math.cos(a) * rx * d, y = cy + Math.sin(a) * ry * d
        nodes.push({ x, y, bx: x, by: y, r: 2.4, c: MODS[k % MODS.length][1], ph: seed(k + 9) * 6.28 }) }
      edges = []
      const mods = nodes.filter(n => n.label)
      mods.forEach((n, i) => { edges.push([0, nodes.indexOf(n)]); edges.push([nodes.indexOf(n), nodes.indexOf(mods[(i + 1) % mods.length])]); edges.push([nodes.indexOf(n), nodes.indexOf(mods[(i + 4) % mods.length])]) })
      nodes.forEach((n, i) => { if (n.label || n.center) return
        const near = nodes.map((m, j) => [j, Math.hypot(m.bx - n.bx, m.by - n.by)]).filter(([j]) => j !== i).sort((a, b) => a[1] - b[1]).slice(0, 3)
        near.forEach(([j]) => edges.push([i, j])) })
      parts = []
      readColors()
    }
    const spawn = (from = null) => {
      const pool = from == null ? edges : edges.filter(e => e[0] === from || e[1] === from)
      const e = pool[Math.floor(Math.random() * pool.length)]; if (!e) return
      const rev = from != null ? e[1] === from : Math.random() < .5
      parts.push({ a: rev ? e[1] : e[0], b: rev ? e[0] : e[1], t: 0, v: .35 + Math.random() * .45, trail: [], hot: from != null })
    }
    const draw = (now) => {
      const dt = Math.min(50, now - (last || now)) / 1000; last = now
      ctx.clearRect(0, 0, W, H)
      const T = now / 1000
      nodes.forEach(n => { n.x = n.bx + Math.sin(T * .6 + n.ph) * (n.label ? 3 : 5); n.y = n.by + Math.cos(T * .5 + n.ph) * (n.label ? 3 : 5) })
      const act = nodes.find(n => n.i === active)
      // qirralar
      edges.forEach(([a, b]) => {
        const A = nodes[a], B = nodes[b], hot = act && (A === act || B === act)
        ctx.strokeStyle = hot ? colors[act.c] : (colors[A.c] || muted); ctx.globalAlpha = hot ? .55 : .13; ctx.lineWidth = hot ? 1.4 : 1
        ctx.beginPath(); ctx.moveTo(A.x, A.y); ctx.lineTo(B.x, B.y); ctx.stroke()
      })
      // zarrachalar (dum bilan)
      parts.forEach(p => {
        p.t += dt * p.v
        const A = nodes[p.a], B = nodes[p.b], e = easeInOut(clamp(p.t, 0, 1)), x = lerp(A.x, B.x, e), y = lerp(A.y, B.y, e)
        p.trail.push([x, y]); if (p.trail.length > 14) p.trail.shift()
        const col = colors[(p.hot && act ? act : A).c] || ink
        for (let k = 1; k < p.trail.length; k++) {
          ctx.globalAlpha = (k / p.trail.length) * (p.hot ? .9 : .55); ctx.strokeStyle = col; ctx.lineWidth = (k / p.trail.length) * (p.hot ? 3 : 2)
          ctx.beginPath(); ctx.moveTo(p.trail[k - 1][0], p.trail[k - 1][1]); ctx.lineTo(p.trail[k][0], p.trail[k][1]); ctx.stroke()
        }
        ctx.globalAlpha = 1; ctx.fillStyle = col; ctx.shadowColor = col; ctx.shadowBlur = p.hot ? 12 : 6
        ctx.beginPath(); ctx.arc(x, y, p.hot ? 2.8 : 2, 0, 6.28); ctx.fill(); ctx.shadowBlur = 0
      })
      parts = parts.filter(p => p.t < 1)
      if (parts.length < 22 && Math.random() < .25) spawn()
      // tugunlar
      nodes.forEach(n => {
        const col = colors[n.c] || ink
        if (n.center) {
          const g = ctx.createRadialGradient(n.x - 6, n.y - 8, 2, n.x, n.y, n.r + 2)
          g.addColorStop(0, css('--cyan')); g.addColorStop(.55, css('--acc')); g.addColorStop(1, css('--violet'))
          ctx.globalAlpha = .18 + Math.sin(T * 1.6) * .06; ctx.fillStyle = col; ctx.beginPath(); ctx.arc(n.x, n.y, n.r + 16 + Math.sin(T * 1.6) * 3, 0, 6.28); ctx.fill()
          ctx.globalAlpha = 1; ctx.fillStyle = g; ctx.shadowColor = css('--acc'); ctx.shadowBlur = 26; ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, 6.28); ctx.fill(); ctx.shadowBlur = 0
          ctx.fillStyle = '#fff'; ctx.font = '700 16px Unbounded, Onest, system-ui'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('R', n.x, n.y + 1)
          return
        }
        if (!n.label) { ctx.globalAlpha = .5; ctx.fillStyle = col; ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, 6.28); ctx.fill(); return }
        const on = n === act, br = on ? 1 + Math.sin(T * 3) * .5 : 0
        if (on) { ctx.globalAlpha = .16; ctx.fillStyle = col; ctx.beginPath(); ctx.arc(n.x, n.y, 22 + br * 4, 0, 6.28); ctx.fill(); ctx.globalAlpha = .3; ctx.beginPath(); ctx.arc(n.x, n.y, 14 + br * 2, 0, 6.28); ctx.fill() }
        ctx.globalAlpha = 1; ctx.fillStyle = css('--surface'); ctx.strokeStyle = col; ctx.lineWidth = on ? 3 : 2
        ctx.beginPath(); ctx.arc(n.x, n.y, on ? 11 : 9, 0, 6.28); ctx.fill(); ctx.stroke()
        ctx.fillStyle = col; ctx.beginPath(); ctx.arc(n.x, n.y, on ? 4.5 : 3.5, 0, 6.28); ctx.fill()
        ctx.font = `${on ? 800 : 600} ${W < 500 ? 10 : 12}px Onest, system-ui`; ctx.textAlign = 'center'; ctx.textBaseline = 'top'
        ctx.fillStyle = on ? col : muted; ctx.globalAlpha = on ? 1 : .9; ctx.fillText(n.label, n.x, n.y + 16); ctx.globalAlpha = 1
      })
      if (run) raf = requestAnimationFrame(draw)
    }
    // jonli oqim satri — balandligi silliq ochiladi
    const pushLive = (i) => {
      const m = MODS[i], li = document.createElement('li'), d = new Date()
      li.style.setProperty('--c', css(m[1]))
      li.innerHTML = `<time>${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}</time><b></b><span></span>`
      li.querySelector('b').textContent = m[0]; li.querySelector('span').textContent = m[2][Math.floor(Math.random() * m[2].length)]
      live.prepend(li)
      if (!reduce) { const h = li.scrollHeight; li.animate([{ height: '0px', opacity: 0, paddingTop: '0px', paddingBottom: '0px' }, { height: h + 'px', opacity: 1, paddingTop: '10px', paddingBottom: '10px' }], { duration: 520, easing: 'cubic-bezier(.2,.8,.2,1)' }) }
      while (live.children.length > 8) live.lastElementChild.remove()
    }
    const setActive = (i, user = false) => {
      active = i; list.forEach(li => li.classList.toggle('on', +li.dataset.n === i))
      if (user) { auto = false; clearTimeout(setActive.t); setActive.t = setTimeout(() => { auto = true }, 9000) }
      const idx = nodes.findIndex(n => n.i === i); for (let k = 0; k < 4; k++) setTimeout(() => spawn(idx), k * 120)
      pushLive(i)
    }
    list.forEach(li => li.addEventListener('click', () => setActive(+li.dataset.n, true)))
    let cyc = 0
    const tick = () => { if (auto && run) setActive((active + 1) % MODS.length) }
    themeListeners.push(readColors)
    let rt2 = 0
    addEventListener('resize', () => { clearTimeout(rt2); rt2 = setTimeout(build, 150) })
    build(); for (let k = 0; k < 4; k++) pushLive(k * 3 % MODS.length); setActive(0)
    visible(cv, (v) => {
      if (v && !reduce) { if (!run) { run = true; last = 0; raf = requestAnimationFrame(draw) } if (!cyc) cyc = setInterval(tick, 2600) }
      else { run = false; cancelAnimationFrame(raf); clearInterval(cyc); cyc = 0; if (reduce) { run = false; requestAnimationFrame(draw) } }
    }, .1)
  }

  // ---------- xodimlar boti — bir marta ketma-ket
  const sp = $('#staffPhone')
  if (sp) {
    const btn = $('#sbBtn')
    const tap = () => { btn?.classList.add('tap'); setTimeout(() => { if (btn) { btn.classList.add('done'); btn.textContent = '✅ Qabul qilindi · 18:04' } }, 650) }
    if (reduce) tap()
    else { sp.classList.add('armed'); once(sp, () => { sp.classList.add('play'); setTimeout(tap, 6400) }, .35) }
  }

  // ---------- solishtirish
  const checks = $$('#checks input'), score = $('.score')
  if (checks.length && score) {
    const you = $('#scYou'), bar = $('#scBarYou'), msg = $('#scMsg'), name = score.dataset.platform || 'Biz'
    const text = (n) => n === 0 ? 'Belgilashni boshlang — farq shu yerda ko\'rinadi.'
      : n < 5 ? `Ko'p ish hali qo'lda yoki alohida dasturlarda. ${name}da bularning hammasi bitta tizimda.`
        : n < 9 ? `Yaxshi! Qolgan ${10 - n} tasi uchun alohida dastur yoki qo'l mehnati kerak bo'lyapti — ${name}da hammasi bor.`
          : `Zo'r dastur! Endi narxni solishtiring: ${name}da server, domen va yangilanishlar narx ichida.`
    const upd = () => { const n = checks.filter(c => c.checked).length; tween(you, n, { dur: 500 }); bar.style.width = n * 10 + '%'; msg.textContent = text(n) }
    checks.forEach(c => c.addEventListener('change', upd))
  }

  // ---------- diagrammalar, vaqt chizig'i — bir marta
  once($('#charts'), () => $('#charts').classList.add('in'), .25)
  const tl = $('#timeline')
  if (tl && !reduce && innerWidth > 1080) { tl.classList.add('armed'); once(tl, () => tl.classList.add('in'), .4) }

  // ---------- kirish oynasi
  const dlg = $('#loginDlg')
  $$('[data-login]').forEach(b => b.addEventListener('click', () => { if (dlg?.showModal) { dlg.showModal(); $('input', dlg).focus() } }))
  dlg?.addEventListener('close', () => {
    if (dlg.returnValue !== 'go') return
    const slug = ($('input', dlg).value || '').trim().toLowerCase()
    if (/^[a-z0-9][a-z0-9-]{1,30}$/.test(slug)) location.href = `${location.protocol}//${slug}.${location.host}/admin/`
  })

  // ---------- ariza
  const sendLead = async (data) => {
    if ((data.phone || '').replace(/\D/g, '').length < 9) throw new Error('Telefon raqamini to\'liq yozing')
    const r = await fetch('/api/v1/sales/lead', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
    const j = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(j.detail || 'Yuborib bo\'lmadi')
  }
  const lf = $('#leadForm'), lm = $('#leadMsg')
  lf?.addEventListener('submit', async (e) => {
    e.preventDefault()
    const btn = $('button[type=submit]', lf); btn.disabled = true
    try { await sendLead(Object.fromEntries(new FormData(lf))); lm.className = 'form-msg ok'; lm.textContent = 'Rahmat! Mutaxassisimiz tez orada qo\'ng\'iroq qiladi.'; lf.reset() }
    catch (err) { lm.className = 'form-msg err'; lm.textContent = err.message || 'Xato — qayta urinib ko\'ring' } finally { btn.disabled = false }
  })

  // ---------- AI maslahatchi
  const box = $('#aicBox'); if (!box) { $$('[data-open-ai]').forEach(b => b.remove()); return }
  const fab = $('#aicFab'), list = $('#aicList'), form = $('#aicForm'), q = $('#aicQ'), send = $('#aicSend'), file = $('#aicFile'), prev = $('#aicPrev'), hint = $('#aicHint')
  const KEY = 'rp.aichat'
  let sid = ss.get('rp.sid'); if (!sid) { sid = (crypto.randomUUID?.() || String(Math.random()).slice(2) + Date.now()).replace(/-/g, '').slice(0, 32); ss.set('rp.sid', sid) }
  let hist = []; try { hist = JSON.parse(ss.get(KEY) || '[]') } catch { hist = [] }
  let busy = false, ctrl = null, img = '', leadDone = ss.get('rp.lead') === '1', leadShown = false
  const esc = (s) => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))
  const safe = (h) => esc(h.replace(/<(\/?)(b|i)>/g, '\u0001$1$2\u0002')).replace(/\u0001(\/?)(b|i)\u0002/g, '<$1$2>')
  const scroll = () => list.scrollTo({ top: list.scrollHeight, behavior: reduce ? 'auto' : 'smooth' })
  const add = (cls, html) => { const d = document.createElement('div'); d.className = 'm ' + cls; d.innerHTML = html; list.appendChild(d); scroll(); return d }
  const save = () => ss.set(KEY, JSON.stringify(hist.slice(-20)))
  hist.forEach(h => add(h.role === 'ai' ? 'ai' : 'me', h.role === 'ai' ? safe(h.text) : esc(h.text)))
  if (hist.length) $('#aicSug')?.remove()

  const open = (v) => {
    box.hidden = !v; fab.setAttribute('aria-expanded', String(v)); if (hint) hint.hidden = true
    if (v) { ss.set('rp.aiseen', '1'); setTimeout(() => q.focus(), 60); scroll() }
  }
  fab.addEventListener('click', () => open(box.hidden))
  $('#aicClose').addEventListener('click', () => open(false))
  $$('[data-open-ai]').forEach(b => b.addEventListener('click', () => open(true)))
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !box.hidden) open(false) })
  $('#aicClear').addEventListener('click', () => { if (busy) return; hist = []; save(); $$('.m, .lead-ok, .lcard', list).slice(1).forEach(x => x.remove()) })
  list.addEventListener('click', (e) => { const b = e.target.closest('.sug button'); if (b) { q.value = b.textContent; $('#aicSug')?.remove(); ask() } })
  if (hint && !ss.get('rp.aiseen')) setTimeout(() => { if (box.hidden) hint.hidden = false }, 6000)
  hint?.addEventListener('click', (e) => { if (e.target.closest('.x')) { hint.hidden = true; ss.set('rp.aiseen', '1'); return } open(true) })

  // chat ichidagi qisqa forma (ochiq, ixtiyoriy)
  const leadCard = () => {
    if (leadDone || leadShown) return
    leadShown = true
    const c = document.createElement('form'); c.className = 'lcard'; c.noValidate = true
    c.innerHTML = '<b>📞 Mutaxassis bepul ko\'rsatib bersinmi?</b><p>10 daqiqada restoraningizga moslab ko\'rsatamiz. Raqamingizni faqat shu uchun ishlatamiz.</p>'
      + '<input name="name" placeholder="Ismingiz" autocomplete="name"><input name="phone" type="tel" inputmode="tel" placeholder="+998 90 123 45 67" autocomplete="tel" required>'
      + '<div class="row"><button class="btn primary" type="submit">Qo\'ng\'iroq qilinsin</button><button class="btn ghost" type="button" data-x>Keyinroq</button></div>'
    list.appendChild(c); scroll()
    c.querySelector('[data-x]').addEventListener('click', () => c.remove())
    c.addEventListener('submit', async (e) => {
      e.preventDefault()
      const b = c.querySelector('button[type=submit]'); b.disabled = true
      try {
        await sendLead({ ...Object.fromEntries(new FormData(c)), note: 'AI chat: ' + hist.filter(h => h.role === 'me').map(h => h.text).slice(-3).join(' | ').slice(0, 400) })
        leadDone = true; ss.set('rp.lead', '1')
        const ok = document.createElement('div'); ok.className = 'lead-ok'; ok.textContent = '✅ Rahmat! Mutaxassisimiz tez orada qo\'ng\'iroq qiladi.'; c.replaceWith(ok); scroll()
      } catch (err) { b.disabled = false; let m = c.querySelector('.err'); if (!m) { m = document.createElement('p'); m.className = 'err'; m.style.color = 'var(--red)'; c.appendChild(m) } m.textContent = err.message }
    })
  }

  // rasm
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

  // 🎙 ovozli xabar
  const mic = $('#aicMic'), recBar = $('#recBar'), recT = $('#recT')
  let rec = null, chunks = [], stream = null, secs = 0, rtimer = 0, discard = false
  const canRec = !!(navigator.mediaDevices?.getUserMedia && window.MediaRecorder)
  if (!canRec) mic?.remove()
  const stopRec = (drop) => { discard = drop; if (rec && rec.state !== 'inactive') rec.stop() }
  mic?.addEventListener('click', async () => {
    if (busy) return
    if (rec) { stopRec(false); return }
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }) } catch { add('ai err', 'Mikrofonga ruxsat berilmadi — brauzer sozlamasida ruxsat bering yoki yozib yuboring.'); return }
    const type = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/mp4'].find(t => MediaRecorder.isTypeSupported?.(t)) || ''
    rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined); chunks = []; secs = 0; discard = false
    rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data) }
    rec.onstop = async () => {
      clearInterval(rtimer); stream.getTracks().forEach(t => t.stop()); mic.classList.remove('rec'); recBar.hidden = true
      const mime = rec.mimeType || 'audio/webm'; rec = null
      if (discard) return
      const blob = new Blob(chunks, { type: mime })
      if (blob.size < 1500) { add('ai', 'Juda qisqa yozildi — 🎙 ni bosib gapiring, tugatgach yana bosing.'); return }
      const data = await new Promise(r => { const fr = new FileReader(); fr.onload = () => r(String(fr.result)); fr.readAsDataURL(blob) })
      const m = add('me', '🎙 <i>Eshityapman…</i>'); setBusy(true)
      try {
        const r = await fetch('/api/v1/sales/transcribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ audio: data.replace(/^data:([^;]+);[^,]*,/, 'data:$1;base64,') }) })
        const j = await r.json().catch(() => ({}))
        if (!r.ok) throw new Error(j.detail || 'Ovozni o\'qib bo\'lmadi')
        m.remove(); setBusy(false); q.value = j.text; ask()
      } catch (err) { m.classList.add('err'); m.textContent = '⚠️ ' + err.message; setBusy(false) }
    }
    rec.start(); mic.classList.add('rec'); recBar.hidden = false; recT.textContent = '0:00'
    rtimer = setInterval(() => { secs++; recT.textContent = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')}`; if (secs >= 120) stopRec(false) }, 1000)
  })
  $('#recX')?.addEventListener('click', () => stopRec(true))

  const setBusy = (v) => {
    busy = v; send.classList.toggle('stop', v); send.setAttribute('aria-label', v ? 'To\'xtatish' : 'Yuborish')
    send.innerHTML = v ? '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" stroke="none"/></svg>'
      : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12h15M13 6l6 6-6 6"/></svg>'
    q.disabled = v
    $('#aicSt').innerHTML = v ? '<i></i>yozmoqda…' : '<i></i>onlayn · matn, ovoz yoki rasm'
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
        body: JSON.stringify({ question: text, history, image, sid }) })
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
            if (x.ok) {
              m.innerHTML = safe(x.answer); hist.push({ role: 'ai', text: x.answer.replace(/<[^>]+>/g, '') }); save()
              if (x.lead) { leadDone = true; ss.set('rp.lead', '1'); const d = document.createElement('div'); d.className = 'lead-ok'; d.textContent = '✅ Arizangiz qabul qilindi — mutaxassisimiz tez orada bog\'lanadi.'; list.appendChild(d) }
              else if (hist.filter(h => h.role === 'ai').length >= 2) leadCard()
            } else { m.classList.add('err'); m.textContent = '⚠️ ' + (x.error || 'Xato'); if (x.detail) console.warn('AI:', x.detail) }
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
