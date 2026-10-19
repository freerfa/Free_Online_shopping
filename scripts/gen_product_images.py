"""Generate unique SVG product photos for seed products (offline-safe, license-free).
Run once: venv/bin/python scripts/gen_product_images.py"""
import os, json, sqlite3, html

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "static", "img", "products")
os.makedirs(OUT, exist_ok=True)

# category -> (emoji, gradient colors)
THEMES = {
    "phones":    ("📱", ("#4f46e5", "#0ea5e9")),
    "fashion":   ("👗", ("#db2777", "#f97316")),
    "home":      ("🏠", ("#0d9488", "#65a30d")),
    "groceries": ("🛒", ("#d97706", "#ca8a04")),
    "beauty":    ("🌸", ("#9333ea", "#ec4899")),
}
PRODUCT_EMOJI = {
    1: "📱", 2: "🎧", 3: "👕", 4: "👗", 5: "🍲",
    6: "💡", 7: "🌾", 8: "🫒", 9: "🧴", 10: "🌸",
}

def svg_for(p):
    emoji, (c1, c2) = THEMES.get(p.get("category"), THEMES["home"])
    emoji = PRODUCT_EMOJI.get(p.get("id"), emoji)
    name = html.escape(str(p.get("name", ""))[:28])
    badge = str(p.get("badge") or "")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="600" height="450" viewBox="0 0 600 450">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>
  </linearGradient></defs>
  <rect width="600" height="450" fill="url(#g)"/>
  <circle cx="300" cy="185" r="118" fill="rgba(255,255,255,0.16)"/>
  <text x="300" y="238" font-size="128" text-anchor="middle">{emoji}</text>
  <text x="300" y="392" font-size="30" text-anchor="middle" fill="#ffffff" font-family="system-ui,sans-serif" font-weight="700">{name}</text>
  {f'<rect x="20" y="20" rx="9" ry="9" width="110" height="40" fill="#ffffff" opacity="0.92"/><text x="75" y="47" font-size="20" text-anchor="middle" fill="{c1}" font-family="system-ui,sans-serif" font-weight="700">{html.escape(badge[:8])}</text>' if badge else ''}
</svg>"""

def main():
    seed_path = os.path.join(BASE, "site_data.json")
    with open(seed_path, "r", encoding="utf-8") as f:
        seed = json.load(f)
    for p in seed.get("products", []):
        fn = f"product_{p['id']}.svg"
        with open(os.path.join(OUT, fn), "w", encoding="utf-8") as f:
            f.write(svg_for(p))
        p["image"] = f"/static/img/products/{fn}"
        print("generated", fn, "for", p["name"])
    with open(seed_path, "w", encoding="utf-8") as f:
        json.dump(seed, f, indent=2, ensure_ascii=False)
    # also update the live DB
    dbp = os.path.join(BASE, "data", "site.db")
    if os.path.exists(dbp):
        con = sqlite3.connect(dbp)
        con.execute("INSERT OR REPLACE INTO site_data(key,value) VALUES('products',?)",
                    (json.dumps(seed["products"]),))
        con.commit(); con.close()
        print("live DB updated")

if __name__ == "__main__":
    main()