# 05 — Admin CMS

Everything under `/admin` requires an admin session. The `admin_required`
decorator redirects anonymous visitors to the login page and flashes
*"Admin login required."*

Admin accounts live in the `admin_users` blob and are managed from
**Admin -> Account**. The last admin cannot be deleted.

---

## 2. Redesigned admin interface

The admin UI is a single control panel built on one app shell
(`admin_base.html`). Every admin page shares the shell, so navigation,
the command palette, the theme toggle and the flash notifications feel like
one cohesive app rather than a set of independent pages.

### 2.1 Shell layout

| Part | Markup | Behaviour |
|---|---|---|
| Sidebar (`.adm-side`) | `templates/admin_base.html` | Collapsible vertical drawer: nav groups (Overview, Store, People, Site), badge counters, the admin's user chip and the logout link. |
| Overlay (`.adm-overlay`) | `templates/admin_base.html` | Semi-transparent backdrop. Tapping it closes the drawer on narrow viewports; carries `data-drawer-close`. |
| Top bar (`.adm-top`) | `templates/admin_base.html` | Current page title/subtitle, the command-palette trigger (`data-palette-open`), a link to the storefront and the theme toggle (`data-theme-toggle`). |
| Content (`.adm-main`) | `templates/admin_base.html` | Page head (title + subtitle) followed by the `admin` block with the page's cards. |

### 2.2 Components

- **Command palette** (`.adm-palette`). Press `Cmd+K` / `Ctrl+K` or tap the
  search icon to open a full-height list of every admin page. Type to filter;
  arrow keys to navigate, Enter to open, Esc to close. Each palette item
  carries a `data-palette-item` attribute that the filter matches against,
  and the first visible item is auto-selected for keyboard navigation.
- **Flash toasts.** `admin_base.html` renders every `get_flashed_messages()`
  as a `.adm-flash` element; `admin.js` lifts each one into a dismissible
  toast that auto-dismisses after ~5 s (or on click).
- **Client-side table filters.** Any `<input data-filter-target="...">`
  hides and shows matching rows; an element targeted by
  `data-filter-empty` is shown when no rows match. The payment ledger and
  the users list both use this pattern.
- **Master switch.** `admin_payment_toggle.html` uses the
  `.adm-switch` / `.adm-switch-track` toggle for the payment-system master
  switch, with a current-state panel beside it.
- **Cards and forms.** `.adm-card`, `.adm-form`, `.adm-form-actions`,
  `.adm-btn`, `.adm-badge`, `.adm-switch` style every admin page.

### 2.3 Responsive behaviour

- Below a narrow breakpoint the sidebar collapses behind the overlay and is
  opened with the burger button. The top-bar title and search are hidden so
  the page head stays usable on small screens.
- Wide tables (payment ledger, users list, orders) live inside
  `.adm-table-wrap` with horizontal scrolling, so the action grid stays
  readable on narrow viewports.
- The payment ledger and user tables show a "no matching rows" empty state
  when the client-side filter has no results.

### 2.4 Behaviour notes

- The payment settings page guards the master switch: when
  `site.payment_enabled` is off, the payment ledger pages redirect to
  `/account` and the toggle card shows the disabled state. Only Cash on
  Delivery is offered to customers at checkout; admin payment records stay
  viewable and are never blocked by the toggle.
- All CSS for the panel lives in `static/admin.css` and JS in
  `static/admin.js`; both are dependency-free and need no build step.


## 3. Page reference

