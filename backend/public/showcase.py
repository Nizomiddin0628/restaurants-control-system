"""
Namuna restoran «Navro'z milliy taomlar» — barcha imkoniyatlarni ko'rsatish va sinash uchun to'liq soxta baza.

Hamma ma'lumot to'qima (ismlar, telefonlar, mijozlar). Narxlar esa haqiqatga yaqin — 2026-yil Toshkent:
  • bozor narxlari (pul24.uz, 2026-06-01): mol go'shti 75–106 ming, qo'y 90–130 ming, guruch 12 mingdan, pomidor ≤13 ming…
  • osh markazlarida 1 porsiya osh Toshkentda 30 200 so'm (uz24.uz, 2024) → 2026-yil o'rta restoranda 42–60 ming
  • somsa, lag'mon, kabob — hostella.uz (2026) va o'rta toifadagi restoran menyulari darajasida
Tannarx tex-kartalardan hisoblanadi (food cost ≈ 28–38%).

Ishga tushirish:  python manage.py seed_showcase          → http://namuna.localhost:8000
                  python manage.py seed_showcase --reset  → o'chirib, qaytadan yaratadi
"""
from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.utils import timezone
from django_tenants.utils import schema_context

SLUG = "namuna"
NAME = "Navro'z milliy taomlar"
OWNER_PHONE = "+998901234567"          # demo egasi (Lazzat bilan bir xil — eslab qolish oson)
EXTRA_OWNERS = [("+998888203830", "Nizomiddin")]   # loyiha egasi o'z raqami bilan ham kira oladi

# ------------------------------------------------------------------ taomnoma
CATS = [("Osh", "Плов", "Plov"), ("Sho'rvalar", "Супы", "Soups"), ("Issiq taomlar", "Горячие блюда", "Main dishes"),
        ("Kaboblar", "Шашлыки", "Kebabs"), ("Somsa va non", "Самса и хлеб", "Samsa & bread"), ("Salatlar", "Салаты", "Salads"),
        ("Shirinliklar", "Десерты", "Desserts"), ("Ichimliklar", "Напитки", "Drinks")]

