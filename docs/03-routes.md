# 03 — Route Reference

Every route in `app.py`, in source order. The **Guards** column is the
decorator chain that must pass for the view to run.

**Guard reference**

| Guard | Effect |
|---|---|
| `login_required` | Redirects to the login page if no user is signed in |
| `admin_required` | Redirects to the login page unless the session user is an admin |
| `perm_required("x")` | Blocks the action if the signed-in customer lacks the `x` permission (guests pass by default) |

`perm_required` is documented in detail in
[04-access-rights.md](04-access-rights.md).

---

## 1. Public storefront

| Method | Path | View | Guards | Purpose |
|---|---|---|---|---|
| GET | `/` | `index` | — | Homepage: hero, categories, featured products, testimonials, partners |
| GET | `/shop` | `shop` | — | Catalogue with search, price range, sort and category filters |
| GET | `/product/<int:pid>` | `product_detail` | — | Single product page |
| GET | `/cart` | `cart` | — | View the session cart |
| POST | `/cart/add/<int:pid>` | `cart_add` | `perm_required("shop")` | Add an item to the cart |
| POST | `/cart/update` | `cart_update` | `perm_required("shop")` | Change quantities / remove items |
| POST | `/cart/clear` | `cart_clear` | `perm_required("shop")` | Empty the cart |
| GET,POST | `/checkout` | `checkout` | `perm_required("shop")` | Checkout form; creates the order, decrements stock |
| GET | `/order/<int:oid>` | `order_success` | — | Order confirmation page |
| GET | `/uploads/<path:fname>` | `uploads` | — | Serve a public uploaded file |
| GET | `/healthz` | `healthz` | — | Liveness probe (used by Render) |

### 1.1 `cart_add`

Verifies the product is in `visible_products()` (so unapproved marketplace
posts cannot be added), clamps the quantity to 1-99, and merges into
`session["cart"]` keyed by product id as a string.

### 1.2 `checkout`

GET renders the form. POST validates `name`, `phone`, `address` and the
email format, then:

1. Inserts a row into `orders`.
2. Decrements `stock` for every product in the cart (floored at 0).
3. Clears the session cart.
4. Sends a confirmation email if an email address was given.
5. Redirects to `/order/<id>` for Cash on Delivery, or to
   `/order/pay/<id>` otherwise.

If the payment system is disabled (`site.payment_enabled` is false), only
Cash on Delivery is accepted.

## 2. Payments (customer side)

| Method | Path | View | Guards | Purpose |
|---|---|---|---|---|
| GET,POST | `/user/payment` | `user_payment` | `login_required`, `perm_required("payment")` | Manage saved payment methods |
| GET,POST | `/order/pay/<int:oid>` | `order_pay` | `login_required`, `perm_required("payment")` | Pay for a specific order |

Both redirect to `/account` with a warning when the payment system is
disabled. See [06-payments.md](06-payments.md).

## 3. Contact and applications

| Method | Path | View | Guards | Purpose |
|---|---|---|---|---|
| GET,POST | `/contact` | `contact` | `perm_required("contact")` | Contact form; stores a `contact_messages` row |
| GET,POST | `/apply/<int:pid>` | `apply` | `perm_required("apply")` | Job application; stores an `applications` row |

`apply` only accepts products whose `category == "jobs"`; anything else is a
404. Uploaded CVs are stored privately in `data/app_docs/`.

## 4. Authentication and account

| Method | Path | View | Guards | Purpose |
|---|---|---|---|---|
| GET,POST | `/register` | `register` | — | Create a customer account |
| GET,POST | `/login` | `login` | — | Sign in as customer or admin |
| GET | `/logout` | `logout` | — | Clear the session |
| GET | `/account` | `account` | `login_required` | Order history, status and rights indicators |
| GET,POST | `/myproducts` | `myproducts` | `login_required` | Seller marketplace: post, edit, delete listings |

### 4.1 `register`

GET redirects to `/login?tab=signup` — sign-up lives on the combined login
page. POST validates the username (3+ chars) and password (4+ chars),
rejects duplicates case-insensitively, and creates the record with
`status: "active"` and all permissions granted.

### 4.2 `login`

