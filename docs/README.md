# Free Online Shopping — Documentation

Technical documentation for the Flask storefront + admin CMS.

| # | Document | What it covers |
|---|---|---|
| 01 | [Architecture](01-architecture.md) | App layout, request lifecycle, module map, design decisions |
| 02 | [Data Model](02-data-model.md) | SQLite tables, `site_data` JSON blobs, user record shape |
| 03 | [Route Reference](03-routes.md) | Every route, its methods, guards and behaviour |
| 04 | [Access Rights](04-access-rights.md) | Account status, permission flags, enforcement points |
| 05 | [Admin CMS](05-admin-cms.md) | Every admin page and the POST actions it handles |
| 06 | [Payments](06-payments.md) | Two-sided payment system, methods, admin ledger |
| 07 | [i18n & Currency](07-i18n-currency.md) | Language files, translation filter, multi-currency |
| 08 | [Uploads & Security](08-uploads-security.md) | File validation, CSRF, hashing, access control |
| 09 | [Deployment](09-deployment.md) | Local run, Render, environment variables |
| 10 | [Testing](10-testing.md) | Smoke tests and the manual checklist |

Project history lives in the top-level [`CHANGELOG.md`](../CHANGELOG.md).

---

## Quick facts

| | |
|---|---|
| Framework | Flask 3.1.0 + Jinja2 |
| Database | SQLite (file-based, `data/site.db`) |
| Content model | One JSON blob per key in the `site_data` table |
| Entry point | `app.py` -> `app` (WSGI) |
| Default port | `8080` (macOS reserves 5000 for AirPlay) |
| Default admin | `admin` / `admin123` |
| Templates | `templates/` (29 files) |
| Static assets | `static/` (`style.css`, `app.js`, `lang/`, `img/`) |

## Quick start

```bash
pip3 install -r requirements.txt
python3 app.py            # http://127.0.0.1:8080
```

See [Deployment](09-deployment.md) for environment variables and Render setup.

---

# Maintaining this documentation

This documentation is **living documentation** — it must be updated in the same
commit as any change it describes. The rules below are the contract.

## When you MUST update the docs

| Change | Document to update |
|---|---|
| New or removed route | [03-routes.md](03-routes.md) — add the row, with its guards |
| New DB table or column | [02-data-model.md](02-data-model.md) — schema + migration note |
| New `site_data` blob key | [02-data-model.md](02-data-model.md) — key table |
| New/changed field on a user record | [02-data-model.md](02-data-model.md) + [04-access-rights.md](04-access-rights.md) |
| New permission flag or status | [04-access-rights.md](04-access-rights.md) — flags table + enforcement table |
| New enforcement point (route guard) | [04-access-rights.md](04-access-rights.md) — enforcement table |
| New admin page or POST action | [05-admin-cms.md](05-admin-cms.md) |
| Payment method or payment flow change | [06-payments.md](06-payments.md) |
| New language file / translation key | [07-i18n-currency.md](07-i18n-currency.md) |
| New currency | [07-i18n-currency.md](07-i18n-currency.md) — currency table |
| New env var | [09-deployment.md](09-deployment.md) — env var table + `app.py` header |
| New upload type or validation rule | [08-uploads-security.md](08-uploads-security.md) |
| Any user-visible behaviour change | [`CHANGELOG.md`](../CHANGELOG.md) — new entry |

## Update rules

1. **Same commit.** Docs and code land together. A feature commit that
   changes behaviour but leaves the docs stale is incomplete.
2. **Verify before you write.** Run the code, read the actual route
   decorators and templates, then document what *is*, not what you remember.
3. **Keep line references optional but useful.** Route tables name the view
   function; an `app.py` line number is a nice-to-have that goes stale, so it
   is only included where it aids navigation.
4. **Never document behaviour you have not confirmed.** If something is
   uncertain, mark it explicitly (`Not verified`) rather than guessing.
5. **Preserve the structure.** Keep the existing headings and tables so
   diffs stay readable and links keep working.

## How to keep route tables accurate

The route inventory in [03-routes.md](03-routes.md) is derived from the
decorators in `app.py`. To regenerate it after adding routes:

```bash
grep -n "@app.route" app.py
```

Then update the table, adding the guard column (`login_required`,
`admin_required`, `perm_required(...)`) that matches the decorators.

## Pre-commit checklist

```bash
# 1. Code still parses and imports
python3 -c "import ast; ast.parse(open('app.py').read())"

# 2. App boots and answers
python3 app.py &
curl -s localhost:8080/healthz

# 3. Docs mention anything new you added
git diff --stat
```

## Adding a new translation key

1. Add the key to **every** file in `static/lang/` (`en`, `ar`, `fr`, `sw`,
   `jac`, `am`).
2. Use it in a template as `{{ 'your.key'|t }}`.
3. Add a note to [07-i18n-currency.md](07-i18n-currency.md) if it introduces
   a new page or flow.

> The `t` filter is registered with `@pass_context` **on purpose**. Jinja
> constant-folds filters whose arguments are all literals, which would bake
> the first request's language into the compiled template. Do not remove
> `pass_context`.
