# Free Online Shopping

Flask + SQLite (JSON-blob CMS) + Jinja2 online store: catalog, cart, checkout, orders, contact form, user accounts, and a full `/admin` CMS.

## Run locally

```bash
pip3 install -r requirements.txt
python3 app.py            # open http://127.0.0.1:8080  (PORT=8080 by default on this Mac)
```

> macOS note: port 5000 is reserved by the AirPlay Receiver on modern macOS, so the app defaults tests to `PORT=8080` (`PORT=5000 python3 app.py` works on servers/Linux).

Default admin login: `admin` / `admin123` — change it under **Admin → Account** after first login.

## Design notes

- Public content is editable from the admin CMS and saved to the `site_data` table (one JSON blob per key).
- `admin_users`, `users`, and `admin_account` are **protected keys** — a plain content re-import never overwrites them.
- `site_data.json` seeds the DB only on first boot; after that `data/site.db` is the source of truth.
- Uploads are validated by magic bytes + extension; on Render set `DATA_DIR=/opt/render/project/src/data` (persistent disk, see `render.yaml`).
- Email goes out via HTTPS API (Resend) when `RESEND_API_KEY` is set; otherwise it is logged (SMTP is often blocked).

## Env vars

| Var | Purpose |
|---|---|
| `SECRET_KEY` | Flask session secret (set a strong one in production) |
| `DATA_DIR` | Where `site.db` and `uploads/` live (Render persistent disk) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Override default first-boot admin credentials |
| `RESEND_API_KEY` / `FROM_EMAIL` | Enable real order/contact emails over HTTPS |

## Test checklist (verified)

- Public pages `/`, `/shop`, `/product/<id>`, `/cart`, `/checkout`, `/contact`, `/login`, `/register` → 200
- Register → add to cart → checkout → order stored, stock decremented, order page shown
- Admin login (`admin` / `admin123`) → all `/admin/*` pages 200; anonymous access redirects
- Content CMS save updates the live site; content **import cannot overwrite** `admin_users` / `users` / `admin_account`
- Contact messages stored and visible in admin; fake `.png` (bad magic bytes) rejected
- `gunicorn app:app` boots with 2 workers (Render-ready, `render.yaml` included)