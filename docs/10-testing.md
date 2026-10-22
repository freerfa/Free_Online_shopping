# 10 — Testing

There is no automated test suite in this repository. Verification is done
with a manual checklist and a throwaway HTTP script.

---

## 1. The pre-flight check

Run this before and after any change:

```bash
# 1. The module parses
python3 -c "import ast; ast.parse(open('app.py').read())"

# 2. The app imports and the routes register
python3 -c "import app; print(len(app.app.url_map._rules), 'routes')"

# 3. It boots and answers
python3 app.py &
sleep 2
curl -s localhost:8080/healthz
```

Expected from step 2: **36 routes**. Expected from step 3:

```json
{ "ok": true, "time": "..." }
```

## 2. The public site

| # | Check | Expected |
|---|---|---|
| 1 | `GET /` | 200, hero and featured products render |
| 2 | `GET /shop` | 200, product grid renders |
| 3 | `GET /product/<id>` | 200 for a real id; 404 for a missing one |
| 4 | `GET /cart` | 200, empty-cart message |
| 5 | `GET /checkout` | Redirects to `/shop` when the cart is empty |
| 6 | `GET /contact` | 200, form renders |
| 7 | `GET /login` | 200, sign-in and sign-up tabs |
| 8 | `GET /register` | Redirects to `/login?tab=signup` |
| 9 | `GET /healthz` | 200 with the JSON body |
| 10 | `GET /uploads/<file>` | 200 for an uploaded file |

## 3. The purchase flow

| # | Step | Expected |
|---|---|---|
| 1 | Register a new customer | Redirected to `/` with a welcome flash |
| 2 | Add a product to the cart | Redirect back with *"Added to cart"* |
| 3 | Open `/cart` | The item and the total are shown |
| 4 | Update the quantity | The new quantity is reflected |
| 5 | Check out with name, phone and address | An order is created and shown |
| 6 | Check the product's stock | It decreased by the ordered quantity |
| 7 | Open `/account` | The order appears in the order history |
| 8 | Check out with an invalid email | Rejected with *"Invalid email address."* |
| 9 | Check out with a missing address | Rejected with the required-fields message |

## 4. The admin CMS

| # | Step | Expected |
|---|---|---|
| 1 | Log in as `admin` / `admin123` | Redirected to the site with a welcome flash |
| 2 | Open every `/admin/*` page | All return 200 |
| 3 | Open `/admin` while signed out | Redirects to the login page |
| 4 | Edit the site content and save | The change appears on the public site |
| 5 | Import a content JSON containing `users` | The accounts are **not** overwritten |
| 6 | Export the content | A JSON download is produced |
| 7 | Upload a fake `.png` (wrong magic bytes) | Rejected with *"File content does not match its extension."* |
| 8 | Add a marketplace listing as a customer | It appears in `/admin/listings` as pending |
| 9 | Approve it | It becomes visible in `/shop` |
| 10 | Submit the contact form | The message appears in `/admin/messages` |
| 11 | Submit a job application | It appears in `/admin/applications` |
| 12 | Try to delete the last admin | Refused with *"Cannot delete last admin."* |

## 5. Access rights

The full checklist is in
[04-access-rights.md](04-access-rights.md#10-testing-this-feature). In
summary:

| # | Step | Expected |
|---|---|---|
| 1 | Register a customer | `active`, all flags `True` |
| 2 | Set the account to `suspended` | The customer can browse but not transact |
| 3 | Set the account to `blocked` | The customer is signed out on the next request |
| 4 | Try to log in as the blocked customer | Refused |
| 5 | Untick one permission | Only that feature is denied |
| 6 | Click **Reset to default** | All flags are `True` again |
| 7 | Check the admin Users page as an admin | The status dropdown and rights panel render |

## 6. A scripted check

For a repeatable check, write a small script that drives the app over HTTP
with a cookie jar. A workable shape:

```python
import re
import requests

BASE = "http://127.0.0.1:8080"
s = requests.Session()


def csrf(html):
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else ""


def get(path, **kw):
    return s.get(BASE + path, **kw)


def post(path, data, **kw):
    page = get(kw.pop("page", path))
    data = dict(data, csrf_token=csrf(page.text))
    return s.post(BASE + path, data=data, **kw)
```

### 6.1 Rules that a script must follow

These are the mistakes that produce false failures:

- **Register at `/register`, not `/login`.** `GET /register` redirects to
  `/login?tab=signup`, but the POST that creates the account goes to
  `/register`.
- **Re-read the CSRF token after every redirect.** The token is tied to the
  session, and a login or a redirect can change the session.
- **Use the same password you registered with.** A test that registers with
  one password and logs in with another always fails.
- **Parse checkboxes with `k in form`, not `form.get(k)`.** An unticked
  checkbox is absent from the payload.
- **Select the row by username.** With several users, indexing by row
  position picks the wrong account.

### 6.2 Example: register a customer and read their record

```python
user = "tester1"
pw = "test1234"

post("/register", {"username": user, "password": pw, "email": "t@example.com"})
post("/login", {"username": user, "password": pw})

page = get("/admin/users")          # as an admin
row = re.search(rf"<b>{user}</b>.*?</tr>", page.text, re.S)
print(row.group(0) if row else "not found")
```

## 7. Deployment checks

| # | Check | Expected |
|---|---|---|
| 1 | `gunicorn app:app --bind 0.0.0.0:$PORT` | Boots with 2 workers |
| 2 | `curl -s localhost:$PORT/healthz` | 200 with the JSON body |
| 3 | Deploy with a persistent disk | `site.db` survives a redeploy |
| 4 | Redeploy and log in | The admin account still exists |
| 5 | Restart with `DATA_DIR` set elsewhere | The new directory is used |

## 8. What is not covered

Being explicit about the gaps:

- No unit or integration test suite exists.
- No automated browser testing.
- No load or concurrency testing. The multi-worker caveat in
  [09-deployment.md](09-deployment.md) is untested.
- Email delivery is only verified by inspecting the log when
  `RESEND_API_KEY` is unset.

If the project grows, the highest-value additions would be a pytest suite
over the Flask test client covering the access-rights matrix, and a CI job
that runs the pre-flight check on every push.

## 9. See also

- [04 — Access Rights](04-access-rights.md) — the access-rights checklist
- [09 — Deployment](09-deployment.md) — the deployment checklist

