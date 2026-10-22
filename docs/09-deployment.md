# 09 — Deployment

## 1. Requirements

| | |
|---|---|
| Python | 3.9+ (3.11+ recommended) |
| Packages | `Flask==3.1.0`, `gunicorn==23.0.0`, `Werkzeug==3.1.3` |
| Database | SQLite (file-based, no server needed) |
| Disk | Persistent storage for `data/` |

Install the dependencies:

```bash
pip3 install -r requirements.txt
```

## 2. Running locally

```bash
python3 app.py
```

The app listens on `PORT` (default **8080**) and binds to `127.0.0.1`.

```bash
curl -s localhost:8080/healthz
```

### 2.1 Why port 8080 and not 5000

macOS reserves port **5000** for the AirPlay Receiver. Binding to it fails
with `Address already in use` on a Mac. The app therefore defaults to
`8080`. On Linux servers, `PORT=5000 python3 app.py` works normally.

The dev server binds to `0.0.0.0` (not just localhost) and runs with
`debug=True`:

```python
if __name__ == "__main__":
    init_db()
    # macOS AirPlay Receiver owns port 5000, so default to 8080 locally.
    # Render/production always provides PORT (and runs via gunicorn, not this block).
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
```

`init_db()` is called here, so the schema is created and seeded when you
run `python3 app.py` directly. **Under gunicorn this block never runs** —
the schema must already exist from a previous run.

### 2.2 Using a virtualenv

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

`venv/` is git-ignored.

### 2.3 First boot

On the first run the app:

1. Creates `data/`, `data/uploads/` and `data/app_docs/`.
2. Creates the SQLite schema.
3. Seeds the `site_data` table from `site_data.json` **if the table is
   empty**.
4. Creates the default admin account.

After that, `data/site.db` is the source of truth. **Editing
`site_data.json` has no effect** — delete `data/site.db` and restart to
re-seed.

### 2.4 Default admin

```
username: admin
password: admin123
```

Change it at **Admin -> Account** immediately. See
[08-uploads-security.md](08-uploads-security.md) for the details.

## 3. Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | `dev-free-online-shopping-change-me` | Flask session signing key. **Set a strong value in production.** |
| `DATA_DIR` | `<app>/data` | Where `site.db`, `uploads/` and `app_docs/` live |
| `ADMIN_USERNAME` | `admin` | First-boot admin username |
| `ADMIN_PASSWORD` | `admin123` | First-boot admin password |
| `RESEND_API_KEY` | *(unset)* | Enables real email over the Resend HTTPS API |
| `FROM_EMAIL` | `onboarding@resend.dev` | The sender address for outgoing email |
| `PORT` | `8080` | The port the dev server binds to |

### 3.1 Notes

- `SECRET_KEY` and `ADMIN_USERNAME`/`ADMIN_PASSWORD` only take effect on
  **first boot** (when the `admin_users` blob is empty). Changing them
  later does not affect an existing database.
- `RESEND_API_KEY` is checked on every send. Without it, emails are logged
  rather than sent, and the app still reports success.
- `DATA_DIR` must point at **persistent** storage on a PaaS host, or the
  database will be lost on every redeploy.

## 4. Production server

Use gunicorn, never the Flask development server:

```bash
gunicorn app:app --bind 0.0.0.0:$PORT
```

With workers:

```bash
gunicorn app:app --bind 0.0.0.0:$PORT --workers 2
```

> **SQLite and multiple workers.** Each worker is a separate process with
> its own connection pool. Writes are serialised by SQLite's own locking,
> which is fine at this scale, but read-modify-write cycles on the JSON
> blobs (`get_blob` -> modify -> `set_blob`) are **not** atomic across
> workers. A busy multi-worker deployment can lose a concurrent write. With
> one worker this is not an issue. If you scale out, either use a single
> worker with more threads, or move the content store to a real database.

## 5. Render

`render.yaml` is included and defines a web service with a persistent disk:

```yaml
services:
  - type: web
    name: free-online-shopping
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn app:app --bind 0.0.0.0:$PORT
    envVars:
      - key: DATA_DIR
        value: /opt/render/project/src/data
      - key: SECRET_KEY
        generateValue: true
    disk:
      name: data
      mountPath: /opt/render/project/src/data
      sizeGB: 1
```

`SECRET_KEY` is generated automatically by Render, so it is stable across
deploys. `DATA_DIR` points at the mounted disk, so `site.db` and the uploads
survive a redeploy.

The `Procfile` provides the same start command for other PaaS providers:

```
web: gunicorn app:app --bind 0.0.0.0:$PORT
```

### 5.1 Render checklist

1. Set `ADMIN_USERNAME` and `ADMIN_PASSWORD` as env vars **before** the
   first deploy, or the defaults will be used.
2. Set `RESEND_API_KEY` and `FROM_EMAIL` if order emails are required.
3. Confirm the disk is attached and `DATA_DIR` matches the mount path.
4. Verify `https://<your-app>/healthz` returns 200 after the deploy.
5. Log in and change the admin password from **Admin -> Account**.

### 5.2 Known Render issue

On a fresh Render deploy the database may be created but **not seeded**,
because `init_db()` only seeds when the `site_data` table is empty *and*
`site_data.json` is present in the build. If the deployed site shows no
products or no admin account, check that `site_data.json` was included in
the deployment and that the disk directory is writable.

The same applies to the default admin: `ensure_default_admin()` is called
from `init_db()` on every boot and creates the admin if the `admin_users`
blob is empty, so a missing admin is a symptom of an unwritable or missing
`DATA_DIR` rather than a code fault.

## 6. Backup and restore

Everything lives under `DATA_DIR`. To back up:

```bash
tar czf backup-$(date +%F).tar.gz data/
```

To restore, stop the app, replace `data/` and start it again.

### 6.1 Content export

**Admin -> Export** downloads every `site_data` blob as JSON. This is a
content backup only — it deliberately **excludes** the protected keys
(`admin_users`, `users`, `admin_account`) when re-imported, so accounts and
credentials cannot be overwritten by a content file.

The full-fidelity backup is a copy of `data/site.db`.

## 7. Monitoring

`GET /healthz` returns a JSON body with the current server time:

```json
{ "ok": true, "time": "2026-10-20T14:31:02.884" }
```

It is the endpoint to use for uptime checks. It does **not** touch the
database, so it will report healthy even if `DATA_DIR` is unwritable — use
an admin page for that check.

## 8. Upgrading

1. Back up `data/`.
2. Pull the change.
3. Restart the app.

Schema changes are applied automatically by `init_db()` on boot, via
idempotent `ALTER TABLE` statements. There is no separate migration step.

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Address already in use` on port 5000 | macOS AirPlay Receiver | Use port 8080, or `PORT=5000` on Linux |
| Empty site after deploy | `site_data` not seeded | Check that `site_data.json` shipped and `DATA_DIR` is writable |
| No admin account | `DATA_DIR` unwritable | Verify the disk mount and permissions |
| Emails never arrive | `RESEND_API_KEY` not set | Set it, or accept log-only emails |
| Sessions reset on every deploy | `SECRET_KEY` changes | Set a fixed `SECRET_KEY` |
| `500` on admin pages | Stale schema | Restart so `init_db()` applies migrations |
| Uploads 404 after redeploy | `data/` not persistent | Point `DATA_DIR` at the persistent disk |

## 10. See also

- [08 — Uploads & Security](08-uploads-security.md)
- [10 — Testing](10-testing.md)
