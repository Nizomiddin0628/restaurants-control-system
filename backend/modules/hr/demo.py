"""Demo: lavozimlar, xodim kartalari, bu hafta smenalari, davomat, joriy oy oyligi."""
import random
from datetime import datetime, time, timedelta

from django.utils import timezone

from core.models import Branch, Membership

from .models import Attendance, Employee, Payslip, Position, ShiftPlan, month_start

POS = [("Menejer", "Boshqaruv", "monthly", 6_000_000), ("Kassir", "Kassa", "shift", 180_000), ("Oshpaz", "Oshxona", "monthly", 5_000_000),
       ("Ofitsiant", "Zal", "hourly", 22_000), ("Buxgalter", "Boshqaruv", "monthly", 4_500_000), ("Marketolog", "Boshqaruv", "monthly", 4_000_000)]
ROLE2POS = {"manager": "Menejer", "cashier": "Kassir", "cook": "Oshpaz", "accountant": "Buxgalter", "marketer": "Marketolog", "courier": "Ofitsiant"}


def seed_demo_hr() -> int:
    if Employee.objects.exists():
        return 0
    random.seed(3)
    positions = {n: Position.objects.get_or_create(name=n, defaults={"department": d, "default_salary_type": st, "default_rate": r, "sort_order": i})[0]
                 for i, (n, d, st, r) in enumerate(POS)}
    branch = Branch.objects.filter(deleted_at__isnull=True).first()
    n = 0
    today = timezone.localdate()
    for m in Membership.objects.select_related("user", "role").exclude(role__code="owner"):
        pos = positions.get(ROLE2POS.get(m.role.code, "Ofitsiant"))
        e = Employee.objects.create(user=m.user, position=pos, branch=branch, salary_type=pos.default_salary_type,
                                    rate=pos.default_rate, hire_date=today - timedelta(days=random.randint(40, 700)))
        # bu hafta va o'tgan hafta smenalari
        for d in range(-7, 7):
            day = today + timedelta(days=d)
            if day.weekday() == random.randint(0, 6):
                continue
            ShiftPlan.objects.create(employee=e, branch=branch, date=day, start=time(9, 0), end=time(18, 0) if pos.name != "Kassir" else time(23, 0))
        # o'tgan kunlar davomati
        for d in range(-7, 0):
            day = today + timedelta(days=d)
            if not ShiftPlan.objects.filter(employee=e, date=day).exists():
                continue
            late = random.choice([0, 0, 0, 12, 25])
            cin = timezone.make_aware(datetime.combine(day, time(9, late)))
            Attendance.objects.create(employee=e, branch=branch, check_in=cin, check_out=cin + timedelta(hours=9), late_minutes=late)
        n += 1
    # bugun smenada bo'lganlar
    for e in Employee.objects.all()[:4]:
        Attendance.objects.create(employee=e, branch=branch, check_in=timezone.now() - timedelta(hours=3))
    # joriy oy oyligi (qoralama)
    for e in Employee.objects.all():
        s = Payslip(employee=e, period=month_start(today), salary_type=e.salary_type, rate=e.rate, hours=160, shifts=22, sales_base=0)
        s.compute()
        s.save()
    return n


