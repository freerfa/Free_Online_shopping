"""Add 5 example job listings (with generated images) to the Jobs category."""
import os, json, sqlite3, html

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "static", "img", "products")
os.makedirs(OUT, exist_ok=True)

JOBS = [
    {"id": 13, "name": "Delivery Rider (Juba)", "stock": 4,
     "emoji": "🛵", "colors": ("#0891b2", "#2563eb"),
     "desc": ("Delivery Rider — Juba. Own motorcycle, valid licence and good "
              "knowledge of Juba routes required. Daily pay + fuel allowance. "
              "Tap Apply now and send your CV through the Contact page.")},
    {"id": 14, "name": "Warehouse Assistant", "stock": 2,
     "emoji": "📦", "colors": ("#d97706", "#dc2626"),
     "desc": ("Warehouse Assistant — receiving, packing and loading orders. "
              "S4 level minimum, able to lift heavy items, team player. "
              "Tap Apply now and send your CV through the Contact page.")},
    {"id": 15, "name": "Customer Support Agent", "stock": 3,
     "emoji": "🎧", "colors": ("#7c3aed", "#db2777"),
     "desc": ("Customer Support Agent — phone, WhatsApp and walk-in customers. "
              "Excellent communication in English and Juba Arabic, patient and "
              "friendly. Training provided. Tap Apply now to send your CV.")},
    {"id": 16, "name": "Graphic Designer (Part-time)", "stock": 1,
     "emoji": "🎨", "colors": ("#16a34a", "#0d9488"),
     "desc": ("Graphic Designer (Part-time) — social media posts, flyers and "
              "product photos. Send a portfolio with your CV. Remote-friendly "
              "with weekly check-ins in Juba. Tap Apply now to get started.")},
    {"id": 17, "name": "Marketing Officer", "stock": 2,
     "emoji": "📣", "colors": ("#e11d48", "#f59e0b"),
     "desc": ("Marketing Officer — grow Connect Airtime across South Sudan: "
              "campaigns, campus and market outreach, social media. Diploma in "
              "marketing or related field. Tap Apply now and send your CV.")},
]

def svg_for(j):
    c1, c2 = j["colors"]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="600" height="450" viewBox="0 0 600 450">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>
  </linearGradient></defs>
  <rect width="600" height="450" fill="url(#g)"/>
  <rect x="18" y="18" rx="9" ry="9" width="86" height="38" fill="#ffffff" opacity="0.92"/>
  <text x="61" y="44" font-size="19" text-anchor="middle" fill="{c1}" font-family="system-ui,sans-serif" font-weight="700">HIRING</text>
  <circle cx="300" cy="185" r="112" fill="rgba(255,255,255,0.16)"/>
  <text x="300" y="238" font-size="120" text-anchor="middle">{j["emoji"]}</text>
  <text x="300" y="378" text-anchor="middle" fill="#ffffff" font-family="system-ui,sans-serif" font-size="30" font-weight="800">{html.escape(j["name"])[:32]}</text>
  <text x="300" y="414" text-anchor="middle" fill="#ffffff" font-family="system-ui,sans-serif" font-size="19" opacity="0.92">Tap Apply now · CV via Contact page</text>
</svg>"""

def as_product(j):
    fn = f"product_{j['id']}.svg"
    with open(os.path.join(OUT, fn), "w", encoding="utf-8") as f:
        f.write(svg_for(j))
    return {"id": j["id"], "name": j["name"], "category": "jobs",
            "price": 0, "old_price": 0, "stock": j["stock"], "badge": "Hiring",
            "image": f"/static/img/products/{fn}", "desc": j["desc"]}

new_products = [as_product(j) for j in JOBS]

seed_path = os.path.join(BASE, "site_data.json")
with open(seed_path, "r", encoding="utf-8") as f:
    seed = json.load(f)
for np in new_products:
    if not any(p.get("id") == np["id"] for p in seed["products"]):
        seed["products"].append(np)
with open(seed_path, "w", encoding="utf-8") as f:
    json.dump(seed, f, indent=2, ensure_ascii=False)
print("seed updated")

dbp = os.path.join(BASE, "data", "site.db")
if os.path.exists(dbp):
    con = sqlite3.connect(dbp)
    row = con.execute("SELECT value FROM site_data WHERE key='products'").fetchone()
    prods = json.loads(row[0]) if row else seed["products"]
    for np in new_products:
        if not any(p.get("id") == np["id"] for p in prods):
            prods.append(np)
    con.execute("INSERT OR REPLACE INTO site_data(key,value) VALUES('products',?)",
                (json.dumps(prods, ensure_ascii=False),))
    con.commit()
    con.close()
    print("live DB updated")