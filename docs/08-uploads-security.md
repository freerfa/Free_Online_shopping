# 08 — Uploads & Security

This document covers the security-relevant behaviour of the app: file
uploads, CSRF, password hashing, output escaping, email and access control.

---

## 1. File uploads

There are two upload paths with different rules and different storage
locations.

### 1.1 Public images — `save_upload()`

Used for product images and payment receipts. Stored in `data/uploads/` and
served publicly via `/uploads/<path>`.

**Allowed extensions:** `png`, `jpg`, `jpeg`, `webp`, `gif`

**Magic byte checks:**

| Extension | Required signature |
|---|---|
| `png` | `\x89PNG\r\n\x1a\n` |
| `jpg` / `jpeg` | `\xff\xd8\xff` |
| `gif` | `GIF87a` or `GIF89a` |
| `webp` | `RIFF` at bytes 0-3 **and** `WEBP` at bytes 8-11 |

**Validation flow:**

```python
def save_upload(file_storage):
    fname = secure_filename(file_storage.filename or "")
    if not fname or not allowed_ext(fname):
        return None, "File type not allowed (png/jpg/jpeg/webp/gif only)."
    ext = fname.rsplit(".", 1)[1].lower()
    head = file_storage.stream.read(16)
    file_storage.stream.seek(0)
    if not valid_magic(head, ext):
        return None, "File content does not match its extension."
    unique = secrets.token_hex(8) + "_" + fname
    dest = os.path.join(UPLOAD_DIR, unique)
    file_storage.save(dest)
    return unique, None
```

Four defences in order:

1. `secure_filename()` strips path components and unsafe characters.
2. The **extension** is checked against an allowlist.
3. The **content** is checked against the expected magic bytes — this is what
   stops a `.png` that is actually a script.
4. The stored name is **randomised** with an 8-byte hex prefix, so uploads
   cannot overwrite each other and the original name is not used as a path.

The stream is rewound with `seek(0)` after the header read, so the full file
is then saved.

### 1.2 Private documents — `save_doc_upload()`

Used for job application CVs. Stored in `data/app_docs/`, which is **not**
served by any static route. The only way to retrieve one is
`GET /admin/applications/<aid>/doc`, which is admin-gated.

**Allowed extensions:** `pdf`, `doc`, `docx`, `txt`, `rtf`, `png`, `jpg`,
`jpeg`, `webp`, `gif`

**Validation:**

| Extension | Check |
|---|---|
| `pdf` | Starts with `%PDF` |
| `doc` | Starts with `\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1` |
| `docx` | Starts with `PK\x03\x04` (a ZIP container) |
| `rtf` | Starts with `{\rtf` |
| images | The same magic byte rules as `save_upload()` |
| `txt` | The first 512 bytes must not contain a null byte — this rejects binary junk |

### 1.3 Size limit

```python
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB
```

Applies to the whole request body, so a multi-file upload is capped at 5MB
in total.

### 1.4 Adding a new upload type

1. Add the extension to `ALLOWED_EXTS` (public) or `DOC_EXTS` (private).
2. Add the magic bytes to `MAGIC` or `DOC_MAGIC`, **or** handle the
   extension in the `else` branch of `save_doc_upload()`.
3. Update this document.

> Never add an extension to the allowlist without a magic-byte check. The
> extension allowlist alone is not a defence.

## 2. CSRF protection

Every `POST` request is checked by the `csrf_guard()` `before_request` hook:

```python
@app.before_request
def csrf_guard():
    if request.method == "POST":
        tok = request.form.get("csrf_token", "")
        if not valid_csrf(tok):
            flash("Security token expired. Please try again.", "danger")
            return redirect(request.path or url_for("index"))
```

The comparison is constant-time:

```python
def valid_csrf(tok):
    return tok and session.get("_csrf") and secrets.compare_digest(str(tok), str(session.get("_csrf")))
```

The token lives in `session["_csrf"]` and is created on demand by
`csrf_token()`, which is called from the context processor — so it is
available in every template as `{{ csrf }}`.

### 2.1 Adding a form

Every POST form **must** include the token:

```html
<input type="hidden" name="csrf_token" value="{{ csrf }}">
```

Missing it means the POST is rejected with a redirect, which is easy to
misread as a routing bug.

## 3. Passwords

Passwords are hashed with Werkzeug and never stored in plaintext:

```python
def hash_pw(pw: str) -> str:
    try:
        return generate_password_hash(pw, method="scrypt")
    except Exception:
        return generate_password_hash(pw, method="pbkdf2:sha256:600000")
```

