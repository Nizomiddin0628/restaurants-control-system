"""Demo: 3 kurs (burger standarti, gigiyena, mehmonga xizmat), testlar, standartlar, topshiriqlar va xodimlar progressi."""
from __future__ import annotations

import random
from datetime import timedelta

from django.utils import timezone

from core.models import User

from . import services
from .models import (
    Assignment,
    Course,
    Lesson,
    LessonProgress,
    Question,
    Quiz,
    Standard,
    StandardAck,
    Submission,
    SubmissionStatus,
)

COURSES = [
    {
        "title": "Burger tayyorlash standarti", "category": "Oshxona", "roles": ["cook", "manager"], "due_days": 7,
        "description": "Kotletdan tortib qadoqlashgacha — har bir burger bir xil ta'm va ko'rinishda bo'lishi uchun.",
        "lessons": [
            ("Kerakli mahsulotlar va jihozlar", "Burger uchun kerakli mahsulotlar, ularning saqlash harorati va ish joyini tayyorlash.",
             ["Mol go'shti qiymasi (80/20)", "Bulochka, sous, sabzavotlar", "Grill va termometr", "Qo'lqop va fartuk"]),
            ("Burger kotletini tayyorlash", "Bu darsda burger kotletini to'g'ri tayyorlash, harorat va vaqt standartlarini o'rganasiz.",
             ["Kerakli mahsulotlar", "Tayyorlash bosqichlari", "Sifat standartlari", "Xatolar va yechimlar"]),
            ("Yig'ish tartibi", "Qatlamlar ketma-ketligi: pastki bulochka → sous → salat → kotlet → pishloq → pomidor → piyoz → ustki bulochka.",
             ["Sous miqdori — 20 g", "Pishloq kotlet issiqligida eriydi", "Burger 90 soniyada yig'iladi"]),
            ("Qadoqlash va berish", "Burger qog'ozga o'raladi, qutiga solinadi, 2 daqiqa ichida mijozga beriladi.",
             ["Qog'oz — logotip tashqarida", "Chekda buyurtma raqami", "Issiq holda berish"]),
            ("Xatolar va yechimlar", "Eng ko'p uchraydigan 5 xato: xom kotlet, ko'p sous, sovuq bulochka, ezilgan burger, noto'g'ri qadoqlash.",
             ["Termometr bilan tekshirish", "Porsiya qoshig'i", "Bulochkani qizdirish"]),
        ],
        "quiz": ("Burger standarti — yakuniy test", 300, [
            ("Burger kotletining ideal ichki harorati necha gradus?", ["55°C", "65°C", "72°C", "80°C"], 2, "Mol go'shti xavfsiz bo'lishi uchun ichki harorat 72°C ga yetishi kerak."),
            ("Kotlet uchun qiymaning yog'liligi qancha bo'lishi kerak?", ["95/5", "80/20", "60/40", "50/50"], 1, "80/20 — sershira va mazali kotlet uchun standart."),
            ("Bitta burgerga qancha sous qo'yiladi?", ["5 g", "20 g", "50 g", "Xohlagancha"], 1, "Standart — 20 g, porsiya qoshig'i bilan."),
            ("Kotlet grillda har tomondan necha daqiqa pishiriladi?", ["1 daqiqa", "3–4 daqiqa", "10 daqiqa", "15 daqiqa"], 1, "3–4 daqiqa, keyin termometr bilan tekshiriladi."),
            ("Tayyor burger mijozga necha daqiqa ichida berilishi kerak?", ["2 daqiqa", "10 daqiqa", "20 daqiqa", "Farqi yo'q"], 0, "Issiq holda — 2 daqiqa ichida."),
            ("Pishloq qachon qo'yiladi?", ["Kotlet sovugach", "Kotlet grilldan olingan zahoti", "Qadoqlashda", "Qo'yilmaydi"], 1, "Issiq kotlet ustida pishloq o'zi eriydi."),
            ("Xom go'sht bilan ishlagandan keyin nima qilinadi?", ["Hech narsa", "Qo'lqop almashtiriladi va qo'les yuviladi", "Fartuk yechiladi", "Suv ichiladi"], 1, "Aralash ifloslanish (cross-contamination) oldini olish uchun."),
            ("Qiyma muzlatgichda qanday haroratda saqlanadi?", ["+10°C", "0…+4°C", "+15°C", "Xona haroratida"], 1, "Sovutgich: 0…+4°C."),
            ("Burger qatlamlarida kotletdan keyin nima keladi?", ["Salat", "Pishloq", "Bulochka", "Sous"], 1, "Kotlet → pishloq → pomidor → piyoz."),
            ("Kotlet ichi pushti bo'lsa nima qilasiz?", ["Mijozga beraman", "Yana pishiraman va termometr bilan tekshiraman", "Sous qo'shaman", "Tashlab yuboraman"], 1, "72°C ga yetguncha pishiriladi."),
        ]),
    },
    {
        "title": "Gigiyena va sanitariya", "category": "Gigiyena", "everyone": True, "due_days": 3,
        "description": "Har bir xodim uchun majburiy: qo'les yuvish, forma, oziq-ovqat xavfsizligi.",
        "lessons": [
            ("Qo'lni to'g'ri yuvish", "Qo'les kamida 20 soniya sovun bilan yuviladi: ish boshlashdan oldin, xom mahsulotdan keyin, hojatxonadan keyin.",
             ["20 soniya sovun bilan", "Tirnoq ostini tozalash", "Bir martalik sochiq"]),
            ("Forma va tashqi ko'rinish", "Toza forma, bosh kiyim, taqinchoqlarsiz, tirnoq kalta.", ["Bosh kiyim majburiy", "Uzuk, soat taqilmaydi"]),
            ("Mahsulotlarni saqlash", "FIFO qoidasi: birinchi kelgan — birinchi ishlatiladi. Har idishda sana yozuvi.", ["FIFO", "Yorliq: nomi va sanasi", "Xom va tayyor alohida"]),
        ],
        "quiz": ("Gigiyena testi", 180, [
            ("Qo'les kamida necha soniya yuviladi?", ["5", "10", "20", "60"], 2, "Kamida 20 soniya sovun bilan."),
            ("FIFO nimani anglatadi?", ["Birinchi kelgan — birinchi ishlatiladi", "Eng yangi birinchi", "Tasodifiy", "Eng arzoni birinchi"], 0, "First In, First Out."),
            ("Oshxonada uzuk taqish mumkinmi?", ["Ha", "Yo'q", "Faqat nikoh uzugi", "Faqat bayramda"], 1, "Taqinchoqlar ostida bakteriya to'planadi."),
            ("Xom go'sht va tayyor ovqat qanday saqlanadi?", ["Birga", "Alohida, xom — pastki tokchada", "Farqi yo'q", "Xom — yuqorida"], 1, "Xom mahsulot suvi tayyor ovqatga tommasligi kerak."),
        ]),
    },
    {
        "title": "Mehmonga xizmat ko'rsatish", "category": "Zal", "roles": ["waiter", "cashier"], "due_days": 10,
        "description": "Mehmonni kutib olishdan xayrlashishgacha — 5 yulduzli xizmat standarti.",
        "lessons": [
            ("Kutib olish", "Mehmon kirgach 30 soniya ichida salomlashing va stolga kuzatib qo'ying.", ["Tabassum", "30 soniya qoidasi", "Menyu darhol beriladi"]),
            ("Buyurtma qabul qilish", "Buyurtmani takrorlab tasdiqlang, qo'shimcha taklif qiling (ichimlik, desert).", ["Takrorlash", "Upsell", "Allergiya haqida so'rash"]),
            ("Shikoyat bilan ishlash", "Tinglang → uzr so'rang → yechim taklif qiling → menejerga xabar bering.", ["Bahslashmang", "Yechim taklif qiling"]),
            ("Hisob-kitob va xayrlashish", "Hisobni 2 daqiqada olib keling, rahmat ayting va yana taklif qiling.", ["Chek to'g'riligini tekshiring", "Xayrlashish"]),
        ],
        "quiz": ("Xizmat ko'rsatish testi", 0, [
            ("Mehmon kirgach necha soniya ichida salomlashish kerak?", ["30", "120", "300", "Salomlashish shart emas"], 0, "30 soniya qoidasi."),
            ("Mehmon shikoyat qilsa birinchi nima qilasiz?", ["Bahslashaman", "Tinglayman", "Ketib qolaman", "Menejerni chaqiraman"], 1, "Avval diqqat bilan tinglang."),
            ("Buyurtmani qabul qilgach nima qilinadi?", ["Takrorlab tasdiqlanadi", "Darhol oshxonaga yuguriladi", "Hech narsa", "Chek chiqariladi"], 0, "Xato bo'lmasligi uchun takrorlanadi."),
        ]),
    },
]

