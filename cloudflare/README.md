# ImobHunter Cloudflare licensing

## Endpoints

- License Worker: https://imobhunter-license.imobhunterbr.workers.dev
- Institutional Pages project: https://imobhunter-br.pages.dev

The Pages project has been created, but the first static deployment still needs the Cloudflare API token in GitHub Actions. The Git integration attempt returned a Cloudflare Pages installation error, so the project uses direct deployment through Wrangler.

## Deploy the license Worker

1. The D1 database `imobhunter-licenses` has been created and `schema.sql` applied.
2. The D1 database ID is configured in `wrangler.toml`.
3. In Cloudflare Dashboard, open Workers & Pages → `imobhunter-license` → Settings → Variables and Secrets.
4. Add `ADMIN_EMAIL` as a **Secret** with the authorized administrator email.
5. Add `ADMIN_PASSWORD` as a **Secret** with the temporary initial password provided privately to the administrator. Never commit either value to Git or bundle it into the desktop installer.
6. Deploy the Worker, then open `/admin` and sign in with email and password. The first successful login stores a salted PBKDF2 password hash in D1; the temporary password secret is only used to bootstrap that first login. Change the password in the Security section immediately. Sessions expire after eight hours.

## GitHub Actions deployments

Add the repository secret `CLOUDFLARE_API_TOKEN` with permissions for Workers Scripts Write, Pages Write, D1 Read, and any account settings read permissions requested by Wrangler. The account ID is already configured in the workflows.

After adding the secret, run **Deploy institutional website to Cloudflare Pages** once from GitHub Actions to publish the current `web/` directory. Later changes under `web/**` deploy automatically. Changes under `cloudflare/**` deploy the Worker automatically. Both workflows skip cleanly while the secret is absent.

## License behavior

The first-time customer key is a 256-bit cryptographically random hexadecimal string. Only its SHA-256 digest is stored. The admin must paste the exact UUID displayed by the customer's desktop app when creating a client; the key is bound to that ID. The complete key is returned once when an admin creates a client or rotates a key. New licenses begin in `pending`; an administrator must activate them after confirming payment. The desktop revalidates every five minutes, so suspensions and expirations take effect during an open session.

## Routes

- `GET /health`: service health.
- `GET /admin`: administrative interface; every admin API requires a signed, expiring session.
- `POST /api/license/activate`: checks user ID, key hash, status and expiry.
- `/api/admin/clients`: create/list clients, activate, suspend, rotate keys, change plan and archive clients.
- `GET /api/admin/audit`: recent administrative actions.

## Prices configured

- Monthly: R$ 3.000, valid for one month.
- Annual: R$ 20.000, valid for twelve months.
- Sales requests use the plan-specific WhatsApp links on the institutional website; the phone number is not printed on the page.