# (kategoriya, nomi uz, nomi ru, tavsif, narx, vazn g, kkal, teglar, modifikator guruhlari)
MENU = [
    ("Osh", "To'y oshi", "Свадебный плов", "Devzira guruch, mol go'shti, sariq sabzi, no'xat va mayiz bilan", 48000, 400, 780, ["hit"], ["porsiya"]),
    ("Osh", "Choyxona oshi", "Чайханский плов", "Qo'y go'shti va dumba yog'ida, ko'p sabzili", 42000, 380, 820, [], ["porsiya"]),
    ("Osh", "Samarqand oshi", "Самаркандский плов", "Qatlam-qatlam, go'sht ustida, sabzi alohida qovurilgan", 45000, 400, 760, [], ["porsiya"]),
    ("Osh", "Qazili osh", "Плов с казы", "To'y oshi + uy qazisi va bedana tuxumi", 62000, 450, 950, ["new"], ["porsiya"]),
    ("Sho'rvalar", "Sho'rva", "Шурпа", "Qo'y go'shti, kartoshka, sabzi va ko'katlar bilan", 38000, 450, 420, [], []),
    ("Sho'rvalar", "Mastava", "Мастава", "Guruchli sho'rva, suzma bilan", 30000, 400, 380, [], []),
    ("Sho'rvalar", "Chuchvara sho'rva", "Суп с чучварой", "Qo'lda tugilgan chuchvara, qatiq bilan", 32000, 400, 410, [], []),
    ("Sho'rvalar", "Mosh xo'rda", "Маш-кхурда", "Mosh, guruch va go'sht — uy taomi", 28000, 400, 360, [], []),
    ("Issiq taomlar", "Qovurma lag'mon", "Жареный лагман", "Qo'lda cho'zilgan xamir, mol go'shti va sabzavot", 40000, 380, 690, ["hit"], ["achchiqlik"]),
    ("Issiq taomlar", "Suyuq lag'mon", "Лагман", "Go'shtli sabzavotli sho'rva va cho'zma xamir", 35000, 450, 540, [], ["achchiqlik"]),
    ("Issiq taomlar", "Manti (5 dona)", "Манты (5 шт)", "Qo'y go'shti va piyoz, bug'da pishirilgan", 36000, 300, 620, [], []),
    ("Issiq taomlar", "Dimlama", "Димлама", "Go'sht va sabzavotlar o'z sharbatida dimlangan", 45000, 450, 560, [], []),
    ("Issiq taomlar", "Qozon kabob", "Казан-кабоб", "Qo'y go'shti va kartoshka qozonda qovurilgan", 69000, 450, 980, ["hit"], []),
    ("Issiq taomlar", "Norin", "Нарын", "Mayda to'g'ralgan xamir va qazi, sovuq holda", 38000, 300, 540, [], []),
    ("Kaboblar", "Qo'y go'shti kabob", "Шашлык из баранины", "1 six, piyoz va non bilan", 28000, 160, 420, ["hit"], ["garnir"]),
    ("Kaboblar", "Mol go'shti kabob", "Шашлык из говядины", "1 six", 26000, 160, 380, [], ["garnir"]),
    ("Kaboblar", "Jigar kabob", "Шашлык из печени", "1 six, dumba bilan", 22000, 150, 350, [], ["garnir"]),
    ("Kaboblar", "Lula kabob", "Люля-кебаб", "Qiyma, ziravorlar bilan", 26000, 150, 390, [], ["garnir"]),
    ("Kaboblar", "Tovuq kabob", "Шашлык из курицы", "1 six, marinadlangan", 20000, 170, 290, [], ["garnir"]),
    ("Somsa va non", "Tandir somsa", "Самса тандырная", "Qo'y go'shti va dumba", 13000, 150, 380, ["hit"], []),
    ("Somsa va non", "Qovoqli somsa", "Самса с тыквой", "Mavsumiy, yengil", 9000, 150, 260, [], []),
    ("Somsa va non", "Obi non", "Лепёшка", "Tandirda yopilgan", 5000, 400, 900, [], []),
    ("Somsa va non", "Patir non", "Патыр", "Qatlamli, sutli", 9000, 350, 1050, [], []),
    ("Salatlar", "Achchiq-chuchuk", "Ачик-чучук", "Pomidor, piyoz, achchiq qalampir", 15000, 250, 70, [], []),
    ("Salatlar", "Toshkent salati", "Салат «Ташкент»", "Ko'k turp, mol go'shti, tuxum", 32000, 250, 380, [], []),
    ("Salatlar", "Suzma ko'katlar bilan", "Сюзьма с зеленью", "Uy suzmasi", 14000, 200, 240, [], []),
    ("Salatlar", "Olivye", "Оливье", "Tovuq go'shti bilan", 26000, 250, 420, [], []),
    ("Salatlar", "Ko'k salat", "Зелёный салат", "Bodring, pomidor, ko'katlar", 18000, 250, 90, ["veg"], []),
    ("Shirinliklar", "Chak-chak", "Чак-чак", "Asal bilan", 18000, 150, 520, [], []),
    ("Shirinliklar", "Halvo", "Халва", "Uy halvosi", 20000, 120, 560, [], []),
    ("Ichimliklar", "Ko'k choy (choynak)", "Зелёный чай (чайник)", "", 8000, 800, 0, [], []),
    ("Ichimliklar", "Qora choy (choynak)", "Чёрный чай (чайник)", "", 8000, 800, 0, [], []),
    ("Ichimliklar", "Limonli choy", "Чай с лимоном", "Limon va asal", 15000, 800, 60, [], []),
    ("Ichimliklar", "Kompot (1 l)", "Компот (1 л)", "Quritilgan mevalardan", 20000, 1000, 240, [], []),
    ("Ichimliklar", "Ayron", "Айран", "Uy ayroni, 0,4 l", 12000, 400, 120, [], []),
    ("Ichimliklar", "Coca-Cola 0,5", "Coca-Cola 0,5", "", 12000, 500, 210, [], []),
    ("Ichimliklar", "Suv 0,5", "Вода 0,5", "Gazsiz", 5000, 500, 0, [], []),
]

# ------------------------------------------------------------------ xomashyo (nom, kategoriya, birlik, narx, min qoldiq, boshlang'ich kirim)
ING = [
    ("Mol go'shti", "Go'sht", "kg", 95000, 10, 45), ("Qo'y go'shti", "Go'sht", "kg", 115000, 8, 40),
    ("Dumba", "Go'sht", "kg", 85000, 3, 10), ("Tovuq go'shti", "Go'sht", "kg", 45000, 5, 20),
    ("Mol jigari", "Go'sht", "kg", 60000, 2, 6), ("Qazi", "Go'sht", "kg", 180000, 3, 2),
    ("Guruch (devzira)", "Don", "kg", 28000, 20, 80), ("Un", "Don", "kg", 6500, 25, 100),
    ("No'xat", "Don", "kg", 18000, 3, 10), ("Mosh", "Don", "kg", 20000, 2, 8), ("Mayiz", "Quruq", "kg", 40000, 2, 5),
    ("Sariq sabzi", "Sabzavot", "kg", 6000, 20, 90), ("Piyoz", "Sabzavot", "kg", 5000, 15, 60),
    ("Kartoshka", "Sabzavot", "kg", 5000, 20, 60), ("Pomidor", "Sabzavot", "kg", 12000, 8, 25),
    ("Bodring", "Sabzavot", "kg", 10000, 5, 15), ("Bolgar qalampir", "Sabzavot", "kg", 12000, 3, 10),
    ("Karam", "Sabzavot", "kg", 4000, 5, 15), ("Qovoq", "Sabzavot", "kg", 5000, 5, 15), ("Ko'k turp", "Sabzavot", "kg", 6000, 3, 8),
    ("Sarimsoq", "Sabzavot", "kg", 25000, 2, 4), ("Ko'katlar", "Sabzavot", "kg", 20000, 1, 3), ("Limon", "Meva", "kg", 50000, 2, 1),
    ("Paxta yog'i", "Yog'", "l", 24000, 20, 60), ("Tuxum", "Sut", "dona", 1500, 60, 300), ("Suzma", "Sut", "kg", 35000, 3, 12),
    ("Mayonez", "Sous", "kg", 30000, 2, 6), ("Ziravorlar", "Quruq", "kg", 60000, 1, 3), ("Tuz", "Quruq", "kg", 3000, 3, 10),
    ("Shakar", "Quruq", "kg", 12000, 5, 15), ("Asal", "Quruq", "kg", 90000, 1, 3),
    ("Ko'k choy", "Choy", "kg", 90000, 1, 3), ("Qora choy", "Choy", "kg", 80000, 1, 3), ("Quritilgan meva", "Quruq", "kg", 45000, 2, 6),
    ("Obi non (tayyor)", "Non", "dona", 3000, 40, 120), ("Patir (tayyor)", "Non", "dona", 5500, 20, 40),
    ("Chak-chak (tayyor)", "Shirinlik", "kg", 60000, 2, 4), ("Halvo (tayyor)", "Shirinlik", "kg", 70000, 2, 3),
    ("Coca-Cola 0,5", "Ichimlik", "dona", 7500, 24, 96), ("Suv 0,5", "Ichimlik", "dona", 2500, 24, 96),
]

