"""Add the 'Service' category and 'Connect Airtime L.T.D' product to seed + live DB."""
import os, json, sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

category = {"id": "service", "name": "Service", "icon": "📡"}
product = {
    "id": 11,
    "name": "Connect Airtime L.T.D",
    "category": "service",
    "price": 1000,
    "old_price": 0,
    "stock": 999,
    "badge": "New",
    "image": "/static/img/products/product_11.svg",
    "desc": ("Connect Airtime L.T.D — building trust for all South Sudanese. "
             "Fast, simple and reliable airtime top-up for ALL networks on one number. "
             "Managing Director (MD): MUSEVENI SYLVESTER Sallah. "
             "Call/WhatsApp: +211 924 689 271 or +211 929 122 339."),
}

def upsert(cats, prods):
    if not any(c.get("id") == "service" for c in cats):
        cats.append(category)
    if not any(p.get("id") == 11 for p in prods):
        prods.insert(0, product)  # front = featured on home + top of shop
    return cats, prods

seed_path = os.path.join(BASE, "site_data.json")
with open(seed_path, "r", encoding="utf-8") as f:
    seed = json.load(f)
seed["categories"], seed["products"] = upsert(seed["categories"], seed["products"])
with open(seed_path, "w", encoding="utf-8") as f:
    json.dump(seed, f, indent=2, ensure_ascii=False)
print("seed updated")

dbp = os.path.join(BASE, "data", "site.db")
if os.path.exists(dbp):
    con = sqlite3.connect(dbp)
    for key in ("categories", "products"):
        row = con.execute("SELECT value FROM site_data WHERE key=?", (key,)).fetchone()
        blob = json.loads(row[0]) if row else seed[key]
        if key == "categories":
            blob = upsert(blob, [])[0]
        else:
            blob = upsert([], blob)[1]
        con.execute("INSERT OR REPLACE INTO site_data(key,value) VALUES(?,?)",
                    (key, json.dumps(blob, ensure_ascii=False)))
    con.commit()
    con.close()
    print("live DB updated")