`scrypt` is preferred, but some system Pythons (notably the Xcode build on
macOS) do not provide it, so the function **falls back to PBKDF2** rather
than failing. Both are salted and slow by design.

Verification uses `check_password_hash()`.

### 3.1 Changing the admin password

**Admin -> Account -> Change password.** The default `admin` / `admin123`
credentials are only created on first boot, when the `admin_users` blob is
empty:

```python
default_pw = os.environ.get("ADMIN_PASSWORD", "admin123")
```

Override the first-boot credentials with the `ADMIN_USERNAME` and
`ADMIN_PASSWORD` environment variables. See
[09-deployment.md](09-deployment.md).

> Change the default admin password on any publicly deployed instance.

## 4. Output escaping

User-supplied text that is stored is escaped with `html.escape()` **before**
it is written to the database:

```python
users.append({"username": username, "email": html.escape(email), ...})
```

The same applies to order names, addresses, notes, phone numbers and
applicant details. This means the stored value is already safe to render,
and Jinja's autoescaping adds a second layer on output.

Input lengths are also bounded — usernames to 50 characters, emails to 150,
product names to 120, descriptions to 2000, and so on.

## 5. Email

`send_email_https()` sends through the Resend HTTPS API rather than SMTP,
because SMTP is commonly blocked on PaaS hosts.

```python
def send_email_https(to_email, subject, body):
    api_key = os.environ.get("RESEND_API_KEY", "")
    from_email = os.environ.get("FROM_EMAIL", "onboarding@resend.dev")
    if not api_key:
        app.logger.info(f"[email-mock] to={to_email} subject={subject} body={body[:200]}")
        return True, "logged (no RESEND_API_KEY set)"
    ...
```

With no `RESEND_API_KEY`, the message is **logged, not sent**, and the
function still reports success. This keeps local development working
without a mail account. In production, set the key or order confirmation
emails will silently never arrive.

## 6. Access control

### 6.1 Route guards

| Guard | Applies to | Behaviour when it fails |
|---|---|---|
| `login_required` | Customer pages | Flash *"Please log in first."* and redirect to the login page with `next` |
| `admin_required` | All `/admin/*` routes | Flash *"Admin login required."* and redirect to the login page |
| `perm_required("x")` | Restricted customer actions | Flash and redirect to `/` |

All three use `@wraps(f)`, so the wrapped function keeps its name and
docstring — which matters because `url_for()` resolves view names.

### 6.2 The `next` parameter

Both guards redirect to `url_for("login", next=request.path)`. After a
successful login the app redirects to `next` — but **only if it starts with
`/`**:

```python
return redirect(nxt if nxt.startswith("/") else url_for("index"))
```

This blocks open-redirect attacks via `?next=https://evil.example.com`.

### 6.3 Admin accounts

- The **last admin cannot be deleted** — the guard is `if len(admins) > 1`.
- Admins are **never restricted** by the customer access-rights system.
- `admin_users` is a **protected key** — a content import cannot overwrite
  it.

### 6.4 Session contents

The session stores only `{"username": ..., "is_admin": bool}`. All
permission decisions re-read the user record from the database, so an
admin's change takes effect on the user's next request with no cache to
invalidate.

### 6.5 Secret key

```python
app.secret_key = os.environ.get("SECRET_KEY", "dev-free-online-shopping-change-me")
```

The fallback is a **development default**. On any real deployment, set
`SECRET_KEY` to a strong random value — otherwise sessions can be forged.
`render.yaml` generates one automatically.

## 7. Summary checklist

| Control | Where |
|---|---|
| File extension allowlist | `ALLOWED_EXTS`, `DOC_EXTS` |
| Magic byte content validation | `valid_magic()`, `save_doc_upload()` |
| Randomised stored filenames | `secrets.token_hex(8)` prefix |
| Private storage for documents | `data/app_docs/`, not served statically |
| Upload size cap | `MAX_CONTENT_LENGTH` = 5MB |
| CSRF on every POST | `csrf_guard()` |
| Constant-time token comparison | `secrets.compare_digest()` |
| Password hashing | `hash_pw()` with scrypt/PBKDF2 fallback |
| Output escaping | `html.escape()` on stored input |
| Route guards | `login_required`, `admin_required`, `perm_required` |
| Open-redirect prevention | `nxt.startswith("/")` |
| Last-admin protection | `len(admins) > 1` |
| Protected import keys | `PROTECTED_KEYS` |
| Session signing key | `SECRET_KEY` env var |

## 8. See also

- [01 — Architecture](01-architecture.md) — the request hook order
- [04 — Access Rights](04-access-rights.md) — the `perm_required` guard
- [09 — Deployment](09-deployment.md) — environment variables