# taom → [(xomashyo, miqdor: g / ml / dona, chiqindi %)]
RECIPES = {
    "To'y oshi": [("Guruch (devzira)", 150, 0), ("Mol go'shti", 90, 8), ("Sariq sabzi", 120, 10), ("Piyoz", 40, 10), ("Paxta yog'i", 45, 0),
                  ("No'xat", 15, 0), ("Mayiz", 8, 0), ("Sarimsoq", 10, 5), ("Ziravorlar", 3, 0), ("Tuz", 3, 0)],
    "Choyxona oshi": [("Guruch (devzira)", 150, 0), ("Qo'y go'shti", 70, 8), ("Dumba", 20, 0), ("Sariq sabzi", 150, 10), ("Piyoz", 40, 10),
                      ("Paxta yog'i", 30, 0), ("Ziravorlar", 3, 0), ("Tuz", 3, 0)],
    "Samarqand oshi": [("Guruch (devzira)", 150, 0), ("Mol go'shti", 100, 8), ("Sariq sabzi", 120, 10), ("Piyoz", 40, 10), ("Paxta yog'i", 40, 0),
                       ("No'xat", 15, 0), ("Ziravorlar", 3, 0), ("Tuz", 3, 0)],
    "Qazili osh": [("Guruch (devzira)", 150, 0), ("Mol go'shti", 80, 8), ("Qazi", 50, 0), ("Sariq sabzi", 120, 10), ("Piyoz", 40, 10),
                   ("Paxta yog'i", 45, 0), ("No'xat", 15, 0), ("Tuxum", 1, 0), ("Ziravorlar", 3, 0)],
    "Sho'rva": [("Qo'y go'shti", 90, 10), ("Kartoshka", 120, 15), ("Sariq sabzi", 60, 10), ("Piyoz", 40, 10), ("Pomidor", 40, 5),
                ("Bolgar qalampir", 20, 10), ("Ko'katlar", 5, 0), ("Ziravorlar", 2, 0)],
    "Mastava": [("Guruch (devzira)", 50, 0), ("Mol go'shti", 60, 8), ("Kartoshka", 60, 15), ("Sariq sabzi", 50, 10), ("Piyoz", 30, 10),
                ("Pomidor", 30, 5), ("Paxta yog'i", 15, 0), ("Suzma", 30, 0)],
    "Chuchvara sho'rva": [("Un", 80, 0), ("Mol go'shti", 70, 8), ("Piyoz", 40, 10), ("Suzma", 30, 0), ("Ko'katlar", 5, 0)],
    "Mosh xo'rda": [("Mosh", 60, 0), ("Guruch (devzira)", 40, 0), ("Mol go'shti", 50, 8), ("Piyoz", 30, 10), ("Paxta yog'i", 15, 0), ("Suzma", 30, 0)],
    "Qovurma lag'mon": [("Un", 150, 0), ("Tuxum", 1, 0), ("Mol go'shti", 90, 8), ("Bolgar qalampir", 40, 10), ("Pomidor", 50, 5),
                        ("Piyoz", 40, 10), ("Sarimsoq", 5, 5), ("Paxta yog'i", 30, 0)],
    "Suyuq lag'mon": [("Un", 130, 0), ("Mol go'shti", 80, 8), ("Kartoshka", 60, 15), ("Bolgar qalampir", 30, 10), ("Pomidor", 40, 5), ("Piyoz", 30, 10)],
    "Manti (5 dona)": [("Un", 120, 0), ("Qo'y go'shti", 90, 8), ("Dumba", 20, 0), ("Piyoz", 100, 10), ("Ziravorlar", 2, 0)],
    "Dimlama": [("Mol go'shti", 110, 8), ("Kartoshka", 150, 15), ("Sariq sabzi", 80, 10), ("Karam", 100, 10), ("Pomidor", 60, 5),
                ("Bolgar qalampir", 40, 10), ("Piyoz", 50, 10)],
    "Qozon kabob": [("Qo'y go'shti", 170, 10), ("Kartoshka", 200, 15), ("Paxta yog'i", 40, 0), ("Piyoz", 40, 10), ("Ziravorlar", 3, 0)],
    "Norin": [("Un", 100, 0), ("Qazi", 40, 0), ("Mol go'shti", 30, 5), ("Piyoz", 30, 10)],
    "Qo'y go'shti kabob": [("Qo'y go'shti", 75, 5), ("Dumba", 15, 0), ("Piyoz", 30, 10), ("Ziravorlar", 1, 0)],
    "Mol go'shti kabob": [("Mol go'shti", 80, 5), ("Piyoz", 30, 10), ("Ziravorlar", 1, 0)],
    "Jigar kabob": [("Mol jigari", 90, 5), ("Dumba", 15, 0), ("Piyoz", 30, 10)],
    "Lula kabob": [("Mol go'shti", 40, 5), ("Qo'y go'shti", 35, 5), ("Dumba", 10, 0), ("Piyoz", 30, 10), ("Ziravorlar", 2, 0)],
    "Tovuq kabob": [("Tovuq go'shti", 120, 10), ("Paxta yog'i", 10, 0), ("Ziravorlar", 2, 0)],
    "Tandir somsa": [("Un", 70, 0), ("Qo'y go'shti", 30, 5), ("Dumba", 10, 0), ("Piyoz", 40, 10)],
    "Qovoqli somsa": [("Un", 70, 0), ("Qovoq", 100, 15), ("Piyoz", 20, 10), ("Dumba", 10, 0)],
    "Obi non": [("Obi non (tayyor)", 1, 0)],
    "Patir non": [("Patir (tayyor)", 1, 0)],
    "Achchiq-chuchuk": [("Pomidor", 150, 5), ("Piyoz", 40, 10), ("Ko'katlar", 3, 0)],
    "Toshkent salati": [("Mol go'shti", 60, 8), ("Ko'k turp", 100, 15), ("Tuxum", 1, 0), ("Mayonez", 30, 0), ("Ko'katlar", 5, 0)],
    "Suzma ko'katlar bilan": [("Suzma", 150, 0), ("Ko'katlar", 5, 0)],
    "Olivye": [("Kartoshka", 60, 15), ("Tovuq go'shti", 50, 10), ("Tuxum", 1, 0), ("Bodring", 30, 5), ("Mayonez", 40, 0)],
    "Ko'k salat": [("Bodring", 100, 5), ("Pomidor", 80, 5), ("Ko'katlar", 10, 0), ("Paxta yog'i", 10, 0)],
    "Chak-chak": [("Chak-chak (tayyor)", 150, 0)],
    "Halvo": [("Halvo (tayyor)", 120, 0)],
    "Ko'k choy (choynak)": [("Ko'k choy", 8, 0)],
    "Qora choy (choynak)": [("Qora choy", 8, 0)],
    "Limonli choy": [("Qora choy", 8, 0), ("Limon", 40, 10), ("Asal", 20, 0)],
    "Kompot (1 l)": [("Quritilgan meva", 150, 0), ("Shakar", 60, 0)],
    "Ayron": [("Suzma", 120, 0), ("Tuz", 2, 0)],
    "Coca-Cola 0,5": [("Coca-Cola 0,5", 1, 0)],
    "Suv 0,5": [("Suv 0,5", 1, 0)],
}