# ================================================================== ishga olish + profil + baholash (demo)
_C = "https://commons.wikimedia.org/wiki/Special:FilePath/{}?width=640"
VACANCIES = [
    {"title": "Ofitsiant", "role_code": "waiter", "pos": "Ofitsiant", "employment": "shift", "salary_from": 3_500_000, "salary_to": 5_500_000,
     "salary_note": "+ choychaqa (o'rtacha 1–1,5 mln) va KPI bonus", "schedule": "2/2, 10:00–23:00",
     "summary": "Jamoamizga xushmuomala, tez va tartibli ofitsiant kerak. Tajriba bo'lmasa — 2 haftalik o'qitish kursini o'tkazamiz.",
     "requirements": ["18 yoshdan katta", "Xushmuomalalik va ozodalik", "Rus tilini bilish — afzallik", "Tibbiy daftarcha (bo'lmasa — yordam beramiz)"],
     "duties": ["Mehmonlarni kutib olish va joylashtirish", "Menyu bo'yicha maslahat, buyurtma olish (planshetda)", "Stolga xizmat va hisob-kitob", "Zal tozaligi"],
     "benefits": ["Bepul tushlik va kechki ovqat", "Rasmiy ishga joylashtirish", "Bepul forma", "Oylik o'z vaqtida, har oy 5-sanada", "Katta ofitsiantgacha o'sish"],
     "image": "Uzbek_palov_in_Yerevan_Food_Court.jpg", "video": "https://www.youtube.com/watch?v=jBe8e69ypcc", "status": "open",
     "questions": [{"text": "Kechki smenada (23:00 gacha) ishlay olasizmi?", "type": "yesno", "must": "ha"},
                   {"text": "Tibbiy daftarchangiz bormi?", "type": "yesno", "must": ""}, {"text": "Qachondan ishga chiqa olasiz?", "type": "text", "must": ""}]},
    {"title": "Oshpaz yordamchisi", "role_code": "cook", "pos": "Oshpaz", "employment": "full", "salary_from": 4_000_000, "salary_to": 5_000_000,
     "salary_note": "sinov muddatidan keyin oshiriladi", "schedule": "6/1, 08:00–18:00",
     "summary": "Osh va kabob sexiga yordamchi. Katta oshpaz qo'lida hunar o'rganasiz.",
     "requirements": ["Oshxonada 6 oydan tajriba — afzallik", "Pichoq bilan ishlash ko'nikmasi", "Gigiyena qoidalariga rioya", "Tibbiy daftarcha majburiy"],
     "duties": ["Sabzavot va go'sht tayyorlash (zagatovka)", "Zirvak, salatlar", "Ish joyi va inventar tozaligi", "Mahsulotni FIFO bo'yicha joylash"],
     "benefits": ["Bepul ovqat", "Rasmiy ishga joylashtirish", "Oshpazlik kursi — kompaniya hisobidan"],
     "image": "Plov_Tashkent.jpg", "video": "https://www.youtube.com/watch?v=oLTaMPjAgLo", "status": "open",
     "questions": [{"text": "Ertalab 08:00 da ish boshlay olasizmi?", "type": "yesno", "must": "ha"},
                   {"text": "Oshxonada qancha ishlagansiz?", "type": "text", "must": ""}]},
    {"title": "Kassir", "role_code": "cashier", "pos": "Kassir", "employment": "shift", "salary_from": 3_800_000, "salary_to": 4_500_000,
     "salary_note": "", "schedule": "2/2, 09:00–23:00",
     "summary": "Kassada ishlash, mehmonlar bilan muloqot. Kassa dasturini 1 kunda o'rgatamiz.",
     "requirements": ["Diqqatlilik va halollik", "Kompyuter/planshet bilan ishlay olish", "20 yoshdan katta"],
     "duties": ["Buyurtmalarni kassaga kiritish", "Naqd va karta to'lovlarini qabul qilish", "Smena oxirida kassa hisoboti"],
     "benefits": ["Bepul ovqat", "Rasmiy ishga joylashtirish", "Qulay grafik"],
     "image": "Samarqand_noni.jpg", "video": "", "status": "open",
     "questions": [{"text": "Oldin kassada ishlaganmisiz?", "type": "yesno", "must": ""}]},
    {"title": "Kuryer (o'z mashinasi bilan)", "role_code": "courier", "pos": "Ofitsiant", "employment": "part", "salary_from": 0, "salary_to": 0,
     "salary_note": "har yetkazish uchun 15 000 so'm + yoqilg'i", "schedule": "moslashuvchan",
     "summary": "Toshkent bo'ylab buyurtma yetkazish.", "requirements": ["Haydovchilik guvohnomasi (B)", "O'z avtomobili"],
     "duties": ["Buyurtmani o'z vaqtida yetkazish"], "benefits": ["Kunlik to'lov"],
     "image": "Shashlik.jpg", "video": "", "status": "paused", "questions": []},
]
FIRST = ["Aziz", "Bekzod", "Dilnoza", "Feruza", "Javohir", "Kamola", "Laziz", "Madina", "Nigora", "Oybek", "Sevara", "Temur", "Ulug'bek", "Zarina",
         "Shohruh", "Mohira", "Anvar", "Gulchehra"]
