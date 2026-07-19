# Here are your Instructions

## Local Stripe webhook testing

The backend has a real webhook handler at `POST /api/webhook/stripe` (see
`backend/server.py`) that Stripe calls directly, not through the frontend -
so exercising it locally requires forwarding Stripe's events to your machine
with the Stripe CLI, rather than just clicking through the UI.

**1. Get the Stripe CLI.** A portable Windows binary is already vendored at
`backend/tools/stripe-cli/stripe.exe` (not committed to git - see below).
If it's missing, download it yourself:

```
curl -sL -o stripe.zip https://github.com/stripe/stripe-cli/releases/latest/download/stripe_<version>_windows_x86_64.zip
unzip stripe.zip   # produces stripe.exe
```

(`choco install stripe-cli` also works if you have an elevated/admin shell -
it fails silently otherwise with a `lib-bad` permissions error.)

**2. Authenticate.** The app's own `STRIPE_API_KEY` in `.env` is a
*restricted* key scoped to what the app itself needs, and does not have the
`stripecli_session_write` ("Debugging Tools Write") permission that
`stripe listen`/`stripe trigger` require. Rather than widen that key's
permissions, pair the CLI with your Stripe account directly:

```
backend/tools/stripe-cli/stripe.exe login
```

This opens a browser to confirm the pairing and stores a separate CLI
credential (`~/.config/stripe/config.toml`), untouched by and unrelated to
the app's own `.env` key.

**3. Forward events to your local backend:**

```
backend/tools/stripe-cli/stripe.exe listen --forward-to localhost:8001/api/webhook/stripe
```

This prints `Your webhook signing secret is whsec_...` on startup. Copy that
value into `STRIPE_WEBHOOK_SECRET` in `backend/.env` and **restart the
backend** - `.env` is only read once at process startup (`load_dotenv` in
`server.py`), so the running process won't pick up a changed secret on its
own.

**Important:** this signing secret is ephemeral - `stripe listen` mints a
new one every time it's (re)started, unless you switch to
`--use-configured-webhooks` against a webhook endpoint registered in the
Stripe Dashboard (which has a stable secret). For local dev, just re-copy
the secret and restart the backend each time you restart `stripe listen`.

**4. Fire test events** (in a second terminal, while `stripe listen` is
running):

```
backend/tools/stripe-cli/stripe.exe trigger checkout.session.completed
backend/tools/stripe-cli/stripe.exe trigger checkout.session.expired
```

Each should show up in the `stripe listen` terminal as `--> event.name` /
`<-- [200] POST .../webhook/stripe`, and in the backend's own logs as
`POST /api/webhook/stripe HTTP/1.1" 200 OK`. A non-200 here usually means
the `STRIPE_WEBHOOK_SECRET` the backend has loaded doesn't match the one
`stripe listen` most recently printed.