| Page | Route | Template | Purpose |
|---|---|---|---|
| Dashboard | `/admin` | `admin_dash.html` | Counts of orders, messages, listings, applications, seller requests |
| Content | `/admin/content` | `admin_content.html` | Edit all editable site content |
| Products | `/admin/products` | `admin_products.html` | Manage the catalogue |
| Listings | `/admin/listings` | `admin_listings.html` | Review marketplace postings |
| Listing review | `/admin/listings/review/<pid>` | `admin_review.html` | Approve / reject one posting |
| Orders | `/admin/orders` | `admin_orders.html` | Orders and their status |
| Messages | `/admin/messages` | `admin_messages.html` | Contact enquiries |
| Applications | `/admin/applications` | `admin_applications.html` | Job applications |
| Application document | `/admin/applications/<aid>/doc` | — | Serve a private applicant document |
| **Users** | `/admin/users` | `admin_users.html` | **Customers, status and access rights** |
| Account | `/admin/account` | `admin_account.html` | Admin accounts and credentials |
| Payments | `/admin/payments` | `admin_payments.html` | Payment ledger and ad-fee recording |
| Payment settings | `/admin/settings/payments` | `admin_payment_toggle.html` | Master switch for the payment system |
| Export | `/admin/export` | — | Download all content as JSON |
| Import | `/admin/import` | `admin_import.html` | Import content JSON |

All admin templates extend `admin_base.html`, which provides the admin
navigation, the badge counters (`n_apps`, `n_pend`, `n_sellreq`) and the
logout link.

## 4. Dashboard

`/admin` shows a summary and shortcuts. The badge counts come from the
context processor:

| Badge | Source |
|---|---|
| `n_apps` | `SELECT COUNT(*) FROM applications` |
| `n_pend` | Products with `post_type == "user"` and status in (`pending`, `reviewing`) |
| `n_sellreq` | Users with `sell_request == "pending"` and `can_sell` false |

## 5. Content CMS

`/admin/content` edits the `site` blob. These fields are written:

`name`, `tagline`, `hero_title`, `hero_subtitle`, `hero_cta`, `currency`,
`announcement`, `about`, `mission`, `contact_email`, `contact_phone`,
`address`, `footer_text`.

The `currencies` list is submitted as a **JSON textarea** and parsed with
`json.loads`; invalid JSON is rejected with *"Currency list is invalid JSON
— not saved."* and the rest of the form is still saved.

Other editable keys (`categories`, `products`, `testimonials`, `partners`,
`fees`) are managed on their own admin pages. Protected keys
(`admin_users`, `users`, `admin_account`) are **never** overwritten by an
import. See section 11.

### 5.1 Image management

Content sections with images support up to 8 images per entry
(`collect_images(maxn=8)`). Each image can be set as primary or deleted:

| Action | Effect |
|---|---|
| `img_primary` | Marks an image as the main one |
| `img_delete` | Removes an image from the entry |

Uploads are validated by magic bytes — see
[08-uploads-security.md](08-uploads-security.md).

## 6. Products

`/admin/products` manages the catalogue.

| Action | Effect |
|---|---|
| `add` | Creates a catalogue product |
| `edit` | Updates an existing product |
| `delete` | Removes a product |
| `stock` | Adjusts stock |
| `img_primary` | Marks an image as the main one |
| `img_delete` | Removes an image from the product |

Catalogued products created here have no `post_type`, so they are always
publicly visible. Only marketplace posts (created by customers) go through
review.

The advertising fee is **not** set here — it lives on the Listings page.

## 7. Listings (marketplace review)

`/admin/listings` lists every customer-posted product — including those
still `pending`, which are invisible on the public site. Each entry shows the
seller and the posting date.

| Action | Effect |
|---|---|
| `fee_set` | Sets the advertising fee (`fees.per_post`), floored at 0, default 5000 |
| `approve` | `status = "approved"` — the post becomes publicly visible |
| `reject` | `status = "rejected"` — stays hidden, the seller can edit and resubmit |
| `fee_paid` | `fee_status = "paid"` |
| `fee_unpaid` | `fee_status = "unpaid"` |
| `delete` | Removes the post and deletes its uploaded images that are no longer referenced |

> **Quirk.** If the payment system is disabled, `/admin/listings` flashes
> *"The payment system is currently disabled."* and redirects to
> `/admin/payments` instead of rendering the page.

### 7.1 Listing review

`/admin/listings/review/<pid>` handles a single listing and supports:

| Action | Effect |
|---|---|
| `notes` | Saves `review_notes` (visible to the seller); a `pending` listing moves to `reviewing` |
| `approve` | `status = "approved"`, stamps `approved_at` |
| `reject` | `status = "rejected"`, stamps `reviewed_at` |
| `fee_paid` | `fee_status = "paid"` |
| `fee_unpaid` | `fee_status = "unpaid"` |

Notes are attached to whichever action is used — approving or rejecting also
saves any text typed into the notes field.

Because `visible_products()` only exposes `post_type == "user"` products with
`status == "approved"`, an unapproved post cannot be seen, searched or
added to the cart.

## 8. Orders

`/admin/orders` lists all orders newest-first. The action is chosen with a
hidden `oid` field.

| Action | Effect |
|---|---|
| `verify_payment` | `payment_status = 'paid'`, stamps `paid_at` |
| `reject_payment` | `payment_status = 'rejected'` |
| anything else | Sets the order `status` from the submitted value (default `pending`) |

Payment-related columns (`payment_method`, `payment_status`,
`payment_reference`, `receipt_path`, `paid_at`) are displayed here.

## 9. Messages

`/admin/messages` lists contact-form submissions newest-first. The only
action is **delete**, identified by a hidden `mid` field — the row is
removed from `contact_messages`.

The contact form itself is gated by the `contact` permission — see
[04-access-rights.md](04-access-rights.md).

## 10. Applications

`/admin/applications` lists job applications newest-first. Two distinct
forms are supported, distinguished by their hidden fields:

| Field present | Effect |
|---|---|
| `did` | **Delete** the application and remove its uploaded document from disk |
| `aid` | **Update the status** to one of `new`, `reviewing`, `shortlisted`, `hired`, `rejected` — an unrecognised value falls back to `new` |

The document is deleted from `data/app_docs/` only if the file still exists;
a missing file is ignored rather than raising.

### 10.1 Private document download

`GET /admin/applications/<aid>/doc` streams the applicant's uploaded file
from `data/app_docs/`. That directory is **not** served by `/uploads/`, so
the documents are reachable only through this admin-gated route.

## 11. Users — accounts, status and access rights

`/admin/users` is the customer management page. The table has one row per
customer with these columns:

| Column | Controls | POST action |
|---|---|---|
| Username | Plain text | — |
| Email | Plain text | — |
| Joined | Creation timestamp | — |
| Seller access | **Grant** / **Revoke** buttons, plus a *pending* badge for open requests | `grant` / `revoke` |
| **Status** | A dropdown (`active` / `suspended` / `blocked`) that submits on change | `status` |
| **Access rights** | A collapsible panel of permission checkboxes, with **Save rights** and **Reset to default** | `perms` / `reset_perms` |
| (last) | **Remove** button, with a confirm prompt | `delete` |

### 11.1 Seller access (pre-existing)

Granting sets `can_sell = True` and stamps `can_sell_granted`; revoking sets
`can_sell = False`. Both clear any pending `sell_request`.

The seller right alone is not enough to post — the account must also hold
the `sell` permission. See section 9.3.

### 11.2 Status

```python
elif act == "status":
    st = request.form.get("status", "active")
    if st not in ACCESS_STATUSES:
        st = "active"
    for u in users:
        if u.get("username") == request.form.get("username"):
            u["status"] = st
            u["status_changed"] = datetime.utcnow().isoformat()
```

The value is validated against `ACCESS_STATUSES`; anything unrecognised
falls back to `active`.

### 11.3 Access rights

```python
elif act == "perms":
    target = request.form.get("username")
    for u in users:
        if u.get("username") == target:
            cur = user_perms(u)
            for k in ACCESS_PERMS:
                # checkboxes only submit when ticked
                cur[k] = (k in request.form)
            u["perms"] = cur
            u["perms_changed"] = datetime.utcnow().isoformat()
```

Two details matter:

- `k in request.form`, not `request.form.get(k)` — unticked checkboxes are
  absent from the payload.
- The result is written as a **complete** map, so removing a flag from
  `ACCESS_PERMS` in code effectively removes it from every account on the
  next save.

`reset_perms` restores `perms` to `DEFAULT_PERMS` (all flags allowed).

### 11.4 Removing a user

`delete` removes the user from the `users` blob. It does **not** delete
their orders, applications or messages — those rows are keyed by
`customer_name` / `name` and are kept for accounting.

An open session belonging to the removed account is terminated on its next
request by `enforce_account_status()`.

### 11.5 The full behaviour of a user row

The status dropdown and the access-rights panel are **independent** forms.
Each carries its own `csrf_token`, its own hidden `action`, and the target
`username`, so they can be submitted in any order without interfering.

## 12. Account

`/admin/account` manages admin accounts.

| Action | Effect |
|---|---|
| `add` | Adds an admin (username 1+ chars, password 4+, unique username) |
| `password` | Changes the signed-in admin's password |
| `email` | Changes the signed-in admin's email |
| `delete` | Removes an admin — **refused for the last remaining admin** |

The last-admin guard is:

```python
elif act=="delete":
    if len(admins)>1:
        admins=[a for a in admins if a["username"]!=request.form.get("username")]
        set_blob("admin_users", admins); flash("Admin removed.","info")
    else: flash("Cannot delete last admin.","danger")
```

### 12.1 Logging in as an admin

`find_user_by_login()` matches either the username **or** the email address,
case-insensitively. The `is_admin` flag on the session is set from whether
the record came from `admin_users`.

## 13. Export and import

`GET /admin/export` returns every `site_data` blob as a JSON download.

`POST /admin/import` accepts a JSON file and merges it via
`safe_import_content()`:

```python
PROTECTED_KEYS = {"admin_users", "users", "admin_account"}

def safe_import_content(new_data: dict):
    """Merge imported JSON but NEVER overwrite protected keys."""
    for k, v in new_data.items():
        if k in PROTECTED_KEYS:
            continue
        ...
```

**Security boundary.** An import can never overwrite accounts or
credentials, even from a backup file that contains them.

## 14. Payments pages

`/admin/payments` shows the admin-side ledger of `admin_payments` rows and
lets an admin record an ad-fee payment. The target row is identified by a
hidden `pid` field.

| Action | Effect |
|---|---|
| `verify` | `status = 'paid'` on the `admin_payments` row |
| `reject` | `status = 'rejected'` on the `admin_payments` row |
| `record` | Inserts a new `ad_fee` row (user, amount, method, reference, optional receipt upload) with `status = 'pending'` |

Like `/admin/listings`, this page refuses to render while the payment system
is disabled — it flashes and redirects to itself. The ledger rows are
filterable client-side (seller, reference, method, status) and show a
"no matching payments" empty state when the filter matches nothing.

`/admin/settings/payments` toggles `site.payment_enabled`, the master switch
for the customer-facing payment system. It renders a `.adm-switch` toggle
plus a "current state" card that shows an enabled/disabled badge and, when
disabled, a hint that only Cash on Delivery is offered to customers. When
the switch is off, checkout accepts only Cash on Delivery and the payment
management pages redirect to `/account`.

See [06-payments.md](06-payments.md).

## 15. Adding an admin page

1. Add the route in the admin block of `app.py` with `@admin_required`.
2. Create `templates/admin_<name>.html` extending `admin_base.html`.
3. Every POST form needs `<input type="hidden" name="csrf_token" value="{{ csrf }}">`.
4. If the page handles POST actions, branch on `request.form.get("action")`.
5. Add the page to the admin navigation in `templates/admin_base.html`.
6. Document the page in this file and add the route to
   [03-routes.md](03-routes.md).

## 16. See also

- [03 — Route Reference](03-routes.md)
- [04 — Access Rights](04-access-rights.md)
- [06 — Payments](06-payments.md)
