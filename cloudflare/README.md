# ImobHunter Cloudflare licensing

## Endpoints

- License Worker: https://imobhunter-license.imobhunterbr.workers.dev
- Institutional Pages project: https://imobhunter-br.pages.dev

The Pages project has been created, but the first static deployment still needs the Cloudflare API token in GitHub Actions. The Git integration attempt returned a Cloudflare Pages installation error, so the project uses direct deployment through Wrangler.

## Deploy the license Worker

1. The D1 database `imobhunter-licenses` has been created and `schema.sql` applied.
2. The D1 database ID is configured in `wrangler.toml`.
3. In Cloudflare Dashboard, open Workers & Pages → `imobhunter-license` → Settings → Variables and Secrets.
4. Add `ADMIN_TOKEN` as a **Secret**. Use a unique, long random value. Never put it in Git or in the desktop installer.
5. Open `/admin` on the Worker URL and enter that token. Admin APIs return 401 until the secret exists (fail-closed).

## GitHub Actions deployments

Add the repository secret `CLOUDFLARE_API_TOKEN` with permissions for Workers Scripts Write, Pages Write, D1 Read, and any account settings read permissions requested by Wrangler. The account ID is already configured in the workflows.

After adding the secret, run **Deploy institutional website to Cloudflare Pages** once from GitHub Actions to publish the current `web/` directory. Later changes under `web/**` deploy automatically. Changes under `cloudflare/**` deploy the Worker automatically. Both workflows skip cleanly while the secret is absent.

## License behavior

The first-time customer key is a 256-bit cryptographically random hexadecimal string. Only its SHA-256 digest is stored. The complete key is returned once when an admin creates a client or rotates a key. New licenses begin in `pending`; an administrator must activate them after confirming payment. The desktop revalidates every five minutes, so suspensions and expirations take effect during an open session.

## Routes

- `GET /health`: service health.
- `GET /admin`: administrative interface; every admin API requires the token.
- `POST /api/license/activate`: checks user ID, key hash, status and expiry.
- `/api/admin/clients`: create/list clients, activate, suspend, rotate keys, change plan and archive clients.
- `GET /api/admin/audit`: recent administrative actions.

## Prices configured

- Monthly: R$ 3.000, valid for one month.
- Annual: R$ 20.000, valid for twelve months.
- Contact for activation: +55 (11) 99903-7737.
