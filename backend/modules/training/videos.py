"""Demo darslar uchun haqiqiy, ochiq YouTube videolar (2026-09 da oEmbed orqali tekshirilgan).

Sarlavha → havola. Yangi restoran ochilganda demo kurslarga shu videolar qo'yiladi;
eski bazalar uchun: `manage.py training_videos --all`.
"""
VIDEOS: dict[str, str] = {
    # Osh tayyorlash standarti
    "Mahsulot tanlash va tayyorlash": "https://www.youtube.com/watch?v=x6seuiSNQcA",   # sabzini somoncha to'g'rash (RU)
    "Zirvak": "https://www.youtube.com/watch?v=nPCynUmy-uA",                            # qozonda osh, bosqichma-bosqich (RU)
    "Guruch solish va damlash": "https://www.youtube.com/watch?v=usyaB7tiex8",          # Stalik: guruchni zirvakka solish (RU)
    "Porsiya va berish": "https://www.youtube.com/watch?v=Xc0f3Bvg36s",                 # I. Lazerson: oshni suzish va berish (RU)
    # Gigiyena va sanitariya
    "Qo'lni to'g'ri yuvish": "https://www.youtube.com/watch?v=3PmVJQUCm4E",             # JSST (WHO)
    "Forma va tashqi ko'rinish": "https://www.youtube.com/watch?v=FOM3SUFY030",         # oziq-ovqat xodimi gigiyenasi (EN)
    "Mahsulotlarni saqlash": "https://www.youtube.com/watch?v=wxFj4_TBjeg",             # FIFO / FEFO, saqlash (EN)
    # Mehmonga xizmat ko'rsatish
    "Kutib olish": "https://www.youtube.com/watch?v=jBe8e69ypcc",                       # ofitsiant: kutib olish (EN)
    "Buyurtma qabul qilish": "https://www.youtube.com/watch?v=507MW3G2Zzw",             # buyurtma qabul qilish darsi (RU)
    "Shikoyat bilan ishlash": "https://www.youtube.com/watch?v=zrnL0FUYz4M",            # shikoyat bilan ishlash tamoyillari (EN)
    "Hisob-kitob va xayrlashish": "https://www.youtube.com/watch?v=2X8X5xz8f1w",        # hisobni berish va to'lov (EN)
    # Oshxona xavfsizligi
    "Pichoq bilan xavfsiz ishlash": "https://www.youtube.com/watch?v=oLTaMPjAgLo",      # pichoq xavfsizligi (EN)
    "O't o'chirgich (PASS usuli)": "https://www.youtube.com/watch?v=heVKavoFhKA",       # PASS usuli (EN)
}

# Avval qo'yilgan, endi almashtirilgan havolalar (mavzuga to'liq mos emas edi)
REPLACED = {"https://www.youtube.com/watch?v=CEXa3aEiTJU"}


def apply_videos() -> int:
    """Joriy sxemadagi darslarga videolarni qo'yadi: bo'sh yoki eskirgan havolani almashtiradi. Qo'lda qo'yilganiga tegmaydi."""
    from django.db.models import Q

    from .models import Lesson
    n = 0
    for title, url in VIDEOS.items():
        n += Lesson.objects.filter(title=title).filter(Q(video_url="") | Q(video_url__in=REPLACED)).update(video_url=url)
    return n
