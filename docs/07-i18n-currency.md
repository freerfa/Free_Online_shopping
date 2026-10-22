# 07 — Internationalisation & Currency

The site supports 6 languages and 17 currencies. Both are switched by a
query parameter that is persisted in a cookie.

---

## 1. Languages

### 1.1 Language packs

One JSON file per language in `static/lang/`:

| File | Code | Name | Direction |
|---|---|---|---|
| `en.json` | `en` | English | `ltr` |
| `ar.json` | `ar` | Arabic | `rtl` |
| `fr.json` | `fr` | French | `ltr` |
| `sw.json` | `sw` | Swahili | `ltr` |
| `jac.json` | `jac` | Juba Arabic | `ltr` |
| `am.json` | `am` | Amharic | `ltr` |

Each file has this shape:

```json
{
  "code": "en",
  "name": "English",
  "dir": "ltr",
  "strings": {
    "nav.home": "Home",
    "nav.shop": "Shop",
    "nav.cart": "Cart ({count})"
  }
}
```

The English pack holds **176 keys** and is the fallback for every other
language.

### 1.2 Loading

`load_languages()` reads every `.json` file in `static/lang/` at import
time and keys the result by each file's `code`. A missing folder is
tolerated, and English is always present as a fallback:

```python
LANGUAGES = load_languages()
```

**Adding a language is just dropping a file into `static/lang/`** — no code
change is needed. The picker in `base.html` renders from the `languages`
context variable.

### 1.3 The `t` filter

```python
@app.template_filter("t")
@pass_context
def translate(ctx, key, **kwargs):
    lang_code = request.cookies.get("language") or DEFAULT_LANGUAGE
    lang = LANGUAGES.get(lang_code) or LANGUAGES.get(DEFAULT_LANGUAGE)
    strings = lang.get("strings", {}) if lang else {}
    text = strings.get(key)
    if text is None:
        en = LANGUAGES.get(DEFAULT_LANGUAGE, {})
        text = en.get("strings", {}).get(key)
    if text is None:
        text = key
    try:
        return text.format(**kwargs)
    except (KeyError, ValueError):
        return text
```

Usage in a template:

```html
{{ 'nav.cart'|t(count=cart_count) }}
{{ 'account.title'|t(user=user.username) }}
```

**Fallback order:** current language -> English -> the key itself. A missing
translation therefore shows the key (e.g. `nav.cart`) rather than breaking
the page.

**Placeholders** use `str.format` syntax. A placeholder that is missing from
the string raises `KeyError`, which is caught and the raw text is returned —
so a mismatched placeholder degrades gracefully instead of erroring.

### 1.4 Why `@pass_context` matters

This is the single most important detail in this document.

Jinja's optimizer **constant-folds filters whose arguments are all
literals**. `{{ 'nav.cart'|t }}` has only a literal argument, so without
`@pass_context` Jinja would evaluate `t` **once at compile time** and bake
the language of whichever request happened to be first into the compiled
template. Every subsequent request would then be served in that language,
regardless of its own cookie.

Marking the filter as context-dependent (`@pass_context`) forces per-request
evaluation.

> **Never remove `@pass_context` from the `t` filter.** If you do, the
> language switcher will appear to work for the first visitor and then serve
> the wrong language to everyone else.

### 1.5 Switching language

`persist_language()` handles `?language=CODE`:

1. Reads the parameter, lower-cased.
2. Stores it in a 30-day cookie.
3. Redirects to the same path with the parameter stripped.

The `language` cookie is read by both `translate()` and `inject_globals()`.
`inject_globals()` also validates the cookie against the loaded languages
and falls back to `en` if it is unknown.

### 1.6 Text direction

`lang_dir` is injected into every template as `ltr` or `rtl`, taken from the
language pack's `dir` field. `base.html` applies it to the `<html>` element
so that Arabic and Juba Arabic render right-to-left.

## 2. Currency

### 2.1 The available currencies

Defined in `DEFAULT_CURRENCIES` in `app.py` (and overridable via the
`site.currencies` blob in the Content CMS):