# xodimlar: vazifalar demosi ro'yxati (+ zal va oshxona uchun qo'shimchalar)
EXTRA_STAFF = [("+998901110011", "Bobur Rahmonov", "waiter"), ("+998901110012", "Shahzoda Umarova", "waiter"),
               ("+998901110013", "Otabek Nurmatov", "waiter"), ("+998901110014", "Ravshan Hakimov", "cook"),
               ("+998901110015", "Farhod Tursunov", "cook"), ("+998901110016", "Elyor Qosimov", "courier")]

OSH_COURSE = {
    "title": "Osh tayyorlash standarti", "category": "Oshxona", "roles": ["cook", "manager"], "due_days": 7,
    "description": "Zirvakdan damlashgacha — har qozon bir xil ta'm, rang va porsiyada bo'lishi uchun.",
    "lessons": [
        ("Mahsulot tanlash va tayyorlash", "Devzira guruch 1 soat oldin ivitiladi, sabzi somoncha to'g'raladi (3–4 mm), go'sht 50–60 g bo'laklarga bo'linadi.",
         ["Guruch — 1 soat ivitish", "Sabzi — somoncha 3–4 mm", "Go'sht — 50–60 g bo'lak"]),
        ("Zirvak", "Yog' tutun chiqquncha qizdiriladi, piyoz tillarang bo'lguncha, keyin go'sht va sabzi. Zirvak 40 daqiqa qaynaydi.",
         ["Yog' harorati", "Piyoz — tillarang", "Zirvak — 40 daqiqa"]),
        ("Guruch solish va damlash", "Guruch tekis yoyiladi, suv 1,5 barmoq ustida. Suv singgach — tepasi to'planadi, 25 daqiqa dam.",
         ["Suv — 1,5 barmoq", "Olov pasaytiriladi", "Dam — 25 daqiqa"]),
        ("Porsiya va berish", "Porsiya: 150 g guruch, 90 g go'sht, sabzi ustida. Lagan issiq bo'lishi shart, achchiq-chuchuk bilan.",
         ["Tarozida porsiya", "Issiq lagan", "Salat bilan"]),
    ],
    "quiz": ("Osh standarti — yakuniy test", 240, [
        ("Devzira guruch necha vaqt ivitiladi?", ["10 daqiqa", "1 soat", "1 kun", "Ivitilmaydi"], 1, "1 soat — guruch bir tekis pishadi."),
        ("Zirvak necha daqiqa qaynaydi?", ["5", "15", "40", "90"], 2, "40 daqiqa — go'sht yumshaydi, sabzi shirasini beradi."),
        ("Suv guruch ustida qancha bo'ladi?", ["Guruch bilan barobar", "1,5 barmoq", "5 barmoq", "Suv qo'yilmaydi"], 1, "1,5 barmoq — ortiqcha bo'lsa osh bo'tqa bo'ladi."),
        ("Bir porsiyada qancha go'sht bo'ladi?", ["30 g", "90 g", "200 g", "Ko'z bilan"], 1, "Standart — 90 g, tarozida."),
        ("Osh qanday idishda beriladi?", ["Sovuq likopchada", "Issiq laganda", "Qog'ozda", "Farqi yo'q"], 1, "Issiq lagan — osh sovib qolmaydi."),
    ]),
}


