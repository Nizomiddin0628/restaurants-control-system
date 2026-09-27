"""
Tayyor loyiha shablonlari — restoran amaliyotidan: bosqich → vazifalar, muddatlar boshlanish sanasidan hisoblanadi.
Har vazifa: (nomi, boshlanishdan necha kun keyin tugashi, [checklist bandlari]).
Ruxsatnoma kabi davlat talablari o'zgarib turadi — vazifa matnida «tekshiring» deb qoldirilgan.
"""
from __future__ import annotations

TEMPLATES: dict[str, dict] = {
    "branch_open": {
        "title": "Yangi filial ochish", "category": "branch", "days": 75, "priority": "high",
        "description": "Joy tanlashdan ochilish kunigacha: ijara, ta'mir, jihoz, ruxsatnomalar, xodimlar, menyu va ochilish marketingi.",
        "milestones": [
            ("Joy va ijara", 14, [
                ("Kamida 3 ta joyni ko'rish (o'tish joyi, parking, qo'shnilar)", 7, ["Kunduzi va kechqurun odam oqimini sanash", "Gaz, elektr (kVt), suv, kanalizatsiya quvvati", "Raqobatchilar ro'yxati"]),
                ("Ijara shartnomasi (muddat, ta'mir ta'tili, indeksatsiya)", 12, ["Yurist ko'rib chiqishi", "Ta'mir davriga ijara ta'tili", "Kommunal to'lovlar kimda"]),
                ("Byudjet va qoplanish muddatini hisoblash", 14, []),
            ]),
            ("Dizayn va ta'mir", 45, [
                ("Zal va oshxona rejasi (oqim: xom → issiq → tarqatish)", 20, ["Oshxona zonalari", "Omborxona va sovutgich joyi", "Hojatxona va qo'l yuvish"]),
                ("Pudratchi tanlash va smeta", 24, ["Kamida 3 ta smeta", "Muddat va jarima shartnomada"]),
                ("Ta'mir ishlari nazorati (haftalik foto)", 42, []),
                ("Ventilyatsiya, gaz va elektr montaji", 42, []),
            ]),
            ("Jihoz va tizimlar", 55, [
                ("Oshxona jihozlari ro'yxati va xarid", 40, ["Plita, pech, fritur", "Sovutgich va muzlatkich", "Idish-tovoq, inventar"]),
                ("Kassa, printer, planshet va internet", 50, ["RestoPOS'da yangi filial ochish", "Oshxona ekrani (KDS)", "Menyu narxlari filialga"]),
                ("Mebel, yorug'lik va peshlavha", 52, []),
            ]),
            ("Ruxsatnomalar", 60, [
                ("Faoliyat haqida xabardor qilish / ruxsatlar (my.gov.uz — joriy talablarni tekshiring)", 50, []),
                ("Sanitariya talablari: tibbiy ko'rik daftarchalari, dezinfeksiya shartnomasi", 55, []),
                ("Yong'in xavfsizligi: o't o'chirgichlar, evakuatsiya rejasi", 55, []),
                ("Chiqindi olib ketish shartnomasi", 58, []),
            ]),
            ("Xodimlar", 68, [
                ("Shtat jadvali va ishga olish e'lonlari", 45, []),
                ("Suhbatlar va ishga qabul qilish", 58, []),
                ("O'qitish: standartlar, kassa, retseptlar (sinov smenasi)", 66, []),
            ]),
            ("Ochilish", 75, [
                ("Ombor: birinchi xarid va qoldiqlarni kiritish", 70, []),
                ("Sinov kuni (yaqinlar uchun yopiq ochilish)", 72, ["Taom chiqish vaqti", "Kassa va chek", "Xizmat ko'rsatish"]),
                ("Ochilish marketingi: Instagram, Telegram, afisha, aksiya", 73, []),
                ("Rasmiy ochilish", 75, []),
            ]),
        ],
    },
    "new_menu": {
        "title": "Yangi taom / mavsumiy menyu", "category": "menu", "days": 30, "priority": "normal",
        "description": "G'oyadan sotuvgacha: retsept, tex-karta, tannarx, degustatsiya, foto, xodimlarni o'qitish.",
        "milestones": [
            ("G'oya va tahlil", 5, [
                ("Menyu tahlili: nima yaxshi sotilmayapti (Hisobot → Menu engineering)", 2, []),
                ("Yangi taomlar ro'yxati va maqsadli narx", 5, []),
            ]),
            ("Retsept va tannarx", 14, [
                ("Retseptni ishlab chiqish (3 ta sinov)", 10, []),
                ("Tex-karta kiritish (Ombor → Tex-kartalar)", 12, []),
                ("Tannarx va narx: food cost 30% atrofida", 14, []),
            ]),
            ("Sinov", 21, [
                ("Degustatsiya: rahbar va 5 ta doimiy mijoz", 18, ["Ta'm", "Ko'rinish", "Porsiya hajmi", "Chiqish vaqti"]),
                ("Foto va menyu matni", 21, []),
            ]),
            ("Ishga tushirish", 30, [
                ("Oshpazlar va ofitsiantlarni o'qitish (taomni tavsiya qilish)", 26, []),
                ("Menyuga va saytga qo'shish, Telegram e'lon", 28, []),
                ("2 hafta sotuv natijasini tahlil qilish", 30, []),
            ]),
        ],
    },
    "renovation": {
        "title": "Ta'mir / jihoz almashtirish", "category": "renovation", "days": 21, "priority": "normal",
        "description": "Smeta, pudratchi, ish grafigi (savdoga ta'sir kam bo'lsin), qabul qilish.",
        "milestones": [
            ("Tayyorgarlik", 7, [
                ("Nima qilinadi — ro'yxat va rasmlar", 2, []),
                ("3 ta smeta olish va pudratchi tanlash", 6, []),
                ("Ish grafigi: yopiladigan kunlar / tungi smena", 7, []),
            ]),
            ("Ish", 18, [
                ("Materiallarni xarid qilish", 9, []),
                ("Ishlarni nazorat qilish (kunlik foto)", 17, []),
            ]),
            ("Qabul", 21, [
                ("Ishni qabul qilish (akt) va kamchiliklar ro'yxati", 20, []),
                ("To'lovni yakunlash", 21, []),
            ]),
        ],
    },
    "marketing": {
        "title": "Marketing kampaniyasi", "category": "marketing", "days": 30, "priority": "normal",
        "description": "Maqsad → kontent → reklama → natija. Masalan: yangi filial, bayram aksiyasi, yetkazib berishni oshirish.",
        "milestones": [
            ("Reja", 5, [
                ("Maqsad va raqam: masalan, +20% kechki savdo", 2, []),
                ("Auditoriya, taklif (aksiya) va byudjet", 5, []),
            ]),
            ("Kontent", 12, [
                ("Kontent reja: 12 post, 20 stories", 7, []),
                ("Foto/video suratga olish", 10, []),
                ("Dizayn: banner, afisha, menyu vkladish", 12, []),
            ]),
            ("Ishga tushirish", 26, [
                ("Instagram/Telegram reklama sozlash", 14, []),
                ("Blogerlar bilan kelishuv", 16, []),
                ("Aksiya promokodini yaratish (Mijozlar → Promo)", 14, []),
            ]),
            ("Natija", 30, [
                ("Natija: savdo, yangi mijozlar, promokod ishlatilishi", 30, []),
            ]),
        ],
    },
    "training": {
        "title": "Xodimlarni o'qitish dasturi", "category": "hr", "days": 21, "priority": "normal",
        "description": "Ehtiyojni aniqlash, kurs va test tayyorlash, o'qitish, natijani KPI'ga bog'lash.",
        "milestones": [
            ("Ehtiyoj", 4, [
                ("Qaysi lavozimda qanday xato ko'p (vazifalar, shikoyatlar)", 3, []),
                ("O'qitish rejasi va jadvali", 4, []),
            ]),
            ("Material", 10, [
                ("Kurs va darslar (O'qitish → Kurslar)", 8, []),
                ("Test savollari", 10, []),
            ]),
            ("O'qitish", 18, [
                ("Guruhlarga o'qitish va amaliy mashg'ulot", 16, []),
                ("Test topshirish va sertifikat", 18, []),
            ]),
            ("Natija", 21, [
                ("Natijani KPI va baholashga qo'shish", 21, []),
            ]),
        ],
    },
    "it_rollout": {
        "title": "Tizimni joriy etish (kassa, ombor, xodimlar)", "category": "it", "days": 14, "priority": "high",
        "description": "RestoPOS'ni to'liq ishga tushirish: menyu, tex-karta, xodimlar, kassa, ombor qoldiqlari.",
        "milestones": [
            ("Sozlash", 5, [
                ("Filial, zal va stollar", 1, []),
                ("Menyu va narxlar", 3, []),
                ("Xodimlar, lavozimlar va ruxsatlar", 4, []),
                ("Tex-kartalar va ombor qoldiqlari", 5, []),
            ]),
            ("O'qitish", 9, [
                ("Kassirlarni o'qitish", 7, []),
                ("Oshxona ekrani va ofitsiantlar", 8, []),
                ("Menejer: hisobotlar, ombor, vazifalar", 9, []),
            ]),
            ("Ishga tushirish", 14, [
                ("Birinchi hafta: kunlik tekshiruv va savollar", 13, []),
                ("Eski tizimni o'chirish", 14, []),
            ]),
        ],
    },
}


def template_list() -> list[dict]:
    from .models import CAT_META
    return [{"key": k, "title": t["title"], "category": t["category"], "emoji": CAT_META[t["category"]][0], "days": t["days"],
             "description": t["description"], "milestones": len(t["milestones"]), "tasks": sum(len(m[2]) for m in t["milestones"])}
            for k, t in TEMPLATES.items()]
