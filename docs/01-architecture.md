# 01 — Architecture

## 1. Overview

**Free Online Shopping** is a single-process Flask application that serves
both the public storefront and a complete admin CMS. It has no external
services beyond an optional email provider.

```
                    ┌──────────────────────────────┐
  Browser  ──────► │  Flask  (app.py)             │
                    │                              │
                    │  before_request chain         │
                    │   ├─ persist_currency()       │
                    │   ├─ persist_language()       │
                    │   ├─ csrf_guard()             │
                    │   └─ enforce_account_status() │
                    │          │                   │
                    │          ▼                   │
                    │      view function            │
                    │          │                   │
                    │   ┌──────┴───────┐           │
                    │   │              │           │
                    │ Jinja2        SQLite         │
                    │ templates/   data/site.db     │
                    └──────────────┘               │
                    ┌──────────────────────────────┐
                    │ static/  style.css app.js     │
                    │          lang/*.json img/     │
                    └──────────────────────────────┘
```

## 2. Repository layout

```
Free_Online_shopping/
├── app.py                    # entire application (single module)
├── site_data.json            # first-boot seed for the site_data table
├── requirements.txt          # Flask, gunicorn, Werkzeug (pinned)
├── render.yaml               # Render blueprint (web service + disk)
├── Procfile                  # `web: gunicorn app:app --bind 0.0.0.0:$PORT`
├── README.md                 # short orientation
├── CHANGELOG.md              # release history
├── docs/                     # this documentation set
├── templates/                # 29 Jinja2 templates
├── static/
│   ├── style.css             # single stylesheet
│   ├── app.js                # client-side behaviour
│   ├── lang/                 # en, ar, fr, sw, jac, am
│   └── img/                  # logos/ + products/ SVG artwork
├── scripts/                  # one-off data/image generators
├── data/                     # runtime state (git-ignored)
│   ├── site.db               # SQLite database
│   ├── uploads/              # public images
│   └── app_docs/             # private applicant documents
└── venv/                     # local virtualenv (git-ignored)
```

## 3. The single-module design

Everything lives in `app.py` (~1600 lines). This is deliberate for a project
of this size: one file to read, no import graph, no circular-import risk, and
trivial deployment (`gunicorn app:app`).

The file is organised into labelled sections in this order:

| Section | Contents |
|---|---|
| Config | Paths, secret key, upload limits, allowed extensions and magic bytes |
| DB helpers | `db()`, `init_db()`, `ensure_default_admin()` |
| Blob helpers | `get_blob()`, `set_blob()`, `get_all_content()`, `safe_import_content()` |
| Auth / CSRF | `csrf_token()`, `valid_csrf()`, `current_user()`, `is_admin()` |
| Access rights | `user_status()`, `user_perms()`, `has_perm()`, `can_sell()`, `perm_required()` |
| Uploads | `allowed_ext()`, `valid_magic()`, `save_upload()`, `save_doc_upload()` |
| Email | `send_email_https()` |
| Cart | `get_cart()`, `cart_detailed()` |
| i18n | `load_languages()`, `translate()` filter, `inject_globals()` context processor |
| Currency | `DEFAULT_CURRENCIES`, `format_currency()` filter |
| Request hooks | `persist_currency()`, `persist_language()`, `csrf_guard()`, `enforce_account_status()` |
| Public routes | `/`, `/shop`, `/cart`, `/checkout`, `/contact`, `/apply`, auth |
| Admin routes | `/admin/*` |

**When the file grows past ~2500 lines, or when a second module appears, split
it** — a `blueprints/` package with `public`, `admin` and `api` blueprints
mapped to the same URL paths. Do not split before that point; the current
single file is easier to reason about.

## 4. Request lifecycle

Every request passes through four `before_request` hooks, in registration
order. **Order matters** — the currency and language hooks must run before
the template context is built, and the CSRF guard must run before any view
mutates data.

### 4.1 `persist_currency()`

Reads `?currency=CODE` from the query string, stores it in a 30-day cookie,
and redirects to the same path with the `currency` parameter stripped. The
redirect is what keeps the URL clean; the cookie is what actually persists
the choice.

### 4.2 `persist_language()`

Identical mechanism for `?language=CODE`, with the language cookie.

### 4.3 `csrf_guard()`

Applies to every `POST`. Compares `request.form["csrf_token"]` against
`session["_csrf"]` using `secrets.compare_digest` (constant-time). A mismatch
flashes *"Security token expired. Please try again."* and redirects back to
the same path. **Every form in every template must include the token:**

```html
<input type="hidden" name="csrf_token" value="{{ csrf }}">
```

`csrf` is injected by the context processor, so it is always available.

### 4.4 `enforce_account_status()`

Runs on every request and handles accounts whose state changed *while a
session was open*:

| Situation | Action |
|---|---|
| Not logged in | Return (no-op) |
| Admin session | Return — admins are never restricted |
| User record missing (admin deleted the account) | Clear session, flash *"Your account is no longer available."*, redirect to `/` |
| Status is `blocked` | Clear session, flash *"Your account has been blocked. Please contact support."*, redirect to `/` |

`suspended` is deliberately **not** handled here — a suspended account stays
logged in and can browse; it is blocked from restricted actions by
`has_perm()` instead. See [04-access-rights.md](04-access-rights.md).

## 5. Template context

`inject_globals()` runs for every template render and injects:

| Variable | Type | Purpose |
|---|---|---|
| `site` | dict | Site-wide content (`name`, `tagline`, `currency`, `currencies`, `payment_enabled`) |
| `content` | dict | Every `site_data` blob, keyed by name |
| `cart_count` | int | Total quantity in the session cart |
| `csrf` | str | CSRF token for forms |
| `json` | module | `json.dumps` for inline templates |
| `n_apps` | int | Unread application count (admin badge) |
| `n_pend` | int | Pending/reviewing marketplace listings (admin badge) |
| `n_sellreq` | int | Pending seller-access requests (admin badge) |
| `currency` | str | Active currency code, e.g. `SSP` |
| `currencies` | list | Available currency definitions |
| `currency_symbol` | str | Symbol for the active currency |
| `language` | str | Active language code, e.g. `en` |
| `languages` | dict | All loaded language packs |
| `lang_dir` | str | `ltr` or `rtl` |
| `user` | dict | Session user (`username`, `is_admin`) or `None` |
| `is_admin` | bool | Whether the session user is an admin |

## 6. Key design decisions

### 6.1 JSON blobs instead of normalised tables

Editable site content (hero text, categories, products, testimonials,
partners) lives as one JSON blob per key in `site_data`. This means the admin
CMS can add, edit and remove *any* content type without a schema migration.

The trade-off: no relational integrity and no indexed queries on content. For
a catalogue of a few hundred products, that is a good trade.

Relational data that genuinely needs querying — orders, contact messages,
applications, payment records — uses real tables.

### 6.2 Protected keys

`PROTECTED_KEYS = {"admin_users", "users", "admin_account"}`.

`safe_import_content()` skips these keys, so importing a content backup can
never overwrite accounts or credentials. This is a security boundary, not a
convenience.

### 6.3 First-boot seeding only

`init_db()` inserts `site_data.json` **only when the `site_data` table is
empty**. After that, `data/site.db` is the source of truth and editing
`site_data.json` has no effect. To re-seed, delete `data/site.db` and
restart.

### 6.4 No ORM, no migrations framework

Schema changes are hand-written `ALTER TABLE` statements guarded by a
`PRAGMA table_info` check, so they are idempotent and run on every boot.
Example — the payment columns added in the two-sided payment release:

```python
_cols = [r["name"] for r in con.execute("PRAGMA table_info(orders)").fetchall()]
for _col, _def in [
    ("payment_method", "TEXT"),
    ("payment_status", "TEXT DEFAULT 'pending'"),
    ("payment_reference", "TEXT"),
    ("receipt_path", "TEXT"),
    ("paid_at", "TEXT"),
]:
    if _col not in _cols:
        con.execute(f"ALTER TABLE orders ADD COLUMN {_col} {_def}")
```

**This is exactly why access rights needed no migration**: the status and
permission flags live *inside* the existing `users` JSON blob. A new feature
that adds a top-level user field should follow the same approach unless it
needs to be queried relationally.

### 6.5 Sessions hold only identity

The session stores `{"username": ..., "is_admin": bool}`. Every permission
decision re-reads the user record from the database. The consequence: an
admin's change to a user's status or rights takes effect on the user's *next
request*, with no cache to invalidate and no session re-issue needed.

## 7. Extension points

| To add… | Do this |
|---|---|
| A public page | New route in the "PUBLIC ROUTES" block + a template in `templates/` |
| An admin page | New route in the admin block + `templates/admin_*.html` extending `admin_base.html` |
| A content type | Add a `site_data` key; the CMS reads/writes it generically |
| A permission flag | Add to `ACCESS_PERMS`, guard the route with `perm_required("flag")` — see [04-access-rights.md](04-access-rights.md) |
| An admin POST action | Add a branch to the `if act == "..."` chain of the target view |
| A language | Drop a JSON file in `static/lang/` — it is auto-discovered on boot |
| A currency | Add an entry to `DEFAULT_CURRENCIES` **or** to `site.currencies` in the CMS |

## 8. See also

- [02 — Data Model](02-data-model.md)
- [03 — Route Reference](03-routes.md)
- [04 — Access Rights](04-access-rights.md)
- [08 — Uploads & Security](08-uploads-security.md)