# ------------------------------------------------------------------ yordamchilar
def _tenant_exists():
    from public.models import Tenant
    return Tenant.objects.filter(slug=SLUG).first()


def drop() -> bool:
    """Namuna restoranni butunlay o'chiradi (sxema bilan). Faqat shu namunaga tegadi."""
    from public.models import Domain, Tenant
    t = Tenant.objects.filter(slug=SLUG).first()
    if t is None:
        return False
    schema = t.schema_name
    Domain.objects.filter(tenant=t).delete()
    Tenant.objects.filter(pk=t.pk).delete()
    with connection.cursor() as c:
        c.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    return True


def build(domain: str = "namuna.localhost", log=print):
    from public.services import create_tenant, set_modules
    if _tenant_exists():
        raise RuntimeError("Namuna restoran allaqachon bor. Qaytadan yaratish uchun: --reset")
    t = create_tenant(name=NAME, slug=SLUG, owner_phone=OWNER_PHONE, preset="restaurant", owner_name="Bahodir Qodirov",
                      plan_code="pro", domain=domain, branch_name="Chilonzor filiali", trial_days=30)
    set_modules(t, [*t.enabled_modules, "training", "crm"])
    log(f"Restoran yaratildi: {t.name} ({domain})")
    with schema_context(t.schema_name):
        connection.set_tenant(t)
        _staff(t, log)
        _menu(t, log)
        _inventory(t, log)
        _operations(t, log)
        _training(t, log)
        _crm_and_telegram(t, log)
        _site(t, log)
        _kitchen_now(t, log)
    connection.set_schema_to_public()
    return t


def _staff(t, log):
    from core.models import Membership, Role, User
    from modules.tasks.demo import STAFF
    roles = {r.code: r for r in Role.objects.all()}
    for phone, name in EXTRA_OWNERS:
        u, _ = User.objects.get_or_create(phone=phone, defaults={"full_name": name})
        Membership.objects.get_or_create(user=u, role=roles["owner"])
    n = 0
    for phone, name, code in [*STAFF, *EXTRA_STAFF]:
        u, _ = User.objects.get_or_create(phone=phone, defaults={"full_name": name})
        Membership.objects.get_or_create(user=u, role=roles[code])
        n += 1
    log(f"Xodimlar: {n}")


