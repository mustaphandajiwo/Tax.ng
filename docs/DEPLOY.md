# Deploying tax.ng

One container serves the API and the built frontend (`backend/taxng/api/app.py`
mounts `frontend/dist`). That keeps the strict same-origin CSP and cookie
sign-in intact without a proxy layer. Cloudflare sits in front for DNS, TLS and
caching. Cloudflare Pages is not used: Pages cannot run the Python backend.

## Hosting: Fly.io (Johannesburg)

Data is SQLite on a persistent volume, so run exactly one machine.

One-time setup (requires a Fly.io account with a card on file):

    fly auth login
    fly launch --no-deploy --copy-config        # accept the app name, or change `app` in fly.toml
    fly volumes create taxng_data --region jnb --size 1
    fly secrets set \
      TAXNG_SECRET="$(openssl rand -hex 32)" \
      TAXNG_ADMIN_EMAILS="you@example.com" \
      TAXNG_RESEND_API_KEY="re_..." \
      TAXNG_MAIL_FROM="tax.ng <no-reply@tax.ng>"
    fly deploy

## Private preview (no terminal needed)

`.github/workflows/preview.yml` deploys `fly.preview.toml` to
`https://taxng-preview.fly.dev` on every push to the `preview` branch, or from
Actions > preview > Run workflow. It creates the app and volume on first run and
seeds demo data. Demo mode is on there: sign-in codes show on screen, so never
use real taxpayer data. Needs one repository secret, `FLY_API_TOKEN`
(Fly dashboard > Tokens > create an organisation token).

## Email (sign-in codes)

Production mode (`TAXNG_DEMO=0`) hides the demo outbox, so sign-in needs real
email. `ProductionMessaging` sends through Resend's HTTPS API.

1. Create a Resend account, add `tax.ng` as a sending domain.
2. Add the DNS records Resend shows (SPF, DKIM, optional DMARC) in Cloudflare DNS.
3. Set `TAXNG_RESEND_API_KEY` and `TAXNG_MAIL_FROM` as Fly secrets (above).

Unconfigured, sign-in returns 503 `integration_not_configured`; a provider
outage returns 503 `integration_unavailable`. The public site keeps working
either way.

## Cloudflare DNS

1. `fly certs add tax.ng` and `fly certs add www.tax.ng`.
2. In Cloudflare DNS: `CNAME tax.ng -> <app>.fly.dev` and `CNAME www -> <app>.fly.dev`, proxied.
3. SSL/TLS mode **Full (strict)**. Flexible causes a redirect loop with
   `force_https`.
4. If a Cloudflare Pages project was created for this repo, delete it: it
   publishes a frontend whose `/api` calls all 404.

## Environment reference

| Variable | Production value | Purpose |
|---|---|---|
| `TAXNG_DEMO` | `0` | Hides outbox and seed command; secure cookies |
| `TAXNG_SECRET` | random 32+ bytes | Signs unsubscribe tokens |
| `TAXNG_DATA_DIR` | `/data` | SQLite location (volume) |
| `TAXNG_ADMIN_EMAILS` | comma list | Platform admins on first sign-in |
| `TAXNG_ADAPTER_MESSAGING` | `production` | Real email delivery |
| `TAXNG_RESEND_API_KEY` | secret | Resend API key |
| `TAXNG_MAIL_FROM` | `tax.ng <no-reply@tax.ng>` | Verified sender |

Every other adapter (filing, payments, KYC, registers, WhatsApp) stays in
sandbox until credentials and authorisation exist. Sandbox results are labelled
as such and "File & Pay" stays hidden.

## Before a public launch

All rules under `rules/` are `unverified` or `secondary_source`; none is
`legal_approved`. The UI shows the status beside every figure, but the
two-reviewer legal sign-off should precede promoting the site.