STANDARDS = [
    ("Qo'les yuvish qoidasi", "Gigiyena", "Har safar: ishni boshlashdan oldin, xom mahsulotdan keyin, hojatxonadan keyin, telefon ushlagandan keyin — 20 soniya sovun bilan.", True, []),
    ("Forma va tashqi ko'rinish", "Gigiyena", "Toza forma, bosh kiyim, yopiq poyabzal. Taqinchoqlar, lak, atir — mumkin emas.", True, []),
    ("Muzlatgich haroratini nazorat qilish", "Oshxona", "Har 4 soatda sovutgich (0…+4°C) va muzlatgich (−18°C) harorati jurnalga yoziladi.", False, ["cook", "manager"]),
    ("Kassa yopish tartibi", "Kassa", "Smena oxirida naqd pul sanaladi, farq bo'lsa menejerga darhol xabar beriladi.", False, ["cashier", "manager"]),
]

# Haqiqiy ochiq video (JSST — qo'l yuvish, YouTube): demo darsda video nazorati qanday ishlashini ko'rsatish uchun
DEMO_VIDEOS = {"Qo'lni to'g'ri yuvish": "https://www.youtube.com/watch?v=3PmVJQUCm4E"}


def seed_demo_training(owner: User | None = None) -> int:
    if Course.objects.exists():
        return 0
    random.seed(7)
    owner = owner or User.objects.filter(memberships__role__code="owner").first()
    manager = User.objects.filter(memberships__role__code="manager").first() or owner
    for ci, c in enumerate(COURSES):
        course = Course.objects.create(
            title=c["title"], description=c["description"], category=c["category"], roles=c.get("roles", []),
            everyone=c.get("everyone", False), due_days=c["due_days"], responsible=manager, is_published=True,
            created_by=owner, sort_order=ci)
        for li, (title, body, checklist) in enumerate(c["lessons"]):
            Lesson.objects.create(course=course, title=title, body=body, checklist=checklist, sort_order=li,
                                  video_url=DEMO_VIDEOS.get(title, ""))
        qt, limit, qs = c["quiz"]
        quiz = Quiz.objects.create(course=course, title=qt, time_limit_seconds=limit)
        for qi, (text, opts, correct, expl) in enumerate(qs):
            ids = "abcdef"
            Question.objects.create(quiz=quiz, text=text, options=[{"id": ids[i], "text": o} for i, o in enumerate(opts)],
                                    correct=[ids[correct]], explanation=expl, sort_order=qi)
        services.sync_course(course, owner)

    for si, (title, cat, body, everyone, roles) in enumerate(STANDARDS):
        Standard.objects.create(title=title, category=cat, body=body, everyone=everyone, roles=roles, responsible=manager, sort_order=si)

    burger = Course.objects.get(title="Burger tayyorlash standarti")
    a1 = Assignment.objects.create(title="Burgerni standart bo'yicha tayyorlang", course=burger, roles=["cook"], responsible=manager, created_by=owner,
                                   description="Bitta burgerni darsdagi tartibda tayyorlab, kesimi ko'rinadigan rasmini yuboring.",
                                   due_at=timezone.now() + timedelta(days=2))
    a2 = Assignment.objects.create(title="Smena oxirida ish joyini tozalash", everyone=True, responsible=manager, created_by=owner,
                                   description="Ish joyingizni tozalab, oldin/keyin rasmini yuboring.", due_at=timezone.now() + timedelta(days=1))
    services.sync_assignment(a1)
    services.sync_assignment(a2)

    # xodimlar progressi — hisobot bo'sh ko'rinmasin
    now = timezone.now()
    for u in services.staff_users():
        if services.user_roles(u) <= {"owner"}:
            continue
        level = random.choice([0, 1, 2, 3])
        for e in u.training_enrollments.select_related("course"):
            lessons = list(e.course.lessons.all())
            k = {0: 0, 1: 1, 2: len(lessons) // 2 + 1, 3: len(lessons)}[level]
            for les in lessons[:k]:
                LessonProgress.objects.create(user=u, lesson=les, percent=100, views=random.randint(1, 3),
                                              watched_seconds=random.randint(60, 240), completed_at=now - timedelta(days=random.randint(0, 5)))
            if level == 3:
                quiz = e.course.quizzes.first()
                if quiz:
                    a = services.start_attempt(quiz, u)
                    services.grade(a, {str(q.pk): q.correct for q in quiz.questions.all()})
            services.recompute(e.course, u)
        if level >= 2:
            for s in Standard.objects.filter(everyone=True):
                StandardAck.objects.get_or_create(standard=s, user=u, version=s.version)
        if level == 3:
            Submission.objects.filter(user=u, assignment=a2).update(status=SubmissionStatus.SUBMITTED, submitted_at=now, text="Tozalandi ✅", attempts=1)
    return Course.objects.count()