def _menu(t, log):
    from modules.catalog import services as cat_services
    from modules.catalog.models import Category, Modifier, ModifierGroup, Product
    cats = {}
    for i, (uz, ru, en) in enumerate(CATS):
        cats[uz] = Category.objects.create(name={"uz": uz, "ru": ru, "en": en}, sort_order=i)
    groups = {}
    g = ModifierGroup.objects.create(name={"uz": "Porsiya", "ru": "Порция", "en": "Portion"}, min_select=1, max_select=1)
    for j, (n, ru, p) in enumerate([("To'liq", "Полная", 0), ("Yarim", "Половина", -12000), ("Katta (1,5)", "Большая", 18000)]):
        Modifier.objects.create(group=g, name={"uz": n, "ru": ru, "en": n}, price=p, is_default=(j == 0), sort_order=j)
    groups["porsiya"] = g
    g = ModifierGroup.objects.create(name={"uz": "Achchiqlik", "ru": "Острота", "en": "Spiciness"}, min_select=1, max_select=1)
    for j, n in enumerate(["Oddiy", "O'rtacha", "Achchiq"]):
        Modifier.objects.create(group=g, name={"uz": n, "ru": n, "en": n}, price=0, is_default=(j == 0), sort_order=j)
    groups["achchiqlik"] = g
    g = ModifierGroup.objects.create(name={"uz": "Garnir", "ru": "Гарнир", "en": "Side"}, min_select=0, max_select=2)
    for j, (n, ru, p) in enumerate([("Marinadlangan piyoz", "Маринованный лук", 0), ("Non", "Лепёшка", 5000), ("Achchiq sous", "Острый соус", 3000)]):
        Modifier.objects.create(group=g, name={"uz": n, "ru": ru, "en": n}, price=p, sort_order=j)
    groups["garnir"] = g
    for i, (cat, uz, ru, desc, price, w, kcal, tags, gcodes) in enumerate(MENU):
        p = Product.objects.create(category=cats[cat], name={"uz": uz, "ru": ru, "en": uz}, description={"uz": desc, "ru": desc, "en": desc},
                                   price=price, weight_g=w, kcal=kcal, tags=tags, sort_order=i)
        p.modifier_groups.set([groups[c] for c in gcodes])
    Product.objects.filter(name__uz="Norin").update(in_stop_list=True)      # stop-list namunasi
    cat_services.publish(by="namuna", note="Boshlang'ich taomnoma", tenant=t)
    log(f"Taomnoma: {len(MENU)} taom, {len(CATS)} bo'lim")


def _inventory(t, log):
    from modules.catalog.models import Product
    from modules.inventory.models import Ingredient, Recipe, RecipeLine, Supplier
    from modules.inventory.services import create_purchase, recompute_all
    sups = {k: Supplier.objects.create(name=n, phone=ph) for k, n, ph in [
        ("go'sht", "Go'sht ulgurji (Chorsu bozori)", "+998901230001"), ("don", "Guruch va un ulgurji savdo", "+998901230002"),
        ("sabzavot", "Sabzavot va ko'kat (Parkent bozori)", "+998901230003"), ("ichimlik", "Ichimliklar distribyutori", "+998901230004")]}
    sup_of = {"Go'sht": "go'sht", "Don": "don", "Quruq": "don", "Choy": "don", "Yog'": "don", "Ichimlik": "ichimlik", "Non": "sabzavot"}
    ings = {}
    for name, cat, unit, price, mn, _ in ING:
        ings[name] = Ingredient.objects.create(name={"uz": name, "ru": name, "en": name}, category=cat, unit=unit, price=0,
                                               min_stock=mn, supplier=sups[sup_of.get(cat, "sabzavot")])
    today = timezone.localdate()
    # 4 hafta kirimlari: har hafta bozorlik, narxlar biroz o'zgaradi (tarix grafik bo'sh bo'lmasin)
    rnd = random.Random(21)
    for wk in (21, 14, 7, 0):
        for key, sup in sups.items():
            lines = [{"ingredient_id": ings[n].pk, "qty": round(q / 4 if wk else q, 2),
                      "unit_price": int(price * (1 + rnd.uniform(-0.06, 0.06)))}
                     for n, cat, unit, price, mn, q in ING if sup_of.get(cat, "sabzavot") == key]
            if lines:
                create_purchase(lines=lines, supplier=sup, date=today - timedelta(days=wk), note=f"Haftalik bozorlik ({sup.name})", tenant=t)
    # kam qolgan xomashyo (ogohlantirish namunasi)
    for n, left in [("Qazi", Decimal("1.2")), ("Limon", Decimal("0.4")), ("Mayonez", Decimal("1.0"))]:
        Ingredient.objects.filter(pk=ings[n].pk).update(stock=left)
    for pname, lines in RECIPES.items():
        p = Product.objects.get(name__uz=pname)
        r = Recipe.objects.create(product=p)
        for i, (iname, qty, waste) in enumerate(lines):
            RecipeLine.objects.create(recipe=r, ingredient=ings[iname], qty=Decimal(qty), waste_percent=Decimal(waste), sort_order=i)
    recompute_all(t)
    log(f"Ombor: {len(ING)} xomashyo, {len(RECIPES)} tex-karta, 4 hafta kirim")


def _operations(t, log):
    from modules.hr.demo import seed_demo_hr
    from modules.pos.demo import seed_demo_orders
    from modules.pos.models import Order, OrderStatus
    from modules.reservations.demo import seed_demo_reservations
    from modules.tables.demo import seed_demo_tables
    from modules.tasks.demo import seed_demo_tasks
    tasks = seed_demo_tasks()
    orders = seed_demo_orders(days=65, per_day=(100, 135))
    # zalda o'tirganlarga stol raqami — hisobot va stol tarixi haqiqiy ko'rinsin
    rnd = random.Random(5)
    for o in Order.objects.filter(type="dine_in", status=OrderStatus.PAID).only("id")[:4000]:
        Order.objects.filter(pk=o.pk).update(table_no=str(rnd.randint(1, 10)))
    hr = seed_demo_hr()
    _payroll_rates()
    exp = _expenses()
    tables = seed_demo_tables()
    res = seed_demo_reservations()
    log(f"Kassa: {orders} chek (65 kun) · vazifalar: {tasks} · xodim kartalari: {hr} · chiqimlar: {exp} · stollar: {tables} · bronlar: {res}")


