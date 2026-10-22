# Changelog

All notable changes to **Free Online Shopping** are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added

- **Customer access rights.** Every customer account now carries an account
  status and a set of feature permission flags, manageable from
  **Admin -> Users**.
  - Account status: `active`, `suspended`, `blocked`.
  - Permission flags: `shop`, `sell`, `payment`, `apply`, `contact`.
  - Status and permissions are stored inside the existing `users` JSON blob,
    so **no database migration** was required.
- `perm_required(perm, guest_ok=True)` route decorator, plus request-level
  enforcement for accounts that were deleted or blocked while a session was
  open (`enforce_account_status`).
- Blocked accounts are signed out on their next request and are refused at
  login.
- Suspended accounts keep browsing the storefront but fail every
  `has_perm()` check.
- New admin POST actions on `/admin/users`: `status`, `perms`, `reset_perms`.
- **Status** column (dropdown + pill) and **Access rights** column
  (collapsible checkbox panel) on the admin Users page.
- Customer-facing status and permission indicators on `/account` and
  `/myproducts`.
- Access-rights styling in `static/style.css` (`.rights`, `.acctstatus`).
- **Redesigned admin panel.** A Control-Panel-style app shell shared by
  every admin page: a collapsible sidebar drawer with a backdrop overlay,
  a fixed top bar (page title, command palette, storefront link, theme
  toggle persisted to `localStorage`) and a `Cmd/Ctrl+K` command palette
  listing all pages.
- **Flash-toast notifications.** Admin flash messages render as
  auto-dismissing, click-to-dismiss toasts (`static/admin.js`).
- **Client-side table filters.** The payment ledger and users list are
  keyword-filterable with a "no matching rows" empty state
  (`docs/05-admin-cms.md`).

### Changed

- Admin panel styling now ships in the dedicated `static/admin.css`
  (`.adm-*` design system), with JS behaviour (drawer, palette, theme,
  toasts, filters) in `static/admin.js`; both are dependency-free.
- Admin payment pages refined: `admin_payments.html` uses the `.adm-card` /
  `.adm-table` / `.adm-form` layout and the ledger empty state is rendered
  outside the row loop; `admin_payment_toggle.html` uses a `.adm-switch`
  master toggle with an enabled/disabled state card.

- Seller posting now requires **both** the existing seller right
  (`can_sell`) and the new `sell` permission.

---

## [0.9.0] — 2026-10-20

### Added

- Internationalisation with 6 languages (`en`, `ar`, `fr`, `sw`, `jac`,
  `am`) via `static/lang/*.json` and the `t` template filter.
- Multi-currency support with 17 currencies, a currency switcher, and the
  `curfmt` filter.
- Admin login by **email address** as well as username.
- Price-range filter on the shop filter bar.
- Restyled category filter chips on the homepage and shop.
- Auto-fitting product grid and filter rows for all screen sizes.
- Admin payment toggle with proper guards and a `pay_enabled` template flag.
- Two-sided payment system: customer checkout plus an admin ledger.

### Fixed

- Auth globals (`user`, `is_admin`) are now correctly injected into all
  templates.
- The `t` filter is registered with `@pass_context` so Jinja no longer
  constant-folds the first request's language into compiled templates.

---

## [0.8.0] — 2026-10-19

### Added

- Initial Flask store: catalogue, cart, checkout, orders, contact form,
  user accounts, marketplace listings, job applications and a full
  `/admin` CMS.
- JSON-blob content model in the `site_data` table, seeded once from
  `site_data.json`.
- Upload validation by magic bytes; applicant documents stored privately
  outside the public `/uploads` path.
- Email over the HTTPS Resend API, with a log-only fallback.
- `render.yaml` and `Procfile` for Render deployment.