| Code | Name | Symbol | Rate | Decimals |
|---|---|---|---|---|
| SSP | South Sudanese Pound | SSP | 1.0 | 0 |
| USD | US Dollar | US$ | 0.000741 | 2 |
| EGP | Egyptian Pound | £ | 0.0303 | 2 |
| KES | Kenyan Shilling | KSh | 0.0909 | 2 |
| XOF | West African CFA Franc | CFA | 0.444 | 0 |
| UGX | Ugandan Shilling | USh | 2.74 | 0 |
| ETB | Ethiopian Birr | Br | 0.10 | 2 |
| SDG | Sudanese Pound | SDG | 0.444 | 0 |
| TZS | Tanzanian Shilling | TSh | 1.85 | 0 |
| RWF | Rwandan Franc | RF | 0.963 | 0 |
| BIF | Burundian Franc | FBu | 2.19 | 0 |
| NGN | Nigerian Naira | ₦ | 1.11 | 2 |
| GBP | British Pound | £ | 0.000585 | 2 |
| EUR | Euro | € | 0.000681 | 2 |
| AED | UAE Dirham | AED | 0.00272 | 2 |
| CNY | Chinese Yuan | ¥ | 0.00537 | 2 |

The **rate** converts from the base currency (SSP). SSP is the base with a
rate of 1.0.

### 2.2 The `curfmt` filter

```python
@app.template_filter("curfmt")
def format_currency(value, code=None):
    ...
```

Usage:

```html
{{ p.price|curfmt(currency) }}        <!-- the active currency (from the cookie) -->
{{ p.price|curfmt('USD') }}           <!-- an explicit currency -->
{{ p.price|curfmt }}                  <!-- falls back to site.currency -->
```

It looks up the currency definition, applies the rate, and formats the
result with the right number of decimals. Currencies with 0 decimals (SSP,
XOF, UGX, SDG, TZS, RWF, BIF) render without a fractional part; everything
else uses 2.

**The symbol is not part of the filter's output.** The filter returns the
number only, and templates print the symbol separately from the injected
`currency_symbol` variable:

```html
<p class="price">{{ currency_symbol }} {{ p.price|curfmt(currency) }}</p>
```

This is the pattern used by `card.html` and `product.html`. Keep it — it
keeps the symbol and the number in separate control, so a currency can be
relabelled without touching the formatter.

The currency code passed in is upper-cased. An unknown code falls back to
the first entry in the list, and a non-numeric price returns an empty
string rather than raising.

### 2.3 Switching currency

`persist_currency()` handles `?currency=CODE`:

1. Reads the parameter, upper-cased.
2. Stores it in a 30-day cookie.
3. Redirects to the same path with the parameter stripped.

`inject_globals()` validates the cookie against the available currency
codes and falls back to `site.currency` (default `SSP`) if it is unknown.
`currency` and `currency_symbol` are then injected for templates.

### 2.4 The base currency

`site.currency` sets the base currency and the default when the visitor has
no cookie. Prices are **stored** in the base currency in the database;
conversion happens only at display time. Changing the base currency later
reinterprets existing prices — this is intended for a single-currency
store that later adds display currencies, not for repricing an existing
catalogue.

## 3. Adding a translation key

1. Add the key to **all six** files in `static/lang/`.
2. Use it in the template as `{{ 'your.key'|t }}`.
3. If it takes a placeholder, use `str.format` syntax and pass it as a
   keyword argument: `{{ 'your.key'|t(name=user.username) }}`.
4. Keep the English text as the fallback, so make it the complete sentence.

## 4. Adding a currency

1. Add an entry to `DEFAULT_CURRENCIES` in `app.py`:

   ```python
   {"code": "KES", "name": "Kenyan Shilling", "symbol": "KSh", "rate": 0.0909, "decimals": 2},
   ```

2. Or add it to the `currencies` list in the Content CMS (the JSON
   textarea) — this overrides the built-in list without a code change.
3. Restart the app if you changed `app.py`; the CMS change takes effect
   immediately.

## 5. Testing

| # | Scenario | Expected |
|---|---|---|
| 1 | Open the site in English | English text throughout |
| 2 | Switch to Arabic | Arabic text, and the page renders right-to-left |
| 3 | Switch language, then open a new tab | The new tab uses the same language (cookie) |
| 4 | Visit the site in two languages back to back | Each request is served in its own language — this is the `pass_context` regression test |
| 5 | Switch to USD | Prices show with the `US$` symbol and 2 decimals |
| 6 | Switch to SSP | Prices show with no decimals |
| 7 | Request `?currency=XXX` (unknown code) | Falls back to the base currency |
| 8 | Request `?language=zz` (unknown code) | Falls back to English |
| 9 | Use a translation key that does not exist | The key itself is displayed, no error |

## 6. See also

- [01 — Architecture](01-architecture.md) — the request hooks
- [08 — Uploads & Security](08-uploads-security.md)