def _expenses() -> int:
    """O'rta restoran (120 o'rin) oylik xarajatlari, 2026: ijara ~30 mln, kommunal ~7 mln, aylanmadan soliq 4%…"""
    from django.db.models import Sum

    from modules.finance.models import Expense, ExpenseCategory, ensure_categories
    from modules.pos.models import Order
    ensure_categories()
    cats = {c.code: c for c in ExpenseCategory.objects.all()}
    today = timezone.localdate()
    rnd = random.Random(13)
    n = 0
    first = today.replace(day=1)
    months = [first]
    for _ in range(2):
        months.insert(0, (months[0] - timedelta(days=1)).replace(day=1))
    for m in months:
        nxt = (m + timedelta(days=32)).replace(day=1)
        rev = Order.objects.filter(status="paid", paid_at__date__gte=m, paid_at__date__lt=nxt).aggregate(s=Sum("total"))["s"] or 0
        rows = [("rent", 30_000_000, 3, "Ijara (oylik)"), ("utilities", rnd.randint(6_500_000, 8_000_000), 10, "Svet, gaz, suv"),
                ("tax", int(rev * 0.04), 15, "Aylanmadan soliq 4%"), ("software", 490_000, 2, "RestoPOS obuna"),
                ("marketing", 2_500_000, 5, "Instagram va Telegram reklama"), ("packaging", 1_400_000, 8, "Olib ketish idishlari"),
                ("repair", rnd.choice([450_000, 900_000, 1_200_000]), 18, "Tandir va qozon ta'miri"),
                ("delivery", rnd.randint(1_800_000, 2_600_000), 25, "Kuryer yoqilg'isi / Yandex"), ("other", 700_000, 20, "Xo'jalik mollari")]
        for code, amount, day, note in rows:
            d = m + timedelta(days=day - 1)
            if d <= today and code in cats and amount:
                Expense.objects.create(date=d, category=cats[code], amount=amount, note=note)
                n += 1
    return n


def _payroll_rates():
    """Toshkent o'rta restorani 2026: menejer ~5 mln, oshpaz ~4,5 mln, ofitsiant soatbay + chaychaqa, kassir smenabay."""
    from modules.hr.models import Employee, Payslip, Position
    rates = {"Menejer": 5_000_000, "Oshpaz": 4_500_000, "Kassir": 150_000, "Ofitsiant": 16_000, "Buxgalter": 3_500_000, "Marketolog": 3_000_000}
    for name, r in rates.items():
        Position.objects.filter(name=name).update(default_rate=r)
        Employee.objects.filter(position__name=name).update(rate=r)
    for s in Payslip.objects.select_related("employee"):
        s.rate = s.employee.rate
        s.compute()
        s.save()


def _training(t, log):
    from modules.training.demo import COURSES, seed_demo_training
    n = seed_demo_training(courses=[OSH_COURSE, COURSES[1], COURSES[2]],
                           cook_task=("Oshni standart bo'yicha damlang", "Bitta qozon oshni darsdagi tartibda damlab, laganda porsiya rasmini yuboring."))
    log(f"O'qitish: {n} kurs, testlar, standartlar, topshiriqlar")


