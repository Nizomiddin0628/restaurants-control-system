"""Demo taomnoma (bootstrap_dev) — maketlardagi 'Lazzat' menyusi."""
from . import services
from .models import Category, Modifier, ModifierGroup, Product


def seed_demo_menu():
    if Product.objects.exists():
        return
    Category.objects.all().delete()
    cats = {}
    for i, (uz, ru, en) in enumerate([("Burgerlar", "Бургеры", "Burgers"), ("Lavash", "Лаваш", "Lavash"), ("Donar", "Донер", "Doner"),
                                       ("Kombolar", "Комбо", "Combos"), ("Garnir", "Гарниры", "Sides"), ("Ichimliklar", "Напитки", "Drinks")]):
        cats[uz] = Category.objects.create(name={"uz": uz, "ru": ru, "en": en}, sort_order=i)

    sauce = ModifierGroup.objects.create(name={"uz": "Sous", "ru": "Соус", "en": "Sauce"}, min_select=0, max_select=2)
    for j, (n, p) in enumerate([("Ketchup", 0), ("Mayonez", 0), ("Achchiq", 1000), ("Sirli", 3000)]):
        Modifier.objects.create(group=sauce, name={"uz": n, "ru": n, "en": n}, price=p, sort_order=j)
    spicy = ModifierGroup.objects.create(name={"uz": "Achchiqlik", "ru": "Острота", "en": "Spiciness"}, min_select=1, max_select=1)
    for j, n in enumerate(["Oddiy", "O'rtacha", "Achchiq"]):
        Modifier.objects.create(group=spicy, name={"uz": n, "ru": n, "en": n}, price=0, is_default=(j == 0), sort_order=j)

    items = [
        ("Burgerlar", "Lazzat Burger", "Mol go'shti kotleti, cheddar, pomidor, maxsus sous", 36000, 12600, 220, 520, ["hit"], [sauce]),
        ("Burgerlar", "Double Burger", "Ikki kotlet, cheddar, karamel piyoz", 49000, 19800, 320, 780, ["new"], [sauce]),
        ("Burgerlar", "Tovuqli burger", "Grill tovuq, salat, sous", 30000, 10300, 210, 480, [], [sauce]),
        ("Lavash", "Tovuqli lavash", "Grill tovuq, yangi sabzavot, yogurt sousi", 28000, 8400, 350, 610, ["hit"], [spicy]),
        ("Lavash", "Mol go'shtli lavash", "Mol go'shti, sabzavot, sous", 32000, 10200, 360, 650, [], [spicy]),
        ("Donar", "Donar katta", "Mol go'shti, kartoshka fri, 2 sous", 32000, 10200, 400, 780, ["hit"], [sauce]),
        ("Donar", "Donar kichik", "Mol go'shti, kartoshka fri, sous", 24000, 7700, 280, 560, [], [sauce]),
        ("Kombolar", "Kombo №1", "Burger + fri + 0,4 l ichimlik", 49000, 16200, 520, 1040, ["value"], []),
        ("Kombolar", "Kombo №2", "Lavash + fri + 0,4 l ichimlik", 44000, 14500, 560, 1050, [], []),
        ("Garnir", "Kartoshka fri", "Katta porsiya", 15000, 3300, 150, 420, [], [sauce]),
        ("Ichimliklar", "Cola 0,4 l", "", 10000, 3500, 400, 170, [], []),
        ("Ichimliklar", "Ayron 0,3 l", "", 8000, 2100, 300, 90, [], []),
    ]
    for i, (cat, name, desc, price, cost, w, kcal, tags, groups) in enumerate(items):
        p = Product.objects.create(category=cats[cat], name={"uz": name, "ru": name, "en": name},
                                   description={"uz": desc, "ru": desc, "en": desc}, price=price, cost=cost,
                                   weight_g=w, kcal=kcal, tags=tags, sort_order=i)
        p.modifier_groups.set(groups)
    services.publish(by="demo", note="Boshlang'ich taomnoma")
