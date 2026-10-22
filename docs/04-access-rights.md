# 04 — Access Rights

Administrators can control, per customer account, **whether the account is
allowed to act** (status) and **which features it may use** (permissions).

This feature was added after the initial release and is documented here in
full because it touches authentication, routing and the admin UI.

---

## 1. Concepts

Each customer account has two independent dimensions:

| Dimension | Values | Effect |
|---|---|---|
| **Status** | `active`, `suspended`, `blocked` | Whether the account may act at all |
| **Permissions** | 5 boolean flags | Which features the account may use |

They compose like this:

| Status | Can sign in | Can browse | Can use restricted features |
|---|---|---|---|
| `active` | yes | yes | only the permissions granted |
| `suspended` | yes | yes | **no** — all restricted features are denied |
| `blocked` | **no** | no | no |

Admins are **never** restricted: `has_perm()` and `can_sell()` short-circuit
on `is_admin`.

## 2. Where the data lives

Both the status and the permissions are stored **inside the existing `users`
JSON blob**, as fields on the user record:

```json
{
  "username": "amina",
  "status": "suspended",
  "status_changed": "2026-10-20T10:02:11.004",
  "perms": {
    "shop": true,
    "sell": false,
    "payment": true,
    "apply": false,
    "contact": true
  },
  "perms_changed": "2026-10-20T10:02:44.881"
}
```

Because they are blob fields rather than table columns, **this feature
required no database migration**. Accounts created before the feature simply
have no `status`/`perms` keys, and the helpers treat them as fully active
with every permission granted.

## 3. Statuses

### 3.1 `active`

The default. The account behaves normally, subject to its permissions.

### 3.2 `suspended`

The account stays signed in and can browse the storefront, but **every
restricted action is denied**. Enforced inside `has_perm()`:

```python
def has_perm(perm):
    u = current_user()
    if not u:
        return False
    if u.get("is_admin"):
        return True
    rec = user_record(u.get("username", ""))
    if not rec:
        return False
    if user_status(rec) != "active":
        return False
    return user_perms(rec).get(perm, True)
```

Note the ordering: **status is checked before permissions**. A suspended
account fails the check regardless of which permission is being tested.

The customer sees the reason on `/myproducts`:

> Your account is **suspended**, so posting is not available. Please contact
> support.

### 3.3 `blocked`

The strongest restriction. A blocked account:

1. **Cannot log in.** `/login` checks the status after the password matches
   and refuses with *"Your account has been blocked. Please contact support."*
2. **Is signed out on its next request.** The `enforce_account_status()`
   `before_request` hook clears the session and redirects to `/`.
3. **Fails every permission check**, as a non-`active` status does.

Blocking is therefore effective **immediately**, even for a session that was
already open — the account is terminated on its next request rather than
waiting for the session to expire.

### 3.4 Accounts deleted while signed in

If an admin removes a user whose session is still open, the same hook
detects the missing record and ends the session with *"Your account is no
longer available."*

## 4. Permission flags

Defined in `ACCESS_PERMS`:

| Flag | Label shown to the admin | Gates |
|---|---|---|
| `shop` | Browse the shop and place orders | Cart add/update/clear, checkout |
| `sell` | Post products in the marketplace | Seller requests and product posting |
| `payment` | Manage payment methods and pay for orders | Saved payment methods, paying for an order |
| `apply` | Submit job applications | The job application form |
| `contact` | Send messages through the contact form | The contact form |

`DEFAULT_PERMS` is every flag set to `True`, and is applied to newly
registered accounts.

### 4.1 Effective permissions

```python
def user_perms(rec):
    """Effective permission map; unknown/absent flags default to allowed."""
    saved = (rec or {}).get("perms") or {}
    return {k: bool(saved.get(k, True)) for k in ACCESS_PERMS}
```

Three properties follow from this:

- A **legacy account** (no `perms` key) gets every flag `True`.
- A **partially configured account** gets `True` for any flag it does not
  mention.
- An **unknown flag** in the stored dict is ignored, because the result is
  built from `ACCESS_PERMS`, not from the stored data.

The default is always permissive on purpose: adding a new flag must not
silently revoke access on existing accounts.

## 5. The `perm_required` decorator

```python
def perm_required(perm, guest_ok=True):
    """Gate a route on a customer permission flag (admins always pass)."""
    def deco(f):
        @wraps(f)
        def w(*a, **kw):
            u = current_user()
            if not u:
                if guest_ok:
                    return f(*a, **kw)
                flash("Please log in first.", "warning")
                return redirect(url_for("login", next=request.path))
            if not has_perm(perm):
                flash(f"Your account does not have the “{perm}” permission right now.", "danger")
                return redirect(url_for("index"))
            return f(*a, **kw)
        return w
    return deco
```

### 5.1 `guest_ok` — why guests pass