def _crm_and_telegram(t, log):
    from modules.crm.demo import seed_demo_crm
    from modules.crm.models import Customer, Promo
    from modules.pos.models import Order
    from modules.telegram.models import Audience, BotUser, Broadcast, BroadcastStatus
    n = seed_demo_crm(t)
    Promo.objects.filter(code="LAZZAT10").update(name="NAVROZ10 promokod", code="NAVROZ10", description="Instagram va Telegram kanal obunachilari uchun")
    Promo.objects.filter(name__startswith="Happy hour").update(name="Tushlik vaqti −15%", description="Har kuni 12:00–15:00 butun menyuga", hour_from=12, hour_to=15)
    rnd = random.Random(9)
    now = timezone.now()
    tg = list(Customer.objects.filter(source="telegram")) + list(Customer.objects.exclude(source="telegram").order_by("?")[:12])
    for i, c in enumerate(tg):
        BotUser.objects.create(chat_id=700_000_000 + i, phone=c.phone, full_name=c.name, username="",
                               orders_count=0, spent_total=0, last_seen_at=now - timedelta(days=rnd.randint(0, 20)))
    for i in range(14):                                  # telefon ulashmagan obunachilar ham bo'ladi
        BotUser.objects.create(chat_id=710_000_000 + i, full_name=rnd.choice(["Aziz", "Madina", "Sherzod", "Laylo", "Temur", "Kamola"]),
                               last_seen_at=now - timedelta(days=rnd.randint(0, 30)), is_blocked=(i % 7 == 0))
    # mijoz buyurtmalarining bir qismi Telegram Mini App'dan kelgan
    phones = [c.phone for c in tg]
    ids = list(Order.objects.filter(customer_phone__in=phones, status="paid").values_list("id", flat=True))
    rnd.shuffle(ids)
    Order.objects.filter(pk__in=ids[: len(ids) // 3]).update(source="telegram", type="delivery")
    for bu in BotUser.objects.exclude(phone=""):
        qs = Order.objects.filter(customer_phone=bu.phone, status="paid", source="telegram")
        BotUser.objects.filter(pk=bu.pk).update(orders_count=qs.count(), spent_total=sum(qs.values_list("total", flat=True)))
    total = BotUser.objects.filter(is_blocked=False).count()
    for text, days, aud in [("🌷 Navro'z bayrami munosabati bilan butun menyuga −15%! 21–23-mart. Bron: botda «Stol bron qilish»", 12, Audience.ALL),
                            ("🆕 Yangi taom: Qazili osh — uy qazisi va bedana tuxumi bilan. Tatib ko'ring!", 5, Audience.ALL)]:
        Broadcast.objects.create(text=text, audience=aud, status=BroadcastStatus.SENT, total=total, sent=total - 2, failed=2,
                                 sent_at=now - timedelta(days=days))
    Broadcast.objects.create(text="Sizni sog'indik! Shu hafta NAVROZ10 promokodi bilan −10% 🙂", audience=Audience.BUYERS)
    tcfg = {"welcome_text": "Assalomu alaykum! «Navro'z» — milliy taomlar. Menyu, yetkazib berish va stol bron — shu yerda 👇",
            "delivery_fee": 15000, "free_delivery_from": 150000, "min_order": 50000, "allow_dine_in": True}
    mods = dict((t.settings or {}).get("modules") or {})
    mods["telegram"] = {**(mods.get("telegram") or {}), **tcfg}
    mods["crm"] = {**(mods.get("crm") or {}), "welcome_bonus": 10000, "birthday_bonus": 50000}
    t.settings = {**(t.settings or {}), "modules": mods}
    t.save(update_fields=["settings"])
    log(f"Mijozlar: {n} · Telegram obunachilar: {BotUser.objects.count()} · xabarlar: {Broadcast.objects.count()}")


def _site(t, log):
    from modules.cms.models import SiteSettings
    s = SiteSettings.get()
    s.title = NAME
    s.tagline = {"uz": "Toshkentning mazali oshi va kaboblari — 2016-yildan beri", "ru": "Вкусный плов и шашлык Ташкента — с 2016 года",
                 "en": "Tashkent's tasty plov and kebabs — since 2016"}
    s.phone = "+998712000000"
    s.address = "Toshkent sh., Chilonzor tumani, 9-kvartal (namuna manzil)"
    s.delivery = {"free_from": 150000, "fee": 15000, "eta_min": 35, "eta_max": 50}
    s.theme = {**(s.theme or {}), "primary": "#B5452B", "accent": "#1E6F5C", "bg": "#FBF6EE", "ink": "#23170F"}
    s.save()
    from core.models import Branch
    from modules.cms.models import SiteSection
    Branch.objects.update(address="Toshkent sh., Chilonzor tumani, 9-kvartal (namuna)", phone="+998712000000")
    for sec in SiteSection.objects.all():
        if sec.type == "hero":
            sec.props = {**sec.props, "title": "Toshkentning haqiqiy oshi va kaboblari",
                         "subtitle": "Qozon oshi, tandir somsa va kaboblar — zalda, olib ketish yoki 35–50 daqiqada yetkazib berish",
                         "cta": "Buyurtma berish"}
        elif sec.type == "bonus":
            sec.props = {**sec.props, "percent": 3}
        sec.save()
    log("Sayt: sarlavha, aloqa, yetkazib berish, rang, filial manzili")


def _kitchen_now(t, log):
    """Hozir oshxonada tayyorlanayotgan 4 ta buyurtma — oshxona ekrani va kassa «ochiq» holati bo'sh turmasin."""
    from core.events import emit
    from core.models import User
    from modules.catalog.models import Product
    from modules.pos.models import CashShift, Order, OrderItem
    shift = CashShift.objects.filter(closed_at__isnull=True).first()
    cashier = User.objects.filter(memberships__role__code="cashier").first()
    rnd = random.Random(3)
    prods = list(Product.objects.filter(in_stop_list=False))
    for k, (typ, table) in enumerate([("dine_in", "4"), ("dine_in", "VIP-1"), ("takeaway", ""), ("delivery", "")]):
        o = Order.objects.create(shift=shift, cashier=cashier, type=typ, table_no=table, source="telegram" if typ == "delivery" else "pos",
                                 note="Piyozsiz" if k == 1 else "")
        for p in rnd.sample(prods, k=rnd.randint(2, 4)):
            OrderItem.objects.create(order=o, product=p, name=p.name["uz"], qty=rnd.randint(1, 3), price=p.price, cost=p.cost)
        o.recalc()
        o.save()
        emit("pos.order_created", {"order_id": o.pk, "number": o.number, "total": o.total, "_tenant": t}, tenant=t)
    log("Oshxona ekrani: 4 ta faol buyurtma")
