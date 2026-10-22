"""Render-check every admin template through Flask/Jinja.

Run with:  python3 scripts/check_admin_templates.py
It boots the real app, logs in as the seeded admin, and GETs every admin
route, asserting the response is 200 and the HTML is well-formed enough
(no unresolved Jinja blocks, no missing template errors).
"""
import os
import re
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

# Use an isolated data dir so the check never touches real site data.
tmp = tempfile.mkdtemp(prefix="admcheck-")
os.environ["DATA_DIR"] = tmp
os.environ.setdefault("SECRET_KEY", "admcheck-secret")

import app as appmod  # noqa: E402

ROUTES = [
    "/admin",
    "/admin/products",
    "/admin/listings",
    "/admin/orders",
    "/admin/payments",
    "/admin/applications",
    "/admin/users",
    "/admin/account",
    "/admin/content",
    "/admin/settings/payments",
    "/admin/messages",
    "/admin/import",
]

from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr"}


class TagBalance(HTMLParser):
    """Minimal well-formedness check: every non-void tag must be closed in order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append((tag, self.getpos()))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack:
            self.errors.append("stray </%s> at line %d" % (tag, self.getpos()[0]))
            return
        if self.stack[-1][0] != tag:
            self.errors.append("</%s> closes <%s> opened at line %d"
                               % (tag, self.stack[-1][0], self.stack[-1][1][0]))
            # Try to recover: pop until we find the tag.
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]
                    return
            return
        self.stack.pop()

    def finish(self):
        for tag, pos in self.stack:
            self.errors.append("unclosed <%s> opened at line %d" % (tag, pos[0]))
        return self.errors


def check_wellformed(body):
    parser = TagBalance()
    parser.feed(body)
    parser.close()
    return parser.finish()


def csrf_of(client, path="/admin"):
    body = client.get(path).get_data(as_text=True)
    m = re.search(r'name="csrf_token" value="([^"]+)"', body)
    return m.group(1) if m else ""


def post(client, path, data, csrf, **kw):
    payload = dict(data)
    payload["csrf_token"] = csrf
    return client.post(path, data=payload, follow_redirects=True, **kw)


def resp_ok(row):
    return row is not None


BAD_PATTERNS = [
    (re.compile(r"\{%-?\s*(if|for|block|endif|endfor|endblock|set)\b"), "unresolved Jinja block"),
    (re.compile(r"\{\{\s*\{"), "unresolved Jinja expression"),
    (re.compile(r"PLACEHOLDER"), "placeholder text left in template"),
    (re.compile(r"\bundefined\b"), "undefined value rendered"),
    (re.compile(r"\bNone\b"), "None rendered into HTML"),
]


def check_workflows(client, appmod):
    """Exercise every admin POST action the redesigned templates expose."""
    fails = []

    def expect(name, cond, detail=""):
        if cond:
            print("OK   POST %-34s" % name)
        else:
            fails.append((name, detail or "assertion failed"))
            print("FAIL POST %-34s %s" % (name, detail or "assertion failed"))

    # ---- payments: record -> verify ----
    csrf = csrf_of(client, "/admin/payments")
    post(client, "/admin/payments", {
        "action": "record", "user_id": "seller1", "amount": "25.50",
        "method": "mtn_momo", "reference": "TXN-123",
    }, csrf)
    con = appmod.db()
    row = con.execute("SELECT * FROM admin_payments ORDER BY id DESC LIMIT 1").fetchone()
    con.close()
    expect("payments/record", resp_ok(row) and row["status"] == "pending"
           and row["amount"] == 25.5, "record did not create a pending row")
    if row is not None:
        csrf = csrf_of(client, "/admin/payments")
        post(client, "/admin/payments", {"action": "verify", "pid": str(row["id"])}, csrf)
        con = appmod.db()
        after = con.execute("SELECT status FROM admin_payments WHERE id=?", (row["id"],)).fetchone()
        con.close()
        expect("payments/verify", after is not None and after["status"] == "paid",
               "status=%r" % (after["status"] if after else None))

    # ---- users: grant / status / perms / reset / delete ----
    appmod.set_blob("users", [{
        "username": "wfuser", "email": "wf@example.com", "created": "2024-01-01",
        "can_sell": False, "sell_request": "pending", "status": "active",
        "perms": {"shop": True, "sell": True, "payment": True, "apply": True, "contact": True},
    }])
    csrf = csrf_of(client, "/admin/users")
    post(client, "/admin/users", {"action": "grant", "username": "wfuser"}, csrf)
    u = next(x for x in appmod.get_blob("users", []) if x["username"] == "wfuser")
    expect("users/grant", u.get("can_sell") is True, repr(u))

    csrf = csrf_of(client, "/admin/users")
    post(client, "/admin/users", {"action": "status", "username": "wfuser", "status": "suspended"}, csrf)
    u = next(x for x in appmod.get_blob("users", []) if x["username"] == "wfuser")
    expect("users/status", u.get("status") == "suspended", repr(u))

    csrf = csrf_of(client, "/admin/users")
    post(client, "/admin/users", {
        "action": "perms", "username": "wfuser",
        "shop": "1", "sell": "1", "contact": "1",  # payment + apply intentionally unticked
    }, csrf)
    u = next(x for x in appmod.get_blob("users", []) if x["username"] == "wfuser")
    expect("users/perms", u["perms"].get("shop") is True and u["perms"].get("payment") is False,
           repr(u.get("perms")))

    csrf = csrf_of(client, "/admin/users")
    post(client, "/admin/users", {"action": "reset_perms", "username": "wfuser"}, csrf)
    u = next(x for x in appmod.get_blob("users", []) if x["username"] == "wfuser")
    expect("users/reset_perms", all(u["perms"].get(k) for k in u["perms"]), repr(u.get("perms")))

    csrf = csrf_of(client, "/admin/users")
    post(client, "/admin/users", {"action": "delete", "username": "wfuser"}, csrf)
    expect("users/delete", not any(x["username"] == "wfuser" for x in appmod.get_blob("users", [])),
           "user still present")

    # ---- account: add / email / password / delete ----
    csrf = csrf_of(client, "/admin/account")
    post(client, "/admin/account", {
        "action": "add", "username": "wfadmin", "email": "wfadmin@example.com", "password": "abcd",
    }, csrf)
    expect("account/add", any(a["username"] == "wfadmin" for a in appmod.get_blob("admin_users", [])),
           "admin not added")

    csrf = csrf_of(client, "/admin/account")
    post(client, "/admin/account", {"action": "email", "email": "checker@example.com"}, csrf)
    me = next((a for a in appmod.get_blob("admin_users", []) if a["username"] == "checker"), {})
    expect("account/email", me.get("email") == "checker@example.com", repr(me))

    csrf = csrf_of(client, "/admin/account")
    post(client, "/admin/account", {"action": "password", "password": "newpass123"}, csrf)
    rec = next(a for a in appmod.get_blob("admin_users", []) if a["username"] == "checker")
    from werkzeug.security import check_password_hash
    expect("account/password", check_password_hash(rec["pw_hash"], "newpass123"),
           "password not updated")

    csrf = csrf_of(client, "/admin/account")
    post(client, "/admin/account", {"action": "delete", "username": "wfadmin"}, csrf)
    expect("account/delete", not any(a["username"] == "wfadmin" for a in appmod.get_blob("admin_users", [])),
           "admin still present")

    # ---- content: save fields + currencies ----
    csrf = csrf_of(client, "/admin/content")
    post(client, "/admin/content", {
        "name": "WF Store", "tagline": "Best deals", "currency": "SSP",
        "announcement": "Free delivery", "hero_title": "Shop now", "hero_cta": "Browse",
        "hero_subtitle": "Quality goods", "about": "About us", "mission": "Mission",
        "contact_email": "hi@example.com", "contact_phone": "0999", "address": "Juba",
        "footer_text": "WF", "currencies": '[{"code": "SSP", "symbol": "SSP", "rate": 1.0}]',
    }, csrf)
    site = appmod.get_blob("site", {})
    expect("content/save", site.get("name") == "WF Store" and site.get("hero_title") == "Shop now"
           and site.get("currency") == "SSP", repr(site.get("name")))
    expect("content/currencies", bool(site.get("currencies")) and site["currencies"][0]["code"] == "SSP",
           repr(site.get("currencies")))

    # ---- payment toggle ----
    csrf = csrf_of(client, "/admin/settings/payments")
    post(client, "/admin/settings/payments", {"enabled": "on"}, csrf)
    expect("payment_toggle/on", appmod.get_blob("site", {}).get("payment_enabled") is True,
           repr(appmod.get_blob("site", {}).get("payment_enabled")))
    csrf = csrf_of(client, "/admin/settings/payments")
    post(client, "/admin/settings/payments", {}, csrf)
    expect("payment_toggle/off", appmod.get_blob("site", {}).get("payment_enabled") is False,
           repr(appmod.get_blob("site", {}).get("payment_enabled")))
    csrf = csrf_of(client, "/admin/settings/payments")
    post(client, "/admin/settings/payments", {"enabled": "on"}, csrf)

    # ---- review: notes / approve / fee_paid ----
    products = appmod.get_blob("products", [])
    target = next((p for p in products if p.get("post_type") == "user"), None)
    if target is not None:
        rev = "/admin/listings/review/%d" % target["id"]

        def reread():
            return next(x for x in appmod.get_blob("products", []) if x["id"] == target["id"])

        csrf = csrf_of(client, rev)
        post(client, rev, {"action": "notes", "notes": "Please add photos."}, csrf)
        expect("review/notes", reread().get("review_notes") == "Please add photos.",
               repr(reread().get("review_notes")))

        csrf = csrf_of(client, rev)
        post(client, rev, {"action": "approve", "notes": "Looks good."}, csrf)
        expect("review/approve", reread().get("status") == "approved", repr(reread().get("status")))

        csrf = csrf_of(client, rev)
        post(client, rev, {"action": "fee_paid"}, csrf)
        expect("review/fee_paid", reread().get("fee_status") == "paid", repr(reread().get("fee_status")))

        csrf = csrf_of(client, rev)
        post(client, rev, {"action": "fee_unpaid"}, csrf)
        expect("review/fee_unpaid", reread().get("fee_status") == "unpaid", repr(reread().get("fee_status")))

    # ---- import ----
    csrf = csrf_of(client, "/admin/import")
    post(client, "/admin/import", {
        "json_data": '{"site": {"tagline": "Imported"}, "categories": [{"name": "Imported"}]}',
    }, csrf)
    expect("import/json", appmod.get_blob("site", {}).get("tagline") == "Imported",
           repr(appmod.get_blob("site", {}).get("tagline")))
    expect("import/protected", any(a["username"] == "checker" for a in appmod.get_blob("admin_users", [])),
           "protected key overwritten")

    return fails


def main():
    application = appmod.app
    application.config.update(TESTING=True)
    appmod.init_db()
    client = application.test_client()

    # Seed an admin so @admin_required passes.
    appmod.set_blob("admin_users", [{
        "username": "checker", "email": "checker@example.com",
        "pw_hash": appmod.hash_pw("checkerpass"), "created": "2024-01-01T00:00:00",
    }])

    with client.session_transaction() as sess:
        sess["user"] = {"username": "checker", "is_admin": True}

    failures = []
    for path in ROUTES:
        try:
            resp = client.get(path, follow_redirects=True)
        except Exception as exc:  # noqa: BLE001
            failures.append((path, "exception: %r" % (exc,)))
            continue
        body = resp.get_data(as_text=True)
        if resp.status_code != 200:
            failures.append((path, "status %s" % resp.status_code))
            continue
        for pattern, label in BAD_PATTERNS:
            if pattern.search(body):
                failures.append((path, label))
        for err in check_wellformed(body):
            failures.append((path, "malformed HTML: %s" % err))
        print("OK   %-28s %6d bytes" % (path, len(body)))

    # The review page needs a real marketplace post.
    products = appmod.get_blob("products", [])
    target = next((p for p in products if p.get("post_type") == "user"), None)
    if target is None:
        target = {
            "id": 999, "name": "Checker Post", "desc": "A test listing",
            "price": 10, "stock": 2, "category": "Test", "post_type": "user",
            "seller": "seller1", "status": "pending", "fee_status": "unpaid",
            "fee_amount": 5, "created": "2024-01-01T00:00:00", "images": [],
        }
        products.append(target)
        appmod.set_blob("products", products)
    try:
        resp = client.get("/admin/listings/review/%d" % target["id"], follow_redirects=True)
        body = resp.get_data(as_text=True)
        if resp.status_code != 200:
            failures.append(("/admin/listings/review/<id>", "status %s" % resp.status_code))
        else:
            for pattern, label in BAD_PATTERNS:
                if pattern.search(body):
                    failures.append(("/admin/listings/review/<id>", label))
            for err in check_wellformed(body):
                failures.append(("/admin/listings/review/<id>", "malformed HTML: %s" % err))
            print("OK   %-28s %6d bytes" % ("/admin/listings/review/<id>", len(body)))
    except Exception as exc:  # noqa: BLE001
        failures.append(("/admin/listings/review/<id>", "exception: %r" % (exc,)))

    failures.extend(check_workflows(client, appmod))

    print()
    if failures:
        print("FAILURES:")
        for path, why in failures:
            print("  - %s: %s" % (path, why))
        return 1
    print("All admin templates rendered cleanly and all workflows passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