Accepts a username **or** an email address in the same field. Customers with
status `blocked` are refused with a flash message; `suspended` customers may
still sign in. The session stores only `username` and `is_admin`.

### 4.3 `myproducts`

Handles these POST actions:

| Action | Requires | Effect |
|---|---|---|
| `request_access` | `has_perm("sell")` | Sets `sell_request = "pending"` on the user record |
| `add` / `edit` / `delete` | `can_sell()` | Creates, edits or deletes a marketplace listing |

`can_sell()` requires **both** the admin-granted seller right and the `sell`
permission. New listings are created with `post_type: "user"` and
`status: "pending"`, so they await admin review before appearing publicly.

The page also explains to the customer why posting is unavailable when the
account is suspended or the `sell` right is off.

---

## 5. Admin CMS

All admin routes require `admin_required`. Anonymous access redirects to the
login page.

| Method | Path | View | Purpose |
|---|---|---|---|
| GET | `/admin` | `admin_dash` | Dashboard: counts, badges, shortcuts |
| GET,POST | `/admin/content` | `admin_content` | Edit all editable site content |
| GET,POST | `/admin/products` | `admin_products` | Manage the catalogue |
| GET,POST | `/admin/listings` | `admin_listings` | Review marketplace listings |
| GET,POST | `/admin/listings/review/<int:pid>` | `admin_review` | Approve / reject one listing |
| GET,POST | `/admin/orders` | `admin_orders` | Order list and status changes |
| GET,POST | `/admin/messages` | `admin_messages` | Contact enquiries |
| GET,POST | `/admin/applications` | `admin_applications` | Job applications and status changes |
| GET | `/admin/applications/<int:aid>/doc` | `application_doc` | Download a private applicant document |
| GET,POST | `/admin/users` | `admin_users` | **Customer accounts, status and access rights** |
| GET,POST | `/admin/account` | `admin_account` | Admin accounts: add, remove, change password/email |
| GET | `/admin/export` | `admin_export` | Download all content as JSON |
| GET,POST | `/admin/import` | `admin_import` | Import content JSON (protected keys skipped) |
| GET,POST | `/admin/payments` | `admin_payments` | Admin-side payment ledger and ad-fee recording |
| GET,POST | `/admin/settings/payments` | `admin_payment_toggle` | Master switch for the payment system |

Details of each page's POST actions are in
[05-admin-cms.md](05-admin-cms.md).

## 6. Quick reference by URL

```
Public
  /                          home
  /shop                      catalogue
  /product/<id>              product detail
  /cart                      cart
  /checkout                  checkout
  /order/<id>                order confirmation
  /order/pay/<id>            pay for an order
  /user/payment              saved payment methods
  /contact                   contact form
  /apply/<id>                job application
  /login  /register  /logout /account  /myproducts

Static & infra
  /uploads/<path>            public uploaded files
  /healthz                   liveness probe
  /static/<path>             css, js, images, language packs

Admin
  /admin                     dashboard
  /admin/content             site content CMS
  /admin/products            catalogue
  /admin/listings            marketplace review queue
  /admin/listings/review/<id>  approve/reject a listing
  /admin/orders              orders
  /admin/messages            contact messages
  /admin/applications        job applications
  /admin/applications/<id>/doc  private document download
  /admin/users               customers, status, access rights
  /admin/account             admin accounts
  /admin/payments            payment ledger
  /admin/settings/payments   payment on/off
  /admin/export              content export (JSON)
  /admin/import              content import (JSON)
```

## 7. Adding a route

1. Put the route in the correct section of `app.py` (public or admin).
2. Add the guards the view needs — `admin_required` for anything under
   `/admin`.
3. If it is a restricted customer action, decide whether it needs a
   permission flag. If yes, add the flag to `ACCESS_PERMS` and guard the
   route with `perm_required("flag")`, then document it in
   [04-access-rights.md](04-access-rights.md).
4. Every POST form must carry `<input type="hidden" name="csrf_token" value="{{ csrf }}">`.
5. Add the route to the table in this document.

## 8. See also

- [01 — Architecture](01-architecture.md)
- [04 — Access Rights](04-access-rights.md)
- [05 — Admin CMS](05-admin-cms.md)
