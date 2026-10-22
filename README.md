# Free Online Shopping

Flask + SQLite (JSON-blob CMS) + Jinja2 online store: catalog, cart, checkout, orders, contact form, user accounts, and a full `/admin` CMS.

## Documentation

Full technical documentation lives in [`docs/`](docs/README.md):

| # | Document | What it covers |
|---|---|---|
| 01 | [Architecture](docs/01-architecture.md) | App layout, request lifecycle, design decisions |
| 02 | [Data Model](docs/02-data-model.md) | SQLite tables, `site_data` JSON blobs, user records |
| 03 | [Route Reference](docs/03-routes.md) | Every route, its methods, guards and behaviour |
| 04 | [Access Rights](docs/04-access-rights.md) | Account status, permission flags, enforcement points |
| 05 | [Admin CMS](docs/05-admin-cms.md) | Every admin page and the POST actions it handles |
| 06 | [Payments](docs/06-payments.md) | Two-sided payment system, methods, admin ledger |
| 07 | [i18n & Currency](docs/07-i18n-currency.md) | Language files, translation filter, multi-currency |
| 08 | [Uploads & Security](docs/08-uploads-security.md) | File validation, CSRF, hashing, access control |
| 09 | [Deployment](docs/09-deployment.md) | Local run, Render, environment variables |
| 10 | [Testing](docs/10-testing.md) | Smoke tests and the manual checklist |

Release history is in [`CHANGELOG.md`](CHANGELOG.md). The docs are living
documentation — see [Maintaining this documentation](docs/README.md#maintaining-this-documentation)
for the rules on updating them alongside code changes.

## Run locally

```bash
pip3 install -r requirements.txt
python3 app.py            # open http://127.0.0.1:8080  (PORT=8080 by default on this Mac)
```

> macOS note: port 5000 is reserved by the AirPlay Receiver on modern macOS, so the app defaults tests to `PORT=8080` (`PORT=5000 python3 app.py` works on servers/Linux).

Default admin login: `admin` / `admin123` — change it under **Admin → Account** after first login.

## Customer access rights

Admins can control, per customer account, both the account **status**
(`active`, `suspended`, `blocked`) and the **feature permissions** it may
use (`shop`, `sell`, `payment`, `apply`, `contact`), from **Admin → Users**.

- Suspended accounts keep browsing but are denied every restricted action.
- Blocked accounts are signed out on their next request and refused at login.
- Admins are never restricted, and legacy accounts default to fully active.
- Access rights live inside the existing `users` blob — no migration needed.

See [Access Rights](docs/04-access-rights.md) for the full behaviour.

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