# 02 — Data Model

## 1. Overview

The system uses **two storage strategies** side by side:

1. **Relational tables** for data that needs querying, ordering or filtering
   (orders, messages, applications, payments).
2. **JSON blobs** in a single `site_data` table for editable content and for
   account records.

All access goes through two helpers:

```python
get_blob(key, default=None)   # -> parsed JSON (list/dict/str)
set_blob(key, value)          # -> writes json.dumps(value) under key
```

## 2. Relational schema

Created by `init_db()` in `app.py`. All tables are `IF NOT EXISTS`, and column
additions are idempotent `ALTER TABLE` statements, so the schema converges on
every boot.

### 2.1 `site_data` — the JSON blob store

| Column | Type | Notes |
|---|---|---|
| `key` | TEXT | Primary key |
| `value` | TEXT | JSON-encoded payload |

One row per content type. See section 3 for the key list.

### 2.2 `orders`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK, autoincrement |
| `customer_name` | TEXT | Matched against `username` to list a user's orders |
| `email` | TEXT | Optional; used for the confirmation email |
| `phone` | TEXT | Required at checkout |
| `address` | TEXT | Required at checkout |
| `city` | TEXT | Defaults to `Juba` |
| `notes` | TEXT | Free text |
| `items_json` | TEXT | JSON array of `{product, qty, line}` snapshots |
| `total` | REAL | Order total in the base currency |
| `status` | TEXT | Defaults to `pending` |
| `created` | TEXT | ISO timestamp (UTC) |
| `payment_method` | TEXT | Chosen method label |
| `payment_status` | TEXT | Defaults to `pending` |
| `payment_reference` | TEXT | Customer-supplied reference |
| `receipt_path` | TEXT | Filename in `data/uploads/` |
| `paid_at` | TEXT | ISO timestamp when marked paid |

The last five columns were added by the two-sided payment release as an
idempotent migration.

### 2.3 `contact_messages`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `name`, `email`, `subject`, `message` | TEXT | The enquiry |
| `created` | TEXT | ISO timestamp |

### 2.4 `applications`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `job` | TEXT | Product name of the job listing |
| `name`, `email`, `phone`, `message` | TEXT | Applicant details |
| `doc` | TEXT | Filename in `data/app_docs/` (private) |
| `status` | TEXT | Defaults to `new` |
| `created` | TEXT | ISO timestamp |

### 2.5 `admin_payments` — the admin-side ledger

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `type` | TEXT | Defaults to `ad_fee` (advertising/posting fee) |
| `user_id` | TEXT | Username the fee relates to |
| `product_id` | INTEGER | Related product, when applicable |
| `amount` | REAL | Fee amount |
| `currency` | TEXT | Defaults to `SSP` |
| `method` | TEXT | Payment method used |
| `status` | TEXT | Defaults to `pending` |
| `reference` | TEXT | Transaction reference |
| `receipt_path` | TEXT | Filename in `data/uploads/` |
| `created` | TEXT | ISO timestamp |

## 3. `site_data` blob keys

| Key | Type | Purpose | Protected? |
|---|---|---|---|
| `site` | dict | Name, tagline, hero copy, `currency`, `currencies`, `payment_enabled` | no |
| `categories` | list | Product categories (`id`, `name`, ...) | no |
| `products` | list | The full catalogue, including marketplace posts | no |
| `testimonials` | list | Customer quotes on the homepage | no |
| `partners` | list | Partner logos | no |
| `fees` | dict | `per_post` — the advertising fee charged to sellers | no |
| `users` | list | **Customer accounts** — see section 4 | **yes** |
| `admin_users` | list | **Admin accounts** — see section 4 | **yes** |
| `admin_account` | dict | Admin profile/settings | **yes** |

Protected keys are listed in `PROTECTED_KEYS` and skipped by
`safe_import_content()`, so a content import can never clobber accounts.

### 3.1 `site` keys

| Key | Type | Default | Notes |
|---|---|---|---|
| `name` | str | `Free Online Shopping` | Store name |
| `tagline` | str | — | Footer/SEO tagline |
| `hero_title` | str | — | Homepage heading |
| `hero_subtitle` | str | — | Homepage subheading |
| `hero_cta` | str | `Shop Now` | Homepage button label |
| `currency` | str | `SSP` | Base currency code |
| `currencies` | list | 17 entries | Available currencies (see [07-i18n-currency.md](07-i18n-currency.md)) |
| `payment_enabled` | bool | `true` | Master switch for the customer payment system |

### 3.2 `products` entries

