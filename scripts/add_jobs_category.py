"""Add the 'Jobs' category and a sample job listing to seed + live DB (idempotent)."""
import os, json, sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

category = {"id": "jobs", "name": "Jobs", "icon": "💼"}
product = {
    "id": 12,
    "name": "Sales Agent — Juba",
    "category": "jobs",
    "price": 0,
    "old_price": 0,
    "stock": 3,
    "badge": "Hiring",
    "image": "/static/img/products/product_12.svg",
    "desc": ("Job opening: Sales Agent (Juba) — friendly team, training provided, "
             "commission on target. Tap Apply now and send your CV through the "
             "Contact page; we will get back to you. "
             "MD: MUSEVENI SYLVESTER Sallah · +211 924 689 271 / +211 929 122 339."),
}

def upsert(cats, prods=None):
    if not any(c.get("id") == "jobs" for c in cats):
        cats.append(category)
    if prods is not None and not any(p.get("id") == 12 for p in prods):
        prods.append(product)

seed_path = os.path.join(BASE, "site_data.json")
with open(seed_path, "r", encoding="utf-8") as f:
    seed = json.load(f)
upsert(seed["categories"], seed["products"])
with open(seed_path, "w", encoding="utf-8") as f:
    json.dump(seed, f, indent=2, ensure_ascii=False)
print("seed updated")

dbp = os.path.join(BASE, "data", "site.db")
if os.path.exists(dbp):
    con = sqlite3.connect(dbp)
    for key in ("categories", "products"):
        row = con.execute("SELECT value FROM site_data WHERE key=?", (key,)).fetchone()
        blob = json.loads(row[0]) if row else seed[key]
        upsert(blob if key == "categories" else [], None if key == "categories" else blob)
        con.execute("INSERT OR REPLACE INTO site_data(key,value) VALUES(?,?)",
                    (key, json.dumps(blob, ensure_ascii=False)))
    con.commit()
    con.close()
    print("live DB updated")