"""Demo: xomashyo, kirim, tex-kartalar (Lazzat burger uchun real tannarx)."""
from decimal import Decimal

from modules.catalog.models import Product

from .models import Ingredient, Recipe, RecipeLine, Supplier
from .services import create_purchase, recompute_all

ING = [
    # (nom, kategoriya, birlik, narx so'm/birlik, min qoldiq)
    ("Mol go'shti (qiyma)", "Go'sht", "kg", 88_000, 5),
    ("Tovuq filesi", "Go'sht", "kg", 42_000, 5),
    ("Burger noni", "Non", "dona", 2_500, 50),
    ("Lavash xamiri", "Non", "dona", 1_800, 50),
    ("Pomidor", "Sabzavot", "kg", 12_000, 3),
    ("Bodring", "Sabzavot", "kg", 9_000, 3),
    ("Piyoz", "Sabzavot", "kg", 4_000, 5),
    ("Salat bargi", "Sabzavot", "kg", 25_000, 1),
    ("Pishloq (cheddar)", "Sut", "kg", 110_000, 2),
    ("Kartoshka fri", "Muzlatilgan", "kg", 22_000, 10),
    ("Sous (burger)", "Sous", "l", 38_000, 2),
    ("Ketchup", "Sous", "l", 18_000, 2),
    ("O'simlik moyi", "Quruq", "l", 21_000, 5),
    ("Coca-Cola 0.5", "Ichimlik", "dona", 6_000, 24),
    ("Tuz", "Quruq", "kg", 2_000, 1),
]

RECIPES = {
    # taom nomi (uz) → [(xomashyo, mayda birlik miqdori, chiqindi %)]
    "Lazzat Burger": [("Burger noni", 1, 0), ("Mol go'shti (qiyma)", 90, 5), ("Pishloq (cheddar)", 12, 0),
                      ("Pomidor", 30, 10), ("Salat bargi", 10, 15), ("Piyoz", 15, 10), ("Sous (burger)", 20, 0)],
    "Double Burger": [("Burger noni", 1, 0), ("Mol go'shti (qiyma)", 140, 5), ("Pishloq (cheddar)", 25, 0),
                      ("Pomidor", 30, 10), ("Salat bargi", 10, 15), ("Sous (burger)", 30, 0)],
    "Tovuqli burger": [("Burger noni", 1, 0), ("Tovuq filesi", 130, 8), ("Salat bargi", 10, 15), ("Bodring", 25, 10),
                       ("Sous (burger)", 25, 0), ("O'simlik moyi", 20, 0)],
    "Kartoshka fri": [("Kartoshka fri", 150, 0), ("O'simlik moyi", 30, 0), ("Tuz", 2, 0), ("Ketchup", 30, 0)],
    "Coca-Cola 0.5": [("Coca-Cola 0.5", 1, 0)],
}


def seed_demo_inventory(tenant=None) -> int:
    if Ingredient.objects.exists():
        return 0
    sup = Supplier.objects.create(name="Bozor (Chorsu)", phone="+998901112233")
    ings = {}
    for name, cat, unit, price, min_stock in ING:
        ings[name] = Ingredient.objects.create(name={"uz": name, "ru": name, "en": name}, category=cat, unit=unit,
                                               price=0, min_stock=min_stock, supplier=sup)
    # birinchi bozorlik — narx va qoldiq shu yerdan keladi
    create_purchase(lines=[{"ingredient_id": ings[n].pk, "qty": (min_stock * 4) or 10, "unit_price": price}
                           for n, _, _, price, min_stock in ING], supplier=sup, note="Boshlang'ich kirim", tenant=tenant)
    n = 0
    for pname, lines in RECIPES.items():
        p = Product.objects.filter(name__uz__iexact=pname, deleted_at__isnull=True).first() or \
            Product.objects.filter(name__uz__icontains=pname.split()[0], deleted_at__isnull=True).first()
        if not p:
            continue
        r, _ = Recipe.objects.get_or_create(product=p)
        r.lines.all().delete()
        for i, (iname, qty, waste) in enumerate(lines):
            RecipeLine.objects.create(recipe=r, ingredient=ings[iname], qty=Decimal(qty), waste_percent=Decimal(waste), sort_order=i)
        n += 1
    recompute_all(tenant)
    return n