| Field | Type | Notes |
|---|---|---|
| `id` | int | Unique product id |
| `name` | str | Display name |
| `category` | str | Category id, or the literal `jobs` for job listings |
| `price` | num | Price in the base currency |
| `old_price` | num | Strike-through "was" price; `0` = none |
| `stock` | int | Units available; decremented on checkout |
| `badge` | str | e.g. `New`, `Sale`; empty for none |
| `image` | str | Path under `/static/img/` or `/uploads/` |
| `desc` | str | Description |
| `post_type` | str | `user` for marketplace posts; absent for catalogue items |
| `status` | str | `pending` / `reviewing` / `approved` / `rejected` (marketplace only) |
| `seller` | str | Username who posted it (marketplace only) |

**Visibility rule** — `visible_products()` returns admin catalogue items plus
marketplace posts whose `status == "approved"`:

```python
return [p for p in get_blob("products", [])
        if p.get("post_type") != "user" or p.get("status") == "approved"]
```

### 3.3 `categories` entries

Each has an `id` and a `name`. A product's `category` field references the
category `id`. The `jobs` category is special: products in it are job
listings and render an *Apply* button that links to `/apply/<id>`.

### 3.4 `fees`

```json
{ "per_post": 5000 }
```

`ad_fee()` reads `per_post` and defaults to `5000` if the blob is missing.
This is the advertising fee charged to sellers posting to the marketplace.

## 4. The user record

Both `users` (customers) and `admin_users` (admins) are lists of dicts.

### 4.1 Customer record (`users`)

| Field | Type | Set at | Notes |
|---|---|---|---|
| `username` | str | register | Unique, 3-50 chars. The key used everywhere. |
| `email` | str | register | Optional, HTML-escaped, 150 chars max |
| `pw_hash` | str | register | Werkzeug password hash — never the raw password |
| `created` | str | register | ISO timestamp |
| `status` | str | register / admin | `active` (default), `suspended`, `blocked` |
| `perms` | dict | register / admin | Feature flags — see [04-access-rights.md](04-access-rights.md) |
| `status_changed` | str | admin | ISO timestamp of the last status change |
| `perms_changed` | str | admin | ISO timestamp of the last rights change |
| `can_sell` | bool | admin | The **seller right** — grants marketplace posting |
| `can_sell_granted` | str | admin | ISO timestamp the seller right was granted |
| `sell_request` | str | customer | `pending` while a seller request awaits review |
| `payment_methods` | list | customer | Saved payment methods — see [06-payments.md](06-payments.md) |

Example record for a newly registered customer:

```json
{
  "username": "amina",
  "email": "amina@example.com",
  "pw_hash": "scrypt:32768:8:1$...",
  "created": "2026-10-20T09:14:22.301",
  "status": "active",
  "perms": {
    "shop": true, "sell": true, "payment": true,
    "apply": true, "contact": true
  }
}
```

### 4.2 Admin record (`admin_users`)

| Field | Type | Notes |
|---|---|---|
| `username` | str | Unique |
| `email` | str | Optional; admins can also log in with it |
| `pw_hash` | str | Werkzeug password hash |
| `created` | str | ISO timestamp |

Admins have **no** `status` or `perms` fields and are never restricted.

### 4.3 Legacy accounts

Accounts created before the access-rights feature have no `status` and no
`perms` keys. The helpers handle this explicitly:

```python
def user_status(rec):
    """Effective account status; missing/legacy accounts are active."""
    if not rec:
        return "active"
    st = rec.get("status", "active")
    return st if st in ACCESS_STATUSES else "active"

def user_perms(rec):
    """Effective permission map; unknown/absent flags default to allowed."""
    saved = (rec or {}).get("perms") or {}
    return {k: bool(saved.get(k, True)) for k in ACCESS_PERMS}
```

**The default is always permissive.** An old account must not silently lose
access because a new field was introduced.

## 5. Storage locations

| Path | Public? | Contents |
|---|---|---|
| `data/site.db` | no | The SQLite database |
| `data/uploads/` | **yes** via `/uploads/<path>` | Product images, payment receipts |
| `data/app_docs/` | **no** | Applicant CVs and documents |

`DATA_DIR` overrides the parent directory. The subdirectories are created on
import (`os.makedirs(..., exist_ok=True)`).

## 6. Reading and writing

```python
# Read
products = get_blob("products", [])
site = get_blob("site", {})

# Write
site["payment_enabled"] = False
set_blob("site", site)

# Read-modify-write a single user
users = get_blob("users", [])
for u in users:
    if u["username"] == "amina":
        u["status"] = "suspended"
set_blob("users", users)
```

`get_blob`/`set_blob` each open and close their own connection. Read-modify-
write cycles are **not** wrapped in a transaction — with a single-process
Flask app and low write concurrency this is acceptable, but it is the first
thing to revisit if the app is scaled to multiple workers.

## 7. See also

- [01 — Architecture](01-architecture.md)
- [04 — Access Rights](04-access-rights.md)
- [06 — Payments](06-payments.md)