With `guest_ok=True` (the default) an anonymous visitor reaches the view
normally. The check therefore only ever bites for a **signed-in account that
an admin has actually restricted**.

This is deliberate. The alternative — requiring a login to add to the cart or
send a contact message — would change the public site's behaviour for
everyone to solve a problem that only affects restricted accounts.

Use `guest_ok=False` when the action must require an account regardless of
restrictions:

```python
@app.route("/something", methods=["POST"])
@perm_required("shop", guest_ok=False)
def something():
    ...
```

### 5.2 Admin bypass

`has_perm()` returns `True` for admins, so admins pass every `perm_required`
gate. Admin routes use `admin_required` and are not affected by customer
permissions at all.

---

## 6. Enforcement points

The complete list of places where a permission is checked. Keep this table
in sync whenever a route is added or a flag is renamed.

| Route / action | Flag | Mechanism | What happens when denied |
|---|---|---|---|
| `POST /cart/add/<pid>` | `shop` | `@perm_required("shop")` | Flash + redirect to `/` |
| `POST /cart/update` | `shop` | `@perm_required("shop")` | Flash + redirect to `/` |
| `POST /cart/clear` | `shop` | `@perm_required("shop")` | Flash + redirect to `/` |
| `GET,POST /checkout` | `shop` | `@perm_required("shop")` | Flash + redirect to `/` |
| `GET,POST /user/payment` | `payment` | `login_required` + `@perm_required("payment")` | Flash + redirect to `/` |
| `GET,POST /order/pay/<oid>` | `payment` | `login_required` + `@perm_required("payment")` | Flash + redirect to `/` |
| `GET,POST /contact` | `contact` | `@perm_required("contact")` | Flash + redirect to `/` |
| `GET,POST /apply/<pid>` | `apply` | `@perm_required("apply")` | Flash + redirect to `/` |
| `POST /myproducts` (request_access) | `sell` | `has_perm("sell")` inside the view | Flash + redirect to `/myproducts` |
| `POST /myproducts` (add/edit/delete) | `sell` | `can_sell()` inside the view | Flash + redirect to `/myproducts` |
| Any request (blocked account) | — | `enforce_account_status()` | Session cleared, flash + redirect to `/` |
| `POST /login` (blocked account) | — | status check in `login()` | Login refused with a flash |

### 6.1 `can_sell()` — two independent checks

```python
def can_sell():
    u = current_user()
    if not u:
        return False
    if u.get("is_admin"):
        return True
    rec = user_record(u.get("username", ""))
    return bool(rec and rec.get("can_sell") and has_perm("sell"))
```

Posting a product requires **both**:

1. The **seller right** (`can_sell` on the record) — granted manually by an
   admin, or through the customer-requested review flow.
2. The **`sell` permission** — the access-rights flag.

These are separate on purpose. The seller right is a *marketplace* concept
(an admin vets each seller); the `sell` permission is an *access control*
concept (an admin can switch a feature off for an account without touching
marketplace policy). Revoking the `sell` permission immediately stops a
granted seller from posting, without changing their seller-right record.

### 6.2 What is deliberately **not** gated

| Route | Why it is open |
|---|---|
| `GET /` , `/shop`, `/product/<id>`, `/cart` | Browsing is public. The `shop` flag gates *ordering*, not looking. |
| `GET /order/<oid>` | Order confirmation is a receipt, not a restricted action. |
| `GET /account` | A customer must always be able to see their own orders and their rights. |
| `GET /uploads/<path>` | Static file serving. |

`suspended` accounts can therefore still browse, view their orders and see
their account page — they just cannot transact, apply, post or contact.

## 7. Admin interface

### 7.1 Where it lives

**Admin -> Users** (`/admin/users`). The table gained two columns:

| Column | Control |
|---|---|
| **Status** | A `<select>` dropdown (`active` / `suspended` / `blocked`) that submits on change, plus a pill showing a non-active status |
| **Access rights** | A collapsible `<details>` panel with one checkbox per permission flag, a **Save rights** button and a **Reset to default** button |

The seller-access column, which already existed, is unchanged.

### 7.2 The dropdown

```html
<select name="status" onchange="this.form.submit()">
  {% for s in statuses %}
  <option value="{{ s }}" {{ 'selected' if st == s }}>{{ s }}</option>
  {% endfor %}
</select>
```

Submitting on change means the admin never has to press a separate "Save"
button for a status change. The form is a normal POST with the CSRF token, so
it is protected by `csrf_guard()`.

### 7.3 The permission checkboxes

```html
<label class="inline">
  <input type="checkbox" name="{{ key }}" value="1" {{ 'checked' if perms.get(key, true) }}>
  {{ label }}
</label>
```

### 7.4 POST actions

All handled by the `if act == ...` chain in `admin_users()`:

| Action | Effect |
|---|---|
| `status` | Sets `status` and `status_changed` on the target user. An unrecognised value falls back to `active`. |
| `perms` | Sets every flag in `ACCESS_PERMS` from the submitted checkboxes and stamps `perms_changed`. |
| `reset_perms` | Restores `perms` to `DEFAULT_PERMS` (all allowed). |
| `grant` / `revoke` | The pre-existing seller-right actions. Unchanged. |
| `delete` | The pre-existing user removal. Unchanged. |

### 7.5 The checkbox gotcha

HTML checkboxes are **only submitted when ticked**. The handler therefore
must not use `request.form.get(key)` — an unticked box is simply absent from
the form data:

```python
cur = user_perms(u)
for k in ACCESS_PERMS:
    # checkboxes only submit when ticked
    cur[k] = (k in request.form)
u["perms"] = cur
```

`k in request.form` is the correct test. Using `request.form.get(k)` would
mean that *every* flag is cleared the moment the admin saves, and the form
could never keep a permission on.

### 7.6 Status validation

The submitted status is validated against `ACCESS_STATUSES` and falls back
to `active`:

```python
st = request.form.get("status", "active")
if st not in ACCESS_STATUSES:
    st = "active"
```

So a tampered or stale form can never put an account into an unknown state.

## 8. Customer-facing display

### 8.1 `/account`

Shows the current status as a pill and each permission as a pill:

```html
<span class="pill {{ 'ok' if my_status == 'active' else ('bad' if my_status == 'blocked' else 'warn') }}">{{ my_status }}</span>
{% for key, label in perm_labels.items() %}
  <span class="pill {{ 'ok' if my_perms.get(key, true) else 'bad' }}">{{ label }}</span>
{% endfor %}
```

Granted rights are green (`ok`), revoked rights are red (`bad`), and a
suspended status is amber (`warn`).

### 8.2 `/myproducts`

When posting is unavailable, the page explains **which** right is missing:

```html
{% if my_status != 'active' %}
  <p class="muted">Your account is <b>{{ my_status }}</b>, so posting is not available. Please contact support.</p>
{% elif not my_perms.get('sell', true) %}
  <p class="muted">The “sell” right is turned off on your account. Please contact support.</p>
{% elif request_status == 'pending' %}
  ...
{% else %}
  <form method="post"> ... request seller access ... </form>
{% endif %}
```

The three branches are ordered so the most specific reason wins: a
non-`active` status takes priority over the `sell` flag, which takes
priority over a pending seller request.

## 9. Effect on existing accounts

**No migration was needed, and no existing account lost access.** An account
created before the feature has no `status` key and no `perms` key, so:

- `user_status()` returns `"active"`.
- `user_perms()` returns every flag `True`.

The same permissiveness applies to a *new* flag added later: any flag not
mentioned in the stored data defaults to allowed.

## 10. Testing this feature

The manual checklist below is the minimum bar before shipping a change to
the access-rights code.

```bash
# 1. The app imports and boots
python3 -c "import ast; ast.parse(open('app.py').read())"
python3 app.py &          # then: curl -s localhost:8080/healthz
```

| # | Scenario | Expected |
|---|---|---|
| 1 | Register a new customer | Account is `active` with all flags `True` |
| 2 | Admin sets the account to `suspended` | Customer can still browse and sign in |
| 3 | Suspended customer adds to cart | Redirected to `/` with a danger flash |
| 4 | Suspended customer submits the contact form | Redirected to `/` |
| 5 | Admin sets the account to `blocked` | The customer is signed out on the next request |
| 6 | Blocked customer tries to log in | Login refused with a flash |
| 7 | Admin unticks `payment` only | All other rights still work; payment routes are denied |
| 8 | Admin clicks **Reset to default** | Every flag is `True` again |
| 9 | Admin ticks only `shop` | Contact, apply, payment and sell are all denied |
| 10 | A granted seller with `sell` unticked | Cannot post; the page explains why |
| 11 | Admin browses the shop and checks out | Admins are never restricted |
| 12 | An old account (no `status`/`perms`) | Fully active with every permission |

### 10.1 Pitfalls found while testing

These were test defects, not application defects — recorded so they are not
repeated:

- **Registering at the wrong URL.** `GET /register` redirects to
  `/login?tab=signup`; a POST must go to `/register` with the right fields.
- **Stale CSRF token.** The token is per session; re-read it from the page
  after logging in or after any redirect.
- **Wrong password.** A test that registers with one password and logs in
  with another will always fail.
- **Mis-parsing checkboxes.** An unticked checkbox is absent from the form
  data — parse with `k in form`, not `form.get(k)`.
- **Inspecting the wrong user's row.** When several users exist, select the
  row by username, not by row index.

## 11. See also

- [02 — Data Model](02-data-model.md) — where the fields are stored
- [03 — Route Reference](03-routes.md) — every route and its guards
- [05 — Admin CMS](05-admin-cms.md) — the full admin page reference
- [10 — Testing](10-testing.md) — the general test checklist

