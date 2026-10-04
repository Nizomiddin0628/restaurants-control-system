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
  if (!reduce) $$('.sec-head, .feat, .plan, .kpi, .dash-grid .ch, .pos, .screens li, .steps li, .stage, .checks li, .score, .help, .atom-box').forEach((el, i) => {
    el.style.opacity = '0'; el.style.transform = 'translateY(16px)'; el.style.filter = 'blur(4px)'
    el.style.transition = 'opacity .9s cubic-bezier(.2,.8,.2,1), transform .9s cubic-bezier(.2,.8,.2,1), filter .9s'
    el.style.transitionDelay = (el.matches('.feat, .plan, .kpi, .ch, .screens li, .steps li, .checks li') ? ([...el.parentElement.children].indexOf(el) % 3) * 90 : 0) + 'ms'
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

  // ---------- ZANJIR: «To'lash» → oltita ekran ketma-ket jonlanadi
  const chain = $('#chain')
  if (chain) {
    const wait = gateFor(chain)
    const pos = $('#pos'), items = $('#posItems'), tot = $('#posTot'), who = $('#posWho'), pay = $('#posPay'), ok = $('#posOk'), drop = $('#drop')
    const dot = $('#chainDot'), fill = $('#chainFill'), rail = $('.rail2', chain), scr = $$('#screens > li')
    const k = (n) => $(`[data-k="${n}"]`, chain)
    const spark = $$('[data-k="spark"] i', chain)
    const sales = [
      { who: 'Dilnoza', items: [['Osh, choyxona ×2', 64000], ['Achchiq-chuchuk', 12000], ['Non ×2', 8000]], disc: 0, stock: ['Guruch', 18.6, .62, '−0,4 kg ayirildi'], tkt: ['#1044', 'Osh ×2, achchiq-chuchuk'], staff: 18, crm: 'Aziz K.' },
      { who: 'Jasur', items: [['Shashlik (qo\'y) ×6', 108000], ['Lag\'mon ×2', 56000], ['Kompot ×2', 16000]], disc: 9000, stock: ['Go\'sht', 23.4, .5, '−1,2 kg ayirildi'], tkt: ['#1045', 'Shashlik ×6, lag\'mon ×2'], staff: 26, crm: 'Malika R.' },
      { who: 'Nodira', items: [['Manti ×10', 70000], ['Sho\'rva ×2', 44000], ['Choy', 6000]], disc: 0, stock: ['Un', 41, .74, '−1,5 kg ayirildi'], tkt: ['#1046', 'Manti ×10, sho\'rva ×2'], staff: 21, crm: 'Bobur T.' },
    ]
    let rev = 8420000, pro = 2930000, si = 0, tt = 0
    const place = (i) => {
      if (getComputedStyle(rail).display === 'none') return
      const rr = rail.getBoundingClientRect(), r = scr[i].getBoundingClientRect(), x = r.left + r.width / 2 - rr.left
      dot.style.left = x + 'px'; fill.style.width = x + 'px'
    }
    const tktTimer = () => { clearInterval(tt); let sec = 0; const e = k('tktT'); e.textContent = '0:00'; tt = setInterval(() => { sec += 7; e.textContent = `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}` }, 1000) }
    const fire = (i, s, total) => {
      scr[i].classList.add('on')
      if (i === 0) { $('.stk span', scr[0]).textContent = s.stock[0]; k('stockV').textContent = String(s.stock[1]).replace('.', ',') + ' kg'; k('stockB').style.setProperty('--w', s.stock[2]); setTimeout(() => { k('stockV').textContent = String(+(s.stock[1] - .4).toFixed(1)).replace('.', ',') + ' kg'; k('stockB').style.setProperty('--w', s.stock[2] - .05) }, 350); k('stockN').textContent = s.stock[3] }
      if (i === 1) { k('tktN').textContent = s.tkt[0]; k('tktI').textContent = s.tkt[1]; tktTimer() }
      if (i === 2) { rev += total; tween(k('cash'), rev, { dur: 1100 }); const hs = spark.map(b => parseFloat(b.style.getPropertyValue('--h'))); hs.shift(); hs.push(.5 + Math.random() * .5); spark.forEach((b, j) => b.style.setProperty('--h', hs[j].toFixed(2))) }
      if (i === 3) { pro += Math.round(total * .36); tween(k('profit'), pro, { dur: 1100 }); k('pfill').style.setProperty('--w', (.33 + Math.random() * .05).toFixed(2)) }
      if (i === 4) { k('whoN').textContent = s.who; k('avt').textContent = s.who[0]; tween(k('whoC'), s.staff + 1, { from: s.staff, dur: 600 }) }
      if (i === 5) { k('crmN').textContent = s.crm; tween(k('bonus'), Math.round(total / 100), { prefix: '+', from: 0, dur: 900 }) }
    }
    const reset = () => { scr.forEach(x => x.classList.remove('on')); dot.classList.remove('on'); fill.style.width = '0'; pos.classList.remove('paid'); ok.classList.remove('on'); drop.classList.remove('go'); clearInterval(tt) }
    addEventListener('resize', () => { let i = -1; scr.forEach((x, j) => { if (x.classList.contains('on')) i = j }); if (i >= 0) { dot.style.transition = fill.style.transition = 'none'; place(i); requestAnimationFrame(() => { dot.style.transition = fill.style.transition = '' }) } })
    ;(async () => {
      for (;;) {
        const s = sales[si++ % sales.length], total = s.items.reduce((a, [, p]) => a + p, 0) - s.disc
        reset(); who.textContent = s.who
        items.innerHTML = s.items.map(([n, p], i) => `<li style="animation-delay:${i * 140}ms">${n}<em>${fmt(p)}</em></li>`).join('') + (s.disc ? `<li class="disc" style="animation-delay:${s.items.length * 140}ms">Chegirma<em>−${fmt(s.disc)}</em></li>` : '')
        tween(tot, total, { from: 0, dur: 700 })
        await wait(1600)
        pay.classList.add('press'); await wait(420); pay.classList.remove('press'); pos.classList.add('paid'); ok.classList.add('on')
        drop.classList.add('go'); await wait(480)
        dot.classList.add('on')
        for (let i = 0; i < scr.length; i++) { place(i); await wait(i ? 800 : 450); fire(i, s, total) }
        await wait(3800)
        if (reduce) break
      }
    })()
  }

  // ---------- ATOM: bo'limlar yadro atrofida elliptik orbitalarda
  const cvA = $('#atom')
  if (cvA) {
    const ctx = cvA.getContext('2d'), card = $('#atomCard'), tk = $('#tk')
    const MODS = [
      ['Kassa', '--herb', 'kassa', ['Chek #1047 — 92 000 so\'m', 'Smena ochildi', 'Kassa topshirildi, farq yo\'q']],
      ['Oshxona', '--ember', 'kds', ['Buyurtma #1047 tushdi', '#1045 tayyor — 6:40 da', 'Stol 4: Osh ×2']],
      ['Ombor', '--teal', 'stock', ['Guruch −0,4 kg', 'Qoldiq yangilandi', 'Yog\' tugayapti — ogohlantirish']],
      ['Zakup', '--cyan', 'stock', ['Bozorlik: 1 840 000 so\'m', 'Ta\'minotchiga buyurtma', 'Qarz to\'landi']],
      ['Xodimlar', '--cyan', 'staff', ['Nodira keldi — 08:57', 'Jasur: 27 chek', 'Smena jadvali saqlandi']],
      ['Telegram', '--tg', 'tg', ['Vazifa yuborildi', '«Keldim» qabul qilindi', 'Kassa qabul tasdiqlandi']],
      ['Sayt', '--tg', 'tg', ['QR menyudan buyurtma', 'Stop-list yangilandi', 'Menyu e\'lon qilindi']],
      ['Bron', '--rose', 'task', ['Stol 7 — 19:00 bron', 'Bron tasdiqlandi', 'Zalda 3 ta bo\'sh stol']],
      ['Mijozlar', '--rose', 'gift', ['+840 bonus yozildi', 'Yangi mijoz', 'Xabar tarqatildi']],
      ['Hisobotlar', '--acc', 'rep', ['Foyda qayta hisoblandi', 'Z-hisobot saqlandi', 'Food cost: 29%']],
      ['Filiallar', '--acc', 'rep', ['Chilonzor yangilandi', 'Sergeli: smena yopildi', 'Narxlar sinxronlandi']],
      ['AI Kotib', '--violet', 'ai', ['Ertalabki hisobot yuborildi', '«Kecha qancha savdo?» — javob', 'Diagramma chizildi']],
    ]
    const ROT = [0, Math.PI / 6, -Math.PI / 6, Math.PI / 2], SPD = [.4, -.32, .28, -.36]   // orbita burchagi va tezligi
    let W = 0, H = 0, ORB = [], cx = 0, cy = 0, els = [], sparks = [], pings = [], colors = {}, ink = '', surf = '', line = '', run = false, raf = 0, last = 0, active = 0, auto = true, t = 0, below = false
    const readColors = () => { MODS.forEach(m => { colors[m[1]] = css(m[1]) }); ink = css('--ink'); surf = css('--surface'); line = css('--line') }
    const build = () => {
      const r = cvA.getBoundingClientRect(), dpr = Math.min(2, devicePixelRatio || 1); W = r.width; H = r.height
      cvA.width = W * dpr; cvA.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      below = W < 700
      cx = W / 2; cy = H / 2 - (below ? 36 : 26)
      const mx = W / 2 - (below ? 44 : 96), my = cy - (below ? 40 : 34), ratio = .36   // yorliqlar uchun joy
      ORB = ROT.map(rot => {   // har orbita ramkaga sig'adigan qilib hisoblanadi
        const c = Math.abs(Math.cos(rot)), sn = Math.abs(Math.sin(rot))
        const ax = mx / Math.sqrt(c * c + ratio * ratio * sn * sn), ay = my / Math.sqrt(sn * sn + ratio * ratio * c * c)
        const A = Math.min(ax, ay); return [rot, A, A * ratio]
      })
      if (!els.length) els = MODS.map((m, i) => ({ i, o: i % 4, ph: Math.floor(i / 4) * (Math.PI * 2 / 3) + (i % 4) * .55, trail: [], x: cx, y: cy, d: 1 }))
      els.forEach(e => { e.trail = [] })
      readColors()
    }
    const posOf = (e) => {
      const [rot, A, B] = ORB[e.o], th = e.ph + SPD[e.o] * t, x0 = A * Math.cos(th), y0 = B * Math.sin(th)
      e.x = cx + x0 * Math.cos(rot) - y0 * Math.sin(rot); e.y = cy + x0 * Math.sin(rot) + y0 * Math.cos(rot); e.d = (Math.sin(th) + 1) / 2   // 0 — orqada, 1 — oldinda
    }
    const rr = (x, y, w, h, r) => { ctx.beginPath(); if (ctx.roundRect) ctx.roundRect(x, y, w, h, r); else ctx.rect(x, y, w, h) }
    const node = (e) => {
      const m = MODS[e.i], col = colors[m[1]], on = e.i === active, s = .72 + .28 * e.d, al = .4 + .6 * e.d
      for (let j = 1; j < e.trail.length; j++) { ctx.strokeStyle = col; ctx.globalAlpha = (j / e.trail.length) * al * (on ? .8 : .4); ctx.lineWidth = (j / e.trail.length) * (on ? 3.5 : 2.2) * s; ctx.beginPath(); ctx.moveTo(e.trail[j - 1][0], e.trail[j - 1][1]); ctx.lineTo(e.trail[j][0], e.trail[j][1]); ctx.stroke() }
      ctx.globalAlpha = al
      if (on) { const g = ctx.createRadialGradient(e.x, e.y, 4, e.x, e.y, 34 * s); g.addColorStop(0, col); g.addColorStop(1, 'rgba(0,0,0,0)'); ctx.globalAlpha = al * .45; ctx.fillStyle = g; ctx.beginPath(); ctx.arc(e.x, e.y, 34 * s, 0, 6.2832); ctx.fill(); ctx.globalAlpha = al }
      ctx.fillStyle = surf; ctx.strokeStyle = col; ctx.lineWidth = on ? 3 : 2; ctx.beginPath(); ctx.arc(e.x, e.y, (on ? 11 : 8) * s, 0, 6.2832); ctx.fill(); ctx.stroke()
      ctx.fillStyle = col; ctx.beginPath(); ctx.arc(e.x, e.y, (on ? 4.5 : 3.2) * s, 0, 6.2832); ctx.fill()
      const fs = Math.round((below ? 12 : 14) * (.86 + .14 * e.d)); ctx.font = `${on ? 800 : 600} ${fs}px Onest, system-ui`
      const tw = ctx.measureText(m[0]).width, px = 10, bw = tw + px * 2, bh = fs + 12, bx = below ? e.x - bw / 2 : e.x + 14 * s, by = below ? e.y + 12 * s : e.y - bh / 2
      ctx.fillStyle = on ? col : surf; ctx.strokeStyle = on ? col : line; ctx.lineWidth = 1; rr(bx, by, bw, bh, bh / 2); ctx.fill(); ctx.stroke()
      ctx.fillStyle = on ? '#fff' : ink; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(m[0], bx + px, by + bh / 2 + 1)
      ctx.globalAlpha = 1
    }
    const draw = (now) => {
      const dt = Math.min(50, now - (last || now)) / 1000; last = now; t += dt
      ctx.clearRect(0, 0, W, H)
      ORB.forEach(([rot, A, B]) => { ctx.save(); ctx.translate(cx, cy); ctx.rotate(rot); ctx.strokeStyle = line; ctx.lineWidth = 1; ctx.setLineDash([3, 7]); ctx.beginPath(); ctx.ellipse(0, 0, A, B, 0, 0, 6.2832); ctx.stroke(); ctx.restore() })
      ctx.setLineDash([])
      els.forEach(e => { posOf(e); e.trail.push([e.x, e.y]); if (e.trail.length > 24) e.trail.shift() })
      const back = els.filter(e => e.d < .5).sort((a, b) => a.d - b.d), front = els.filter(e => e.d >= .5).sort((a, b) => a.d - b.d)
      back.forEach(node)
      // yadro
      const R = 34 * (1 + Math.sin(t * 1.8) * .04), acc = colors['--acc']
      pings = pings.filter(p => p.t < 1)
      pings.forEach(p => { p.t += dt * .9; ctx.globalAlpha = (1 - p.t) * .5; ctx.strokeStyle = colors[MODS[active][1]]; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(cx, cy, R + p.t * 80, 0, 6.2832); ctx.stroke() })
      const halo = ctx.createRadialGradient(cx, cy, R * .6, cx, cy, R * 2.8); halo.addColorStop(0, acc); halo.addColorStop(1, 'rgba(0,0,0,0)')
      ctx.globalAlpha = .2 + Math.sin(t * 1.8) * .05; ctx.fillStyle = halo; ctx.beginPath(); ctx.arc(cx, cy, R * 2.8, 0, 6.2832); ctx.fill()
      ;[[R + 11, t * .5], [R + 21, -t * .35]].forEach(([r, a]) => { ctx.save(); ctx.translate(cx, cy); ctx.rotate(a); ctx.strokeStyle = acc; ctx.globalAlpha = .35; ctx.lineWidth = 1.2; ctx.setLineDash([10, 14]); ctx.beginPath(); ctx.arc(0, 0, r, 0, 6.2832); ctx.stroke(); ctx.restore() })
      ctx.setLineDash([]); ctx.globalAlpha = 1
      const g = ctx.createRadialGradient(cx - 10, cy - 12, 4, cx, cy, R); g.addColorStop(0, colors['--cyan']); g.addColorStop(.6, acc); g.addColorStop(1, colors['--violet'])
      ctx.fillStyle = g; ctx.shadowColor = acc; ctx.shadowBlur = 30; ctx.beginPath(); ctx.arc(cx, cy, R, 0, 6.2832); ctx.fill(); ctx.shadowBlur = 0
      ctx.fillStyle = '#fff'; ctx.font = '700 22px Unbounded, Onest, system-ui'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('R', cx, cy + 1)
      // uchqunlar: bo'limdan yadroga
      sparks = sparks.filter(p => p.t < 1.05)
      sparks.forEach(p => {
        p.t += dt * 1.25; if (p.t < 0) return
        const e = els[p.i], kk = easeInOut(clamp(p.t, 0, 1)), x = lerp(e.x, cx, kk), y = lerp(e.y, cy, kk), col = colors[MODS[p.i][1]]
        p.tr.push([x, y]); if (p.tr.length > 12) p.tr.shift()
        for (let j = 1; j < p.tr.length; j++) { ctx.globalAlpha = j / p.tr.length; ctx.strokeStyle = col; ctx.lineWidth = (j / p.tr.length) * 3; ctx.beginPath(); ctx.moveTo(p.tr[j - 1][0], p.tr[j - 1][1]); ctx.lineTo(p.tr[j][0], p.tr[j][1]); ctx.stroke() }
        ctx.globalAlpha = 1; ctx.fillStyle = col; ctx.shadowColor = col; ctx.shadowBlur = 12; ctx.beginPath(); ctx.arc(x, y, 3, 0, 6.2832); ctx.fill(); ctx.shadowBlur = 0
        if (p.t >= 1 && !p.done) { p.done = true; pings.push({ t: 0 }) }
      })
      front.forEach(node)
      if (run) raf = requestAnimationFrame(draw)
    }
    const setActive = (i, user = false) => {
      active = i; const m = MODS[i]
      if (user) { auto = false; clearTimeout(setActive.t); setActive.t = setTimeout(() => { auto = true }, 9000) }
      for (let j = 0; j < 3; j++) sparks.push({ i, t: -j * .14, tr: [] })
      card.classList.remove('sw'); void card.offsetWidth; card.classList.add('sw')
      setTimeout(() => { card.querySelector('.ic').className = 'ic ' + m[2]; card.querySelector('b').textContent = m[0]; card.querySelector('span').textContent = m[3][Math.floor(Math.random() * 3)] }, 200)
    }
    cvA.addEventListener('click', (e) => { const r = cvA.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top; let best = -1, bd = 56; els.forEach(el => { const d = Math.hypot(el.x + (below ? 0 : 30) - x, el.y + (below ? 18 : 0) - y); if (d < bd) { bd = d; best = el.i } }); if (best >= 0) setActive(best, true) })
    cvA.style.cursor = 'pointer'
    const fillTk = () => { if (!tk) return; const html = MODS.flatMap(m => m[3].map(x => `<span style="--c:${css(m[1])}"><i></i><b>${m[0]}</b>${x}</span>`)).join(''); tk.innerHTML = html + html }
    fillTk()
    themeListeners.push(() => { readColors(); fillTk(); if (reduce) requestAnimationFrame(draw) })
    let rtA = 0; addEventListener('resize', () => { clearTimeout(rtA); rtA = setTimeout(() => { build(); if (!run) requestAnimationFrame(draw) }, 150) })
    build(); setActive(0)
    let cyc = 0
    visible(cvA, (v) => {
      if (v && !reduce) { if (!run) { run = true; last = 0; raf = requestAnimationFrame(draw) } if (!cyc) cyc = setInterval(() => { if (auto && !document.hidden) setActive((active + 1) % MODS.length) }, 3000) }
      else { run = false; cancelAnimationFrame(raf); clearInterval(cyc); cyc = 0; if (reduce) requestAnimationFrame(draw) }
    }, .1)
  }

  // ---------- solishtirish: «biz bilan bunga erishasiz» — tez-tez almashadi
  const achv = $('#achv')
  if (achv) {
    const slides = $$('.as', achv), bar = $('.achv-bar i', achv)
    let ai = 0
    const show = (n) => {
      slides.forEach((s, j) => { if (s.classList.contains('on') && j !== n) { s.classList.remove('on'); s.classList.add('out') } s.classList.toggle('on', j === n) })
      setTimeout(() => slides.forEach(s => s.classList.remove('out')), 650)
      if (bar) { bar.classList.remove('run'); void bar.offsetWidth; bar.classList.add('run') }
    }
    show(0)
    if (!reduce) { const wait = gateFor(achv); (async () => { for (;;) { await wait(3000); ai = (ai + 1) % slides.length; show(ai) } })() }
  }

  // ---------- BIR KUN: har soat — o'z sahnasi
  const dayb = $('#dayb')
  if (dayb) {
    const steps = $$('#daySteps li'), scenes = $$('#dayStage .scene'), wait = gateFor(dayb), DUR = 5400
    const mln = (n) => (n / 1e6).toFixed(1).replace('.', ',') + ' mln'
    let timers = [], cur = -1, hold = 0
    const later = (fn, ms) => timers.push(setTimeout(fn, ms))
    const counts = (sc) => $$('[data-n]', sc).forEach((el, j) => later(() => {
      const to = +el.dataset.n
      if (el.dataset.f === 'mln') { const t0 = performance.now(); const step = (now) => { const kk = clamp((now - t0) / 1100, 0, 1); el.textContent = mln(lerp(0, to, easeOut(kk))); if (kk < 1) requestAnimationFrame(step) }; requestAnimationFrame(step) }
      else tween(el, to, { from: 0, dur: 1000 })
    }, 300 + j * 120))
    const fx = [
      null,
      () => $$('#shop li').forEach((li, j) => later(() => li.classList.add('ok'), 1100 + j * 420)),
      (sc) => { $$('#tmap i').forEach((tb, j) => later(() => tb.classList.add('busy'), 600 + ((j * 7) % 12) * 190)); $$('.tk2 small', sc).forEach((s) => { let sec = 0; timers.push(setInterval(() => { sec += 9; s.textContent = `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}` }, 1000)) }) },
      () => { $$('#tst li').forEach((li, j) => later(() => li.classList.add('on'), 600 + j * 950)); later(() => $('#tphoto').classList.add('on'), 2700) },
      null, null,
    ]
    const show = (i) => {
      timers.forEach(x => { clearTimeout(x); clearInterval(x) }); timers = []
      cur = i
      steps.forEach(s => s.classList.remove('on')); void dayb.offsetWidth
      steps.forEach((s, j) => { s.classList.toggle('on', j === i); s.classList.toggle('done', j < i); s.style.setProperty('--d', DUR + 'ms') })
      scenes.forEach((s, j) => { s.classList.toggle('on', j === i); if (j !== i) { $$('.ok, .busy, .on', s).forEach(x => x.classList.remove('ok', 'busy', 'on')); $$('.tk2 small', s).forEach(x => { x.textContent = '0:00' }) } })
      counts(scenes[i]); fx[i]?.(scenes[i])
    }
    steps.forEach((s, j) => s.addEventListener('click', () => { show(j); hold = Date.now() + 9000 }))
    show(0)
    if (!reduce) (async () => { for (;;) { await wait(DUR); if (Date.now() < hold) { await wait(800); continue } show((cur + 1) % scenes.length) } })()
  }

  // ---------- PANEL: davr tanlanadi, chiziq chiziladi, kursor o'zi yuradi
  const dash = $('#dash')
  if (dash) {
    const svg = $('#lineSvg'), tip = $('#lineTip'), xl = $('#xl'), per = $('#chPeriod'), tabs = $$('#dashTabs button')
    const MON = ['yan', 'fev', 'mar', 'apr', 'may', 'iyun', 'iyul', 'avg', 'sen', 'okt', 'noy', 'dek']
    const seed = (q) => { const x = Math.sin(q * 12.9898 + 78.233) * 43758.5453; return x - Math.floor(x) }
    const gen = (n) => { const out = [], today = new Date(); for (let i = 0; i < n; i++) { const d = new Date(today); d.setDate(today.getDate() - (n - 1 - i)); const wk = d.getDay(); out.push({ d, v: Math.max(6, 9.5 + (i / n) * 3.2 + ((wk === 5 || wk === 6) ? 1.8 : wk === 0 ? .9 : 0) + (seed(i + n * 7) - .5) * 1.6) }) } return out }
    const DELTA = { 7: ['+6%', '+4%', '+2%'], 30: ['+12%', '+9%', '+3%'], 90: ['+21%', '+15%', '+5%'] }
    let data = [], pts = [], scan = 0, hover = false
    const smooth = (p) => { let d = `M${p[0][0]} ${p[0][1]}`; for (let i = 0; i < p.length - 1; i++) { const p0 = p[Math.max(0, i - 1)], p1 = p[i], p2 = p[i + 1], p3 = p[Math.min(p.length - 1, i + 2)]; d += ` C${(p1[0] + (p2[0] - p0[0]) / 6).toFixed(1)} ${(p1[1] + (p2[1] - p0[1]) / 6).toFixed(1)}, ${(p2[0] - (p3[0] - p1[0]) / 6).toFixed(1)} ${(p2[1] - (p3[1] - p1[1]) / 6).toFixed(1)}, ${p2[0]} ${p2[1]}` } return d }
    const K = (q) => $(`[data-kpi="${q}"]`, dash)
    const placeCur = (i) => {
      if (!pts[i]) return
      const [x, y] = pts[i], cl = $('#curL'), cd = $('#curD')
      if (cl) { cl.style.transform = `translate(${x}px, 0)`; cd.style.transform = `translate(${x}px, ${y}px)` }
      const r = svg.getBoundingClientRect(); tip.style.left = (x / 600 * r.width) + 'px'; tip.style.top = (y / 220 * r.height) + 'px'
      tip.innerHTML = `${data[i].d.getDate()} ${MON[data[i].d.getMonth()]} · <b>${data[i].v.toFixed(1).replace('.', ',')} mln</b>`; tip.classList.add('on')
    }
    const render = (n) => {
      data = gen(n); const max = Math.max(...data.map(x => x.v)) * 1.1, min = Math.min(...data.map(x => x.v)) * .82
      pts = data.map((x, i) => [+(i / (n - 1) * 600).toFixed(1), +(200 - (x.v - min) / (max - min) * 180).toFixed(1)])
      const d = smooth(pts)
      svg.innerHTML = `<defs><linearGradient id="dashArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${css('--acc')}" stop-opacity=".32"/><stop offset="1" stop-color="${css('--acc')}" stop-opacity="0"/></linearGradient></defs>
        <g class="grid"><path d="M0 40H600M0 100H600M0 160H600"/></g><path fill="url(#dashArea)" d="${d} L600 220 L0 220Z"/><path class="ln2" id="ln2" pathLength="1" d="${d}"/>
        <g class="cur" id="curL"><line x1="0" x2="0" y1="0" y2="215"/></g><g class="curd" id="curD"><circle r="6"/></g>`
      const ln = $('#ln2'); ln.style.strokeDasharray = '1'; ln.style.strokeDashoffset = '1'; ln.getBoundingClientRect(); ln.style.transition = reduce ? '' : 'stroke-dashoffset 1.8s cubic-bezier(.65,0,.35,1)'; ln.style.strokeDashoffset = '0'
      const stepN = n > 30 ? 15 : n > 7 ? 5 : 1
      xl.innerHTML = data.filter((_, i) => i % stepN === 0 || i === n - 1).map(x => `<span>${x.d.getDate()} ${MON[x.d.getMonth()]}</span>`).join('')
      per.textContent = `mln so'm · ${n} kun`
      const rev = data.reduce((a, x) => a + x.v, 0), cnt = Math.round(rev * 1e6 / 129000), avg = Math.round(rev * 1e6 / cnt)
      const t0 = performance.now(), from = parseFloat(K('rev').dataset.v || '0'); K('rev').dataset.v = rev
      const f = (now) => { const kk = clamp((now - t0) / 1000, 0, 1); K('rev').textContent = lerp(from, rev, easeOut(kk)).toFixed(1).replace('.', ',') + ' mln'; if (kk < 1) requestAnimationFrame(f) }; requestAnimationFrame(f)
      tween(K('cnt'), cnt, { dur: 1000 }); tween(K('avg'), avg, { dur: 1000, suffix: ' so\'m' })
      const dl = DELTA[n]; K('revD').textContent = dl[0] + ' oldingi davrga'; K('cntD').textContent = dl[1]; K('avgD').textContent = dl[2]
      const sp = data.slice(-14).map((x, i, a) => [+(i / (a.length - 1) * 90).toFixed(1), +(32 - (x.v - min) / (max - min) * 28).toFixed(1)]), spd = smooth(sp)
      $('#spL').setAttribute('d', spd); $('#spA').setAttribute('d', spd + ' L90 34 L0 34Z')
      scan = n - 1; placeCur(scan)
    }
    tabs.forEach(b => b.addEventListener('click', () => { tabs.forEach(x => x.classList.toggle('on', x === b)); render(+b.dataset.p) }))
    svg.addEventListener('pointermove', (e) => { hover = true; const r = svg.getBoundingClientRect(); placeCur(clamp(Math.round((e.clientX - r.left) / r.width * (pts.length - 1)), 0, pts.length - 1)) })
    svg.addEventListener('pointerleave', () => { hover = false })
    themeListeners.push(() => render(+($('#dashTabs .on')?.dataset.p || 30)))
    render(30)
    once(dash, () => dash.classList.add('in'), .2)
    if (!reduce) { const wait = gateFor(dash); (async () => { for (;;) { await wait(1400); if (hover) continue; scan = (scan + 1) % pts.length; placeCur(scan) } })() }
  }

  // ---------- narx: raqam sanaladi, kunlik hisob
  $$('.price > b[data-count]').forEach(b => { const d = b.closest('.plan')?.querySelector('[data-day]'); if (d) d.textContent = '$' + (+b.dataset.count / 30).toFixed(1).replace('.', ',') })
  once($('.plans'), () => $$('.price > b[data-count]').forEach((b, i) => setTimeout(() => tween(b, +b.dataset.count, { from: 0, dur: 1300 }), i * 150)), .3)

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
