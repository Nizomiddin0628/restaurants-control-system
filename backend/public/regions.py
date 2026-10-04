"""O'zbekiston hududlari (viloyat → tuman/shahar) — HQ'da restoranni hudud bo'yicha guruhlash uchun.
Tuman ro'yxati — tanlash uchun taklif; ro'yxatda yo'q bo'lsa, qo'lda yozish mumkin."""

REGIONS: dict[str, list[str]] = {
    "Toshkent shahri": ["Bektemir", "Chilonzor", "Mirobod", "Mirzo Ulug'bek", "Olmazor", "Sergeli", "Shayxontohur", "Uchtepa",
                        "Yakkasaroy", "Yangihayot", "Yashnobod", "Yunusobod"],
    "Toshkent viloyati": ["Angren sh.", "Bekobod", "Bo'stonliq", "Bo'ka", "Chinoz", "Chirchiq sh.", "Ohangaron", "Olmaliq sh.", "O'rta Chirchiq",
                          "Oqqo'rg'on", "Parkent", "Piskent", "Qibray", "Quyi Chirchiq", "Toshkent tumani", "Yangiyo'l", "Yuqori Chirchiq", "Zangiota",
                          "Nurafshon sh."],
    "Andijon viloyati": ["Andijon sh.", "Andijon tumani", "Asaka", "Baliqchi", "Bo'z", "Buloqboshi", "Izboskan", "Jalaquduq", "Xo'jaobod",
                         "Qo'rg'ontepa", "Marhamat", "Oltinko'l", "Paxtaobod", "Shahrixon", "Ulug'nor", "Xonobod sh."],
    "Buxoro viloyati": ["Buxoro sh.", "Buxoro tumani", "G'ijduvon", "Jondor", "Kogon", "Olot", "Peshku", "Qorako'l", "Qorovulbozor",
                        "Romitan", "Shofirkon", "Vobkent"],
    "Farg'ona viloyati": ["Farg'ona sh.", "Marg'ilon sh.", "Qo'qon sh.", "Quvasoy sh.", "Beshariq", "Bog'dod", "Buvayda", "Dang'ara",
                          "Farg'ona tumani", "Furqat", "Oltiariq", "Qo'shtepa", "Quva", "Rishton", "So'x", "Toshloq", "Uchko'prik",
                          "O'zbekiston tumani", "Yozyovon"],
    "Jizzax viloyati": ["Jizzax sh.", "Arnasoy", "Baxmal", "Do'stlik", "Forish", "G'allaorol", "Mirzacho'l", "Paxtakor", "Sharof Rashidov",
                        "Yangiobod", "Zafarobod", "Zarbdor", "Zomin"],
    "Xorazm viloyati": ["Urganch sh.", "Xiva sh.", "Bog'ot", "Gurlan", "Xonqa", "Hazorasp", "Qo'shko'pir", "Shovot", "Urganch tumani",
                        "Yangiariq", "Yangibozor", "Tuproqqal'a"],
    "Namangan viloyati": ["Namangan sh.", "Chortoq", "Chust", "Kosonsoy", "Mingbuloq", "Namangan tumani", "Norin", "Pop", "To'raqo'rg'on",
                          "Uchqo'rg'on", "Uychi", "Yangiqo'rg'on"],
    "Navoiy viloyati": ["Navoiy sh.", "Zarafshon sh.", "Karmana", "Konimex", "Navbahor", "Nurota", "Qiziltepa", "Tomdi", "Uchquduq", "Xatirchi"],
    "Qashqadaryo viloyati": ["Qarshi sh.", "Shahrisabz sh.", "Chiroqchi", "Dehqonobod", "G'uzor", "Kasbi", "Kitob", "Koson", "Mirishkor",
                             "Muborak", "Nishon", "Qamashi", "Qarshi tumani", "Yakkabog'", "Shahrisabz tumani", "Ko'kdala"],
    "Qoraqalpog'iston Respublikasi": ["Nukus sh.", "Amudaryo", "Beruniy", "Chimboy", "Ellikqal'a", "Kegeyli", "Mo'ynoq", "Nukus tumani",
                                      "Qonliko'l", "Qorao'zak", "Qo'ng'irot", "Shumanay", "Taxtako'pir", "To'rtko'l", "Xo'jayli", "Taxiatosh",
                                      "Bo'zatov"],
    "Samarqand viloyati": ["Samarqand sh.", "Kattaqo'rg'on sh.", "Bulung'ur", "Ishtixon", "Jomboy", "Kattaqo'rg'on tumani", "Narpay",
                           "Nurobod", "Oqdaryo", "Pastdarg'om", "Paxtachi", "Payariq", "Qo'shrabot", "Samarqand tumani", "Toyloq", "Urgut"],
    "Sirdaryo viloyati": ["Guliston sh.", "Shirin sh.", "Yangiyer sh.", "Boyovut", "Guliston tumani", "Mirzaobod", "Oqoltin", "Sardoba",
                          "Sayxunobod", "Sirdaryo tumani", "Xovos"],
    "Surxondaryo viloyati": ["Termiz sh.", "Angor", "Boysun", "Denov", "Jarqo'rg'on", "Muzrabot", "Oltinsoy", "Qiziriq", "Qumqo'rg'on",
                             "Sariosiyo", "Sherobod", "Sho'rchi", "Termiz tumani", "Uzun", "Bandixon"],
}


def region_list() -> list[dict]:
    return [{"name": k, "districts": v} for k, v in REGIONS.items()]