LAST_M = ["Rashidov", "Tursunov", "Xolmatov", "Ismoilov", "Abdullayev", "Normatov", "Qodirov", "Mirzayev", "Sobirov"]
PREV = [("«Rayhon» milliy taomlari", "ofitsiant"), ("Evos", "kassir"), ("«Caravan» restorani", "ofitsiant"), ("Safia", "sotuvchi-kassir"),
        ("«Besh qozon» osh markazi", "oshpaz yordamchisi"), ("Oqtepa Lavash", "kassir"), ("«Afsona» restorani", "ofitsiant"),
        ("Chayxana «Navvat»", "oshpaz"), ("KFC Chilonzor", "oshxona xodimi"), ("Bellissimo", "kuryer")]
STAGE_PLAN = [("new", 5), ("screen", 3), ("interview", 3), ("trial", 2), ("offer", 1), ("rejected", 3)]


def _name(rnd, i):
    f = FIRST[i % len(FIRST)]
    last = LAST_M[rnd.randrange(len(LAST_M))]
    female = f in ("Dilnoza", "Feruza", "Kamola", "Madina", "Nigora", "Sevara", "Zarina", "Mohira", "Gulchehra")
    return f"{f} {last + 'a' if female else last}"


def seed_demo_recruit_people(reviewer=None) -> dict:
    """Vakansiyalar + nomzodlar (barcha bosqichlarda) + xodim profili, ish tarixi, hujjatlar, baholar, kayfiyat."""
    from . import recruit
    from .models import (
        REVIEW_CRITERIA,
        Application,
        ApplicationEvent,
        DocKind,
        EmployeeDocument,
        Review,
        ShiftFeedback,
        Stage,
        Vacancy,
        WorkHistory,
    )
    if Vacancy.objects.exists():
        return {"vacancies": 0}
    rnd = random.Random(11)
    now, today = timezone.now(), timezone.localdate()
    branch = Branch.objects.filter(deleted_at__isnull=True).first()
    positions = {p.name: p for p in Position.objects.all()}
    vacs = []
    for v in VACANCIES:
        vacs.append(Vacancy.objects.create(
            title=v["title"], role_code=v["role_code"], position=positions.get(v["pos"]), branch=branch, employment=v["employment"],
            salary_from=v["salary_from"], salary_to=v["salary_to"], salary_note=v["salary_note"], schedule=v["schedule"], summary=v["summary"],
            requirements=v["requirements"], duties=v["duties"], benefits=v["benefits"], image_url=_C.format(v["image"]), video_url=v["video"],
            questions=v["questions"], status=v["status"], responsible=reviewer, views=rnd.randint(40, 380)))
    # --- nomzodlar
    n, i = 0, 0
    places = ["Chilonzor filiali, 2-qavat ofis", "Bosh ofis, menejer xonasi"]
    for stage, cnt in STAGE_PLAN:
        for _ in range(cnt):
            v = vacs[i % 3]
            i += 1
            comp, pos = PREV[rnd.randrange(len(PREV))]
            yes = rnd.random() > (0.5 if stage == "rejected" else 0.1)
            raw = [{"i": k, "a": ("Ha" if yes or k else "Yo'q") if q["type"] == "yesno" else rnd.choice(["Dushanbadan", "Ertadan", "1 haftadan keyin", "2 yil"])}
                   for k, q in enumerate(v.questions)]
            answers, ko = recruit.check_answers(v, raw)
            created = now - timedelta(days=rnd.randint(0, 3) if stage == "new" else rnd.randint(3, 20), hours=rnd.randint(0, 10))
            src = rnd.choice(["site", "site", "telegram", "telegram", "telegram", "referral"])
            a = Application.objects.create(
                vacancy=v, full_name=_name(rnd, i), phone=f"+99893{rnd.randint(1000000, 9999999)}", birth_year=rnd.randint(1990, 2006),
                city="Toshkent", source=src, tg_chat_id=(700000 + i) if src == "telegram" else None,
                tg_username=f"user{700 + i}" if src == "telegram" else "",
                experience=rnd.choice(["", "Tajribam bor, mehmon bilan ishlashni yaxshi ko'raman.", f"{comp}da {rnd.randint(1, 3)} yil ishlaganman.",
                                       "Talabaman, kechki smenalarda ishlamoqchiman."]),
                work_history=[{"company": comp, "position": pos, "years": f"{rnd.randint(2018, 2023)}–{rnd.randint(2024, 2026)}"}],
                answers=answers, knocked_out=ko, stage=stage, rating=rnd.choice([0, 3, 4, 4, 5]) if stage != "new" else 0,
                interview_at=(now + timedelta(days=rnd.randint(1, 4), hours=rnd.randint(-3, 3))) if stage in ("interview", "trial") else None,
                interview_place=places[rnd.randrange(2)] if stage in ("interview", "trial") else "",
                reject_reason=rnd.choice(["Kechki smenaga chiqa olmaydi", "Tajriba yetarli emas", "Maosh kutilmasi yuqori"]) if stage == "rejected" else "",
                notes="Suhbatda yaxshi taassurot qoldirdi." if stage in ("offer", "trial") else "",
                stage_changed_at=created + timedelta(days=1) if stage != "new" else created)
            Application.objects.filter(pk=a.pk).update(created_at=created)
            ApplicationEvent.objects.create(application=a, at=created, kind="created",
                                            text=f"Ariza: {dict(site='sayt', telegram='Telegram bot', referral='xodim tavsiyasi').get(src, src)}")
            if stage != "new":
                ApplicationEvent.objects.create(application=a, at=created + timedelta(days=1), actor=reviewer, kind="stage",
                                                text=f"Bosqich: {Stage(stage).label}" + (f" · {a.reject_reason}" if a.reject_reason else ""))
            n += 1
    # --- mavjud xodimlar: profil, ish tarixi, hujjat, baho, kayfiyat
    emps = list(Employee.objects.filter(is_active=True).select_related("user"))
    first_hired = None
    langs = [["o'zbek", "rus"], ["o'zbek"], ["o'zbek", "rus", "ingliz"]]
    skills = {"Oshpaz": ["osh", "kabob", "zagatovka"], "Kassir": ["kassa", "Excel"], "Ofitsiant": ["xizmat", "upsell"],
              "Menejer": ["jamoa boshqaruvi", "inventarizatsiya"], "Buxgalter": ["1C", "soliq hisoboti"], "Marketolog": ["SMM", "Canva"]}
    this_m = month_start(today)
    prev_m = month_start(this_m - timedelta(days=1))
    for k, e in enumerate(emps):
        pos = e.position.name if e.position_id else "Ofitsiant"
        female = (e.user.full_name or "").split(" ")[-1].endswith("a")
        e.birth_date = today.replace(year=today.year - rnd.randint(20, 42), day=1) + timedelta(days=rnd.randint(0, 27))
        e.gender = "f" if female else "m"
        e.address = rnd.choice(["Chilonzor tumani, 9-kvartal", "Yunusobod tumani, 4-mavze", "Sergeli tumani", "Olmazor tumani, Qorasaroy ko'chasi"])
        e.education = rnd.choice(["O'rta maxsus (kollej)", "Oliy — TDIU", "Oshpazlik kolleji, 2019", "O'rta maktab"])
        e.languages = langs[k % 3]
        e.skills = skills.get(pos, ["xizmat"])
        e.emergency_name = rnd.choice(["Onasi", "Otasi", "Turmush o'rtog'i", "Akasi"])
        e.emergency_phone = e.emergency_phone or f"+99890{rnd.randint(1000000, 9999999)}"
        # tibbiy daftarcha: ko'pchiligi joyida, 2 tasi tugayapti, 1 tasi o'tgan — ogohlantirish ko'rinsin
        e.medical_book_until = today + timedelta(days=(-5 if k == 2 else 12 if k in (4, 7) else rnd.randint(60, 330)))
        e.source = rnd.choice(["vakansiya", "tanish tavsiyasi", "Telegram kanal", "OLX.uz"])
        e.about = "Mas'uliyatli, jamoada yaxshi ishlaydi." if k % 2 else ""
        e.save()
        comp, p = PREV[k % len(PREV)]
        WorkHistory.objects.create(employee=e, company=comp, position=p, start=str(rnd.randint(2016, 2020)), end=str(rnd.randint(2021, 2024)),
                                   reason_left=rnd.choice(["Uyga uzoq edi", "Maosh past edi", "O'qishga kirdi", "Kompaniya yopildi"]),
                                   reference_phone=f"+99897{rnd.randint(1000000, 9999999)}")
        if k % 3 == 0:
            c2, p2 = PREV[(k + 3) % len(PREV)]
            WorkHistory.objects.create(employee=e, company=c2, position=p2, start="2014", end=str(rnd.randint(2015, 2016)))
        EmployeeDocument.objects.create(employee=e, kind=DocKind.CONTRACT, title=f"Mehnat shartnomasi №{100 + k}",
                                        url="https://drive.google.com/file/d/demo-contract/view")
        EmployeeDocument.objects.create(employee=e, kind=DocKind.MEDBOOK, title="Tibbiy daftarcha", expires_on=e.medical_book_until,
                                        url="https://drive.google.com/file/d/demo-medbook/view")
        base = rnd.choice([3, 4, 4, 4, 5, 5])
        for period in (prev_m, this_m):
            if period == this_m and k % 4 == 3:
                continue              # har to'rtinchisi hali baholanmagan
            sc = {c: max(1, min(5, base + rnd.choice([-1, 0, 0, 1]))) for c, _ in REVIEW_CRITERIA}
            Review.objects.create(employee=e, reviewer=reviewer, period=period, scores=sc,
                                  strengths=rnd.choice(["Mehmon bilan muomalasi a'lo", "Tez ishlaydi", "Intizomli", "Jamoaga yordam beradi"]),
                                  improve=rnd.choice(["", "Kechikishni kamaytirish", "Ish joyi tozaligi", "Menyuni yaxshiroq bilish"]),
                                  goals=rnd.choice(["O'rtacha chekni 10% oshirish", "Oy davomida kechikmaslik", "«Gigiyena» kursini tugatish"]))
        mood_base = 2 if k == 5 else rnd.choice([3, 3, 4])       # bittasi «xavf» ostida
        for att in Attendance.objects.filter(employee=e, check_out__isnull=False):
            ShiftFeedback.objects.create(employee=e, attendance=att, date=timezone.localtime(att.check_in).date(),
                                         mood=max(1, min(4, mood_base + rnd.choice([-1, 0, 0, 1]))),
                                         comment=rnd.choice(["", "", "Mehmon ko'p edi", "Oshxonada kechikish bo'ldi"]))
        if first_hired is None and pos in ("Kassir", "Ofitsiant"):
            first_hired = e
    # bitta qabul qilingan nomzod — «qayerdan kelgan» profilda ko'rinsin
    if first_hired:
        hv = vacs[2] if first_hired.position and first_hired.position.name == "Kassir" else vacs[0]
        a = Application.objects.create(vacancy=hv, full_name=first_hired.user.full_name, phone=first_hired.user.phone, birth_year=first_hired.birth_date.year,
                                       source="telegram", stage=Stage.HIRED, rating=5, employee=first_hired,
                                       answers=recruit.check_answers(hv, [{"i": 0, "a": "Ha"}, {"i": 1, "a": "Ha"}, {"i": 2, "a": "Darhol"}])[0],
                                       stage_changed_at=now - timedelta(days=30))
        Application.objects.filter(pk=a.pk).update(created_at=now - timedelta(days=38))
        n += 1
    return {"vacancies": len(vacs), "applications": n, "profiles": len(emps)}
