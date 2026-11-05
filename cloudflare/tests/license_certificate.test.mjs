import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { webcrypto } from 'node:crypto';
import { test } from 'node:test';

const crypto = webcrypto;

// Import the actual Worker module as ESM without changing the production .js layout.
const source = readFileSync(new URL('../worker.js', import.meta.url), 'utf8');
const worker = (await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))).default;
const userId = '00000000-0000-4000-8000-000000000001';
const activationKey = 'A'.repeat(64);
const expiresAt = new Date(Date.now() + 24 * 3600_000).toISOString();

function mockDb() {
  const statements = [];
  return {
    statements,
    prepare(sql) {
      const entry = { sql, params: [] };
      statements.push(entry);
      return {
        bind(...args) {
          entry.params = args;
          return this;
        },
        async first() {
          if (!sql.includes('FROM licenses')) throw Error('Unexpected SELECT: ' + sql);
          return {
            user_id: userId, status: 'active', plan: 'annual',
            expires_at: expiresAt, deleted_at: null,
            key_hash: Buffer.from(await crypto.subtle.digest(
              'SHA-256', new TextEncoder().encode(activationKey)
            )).toString('hex').toUpperCase()
          };
        },
        async run() { return { success: true, meta: { changes: 1 } }; }
      };
    }
  };
}

function activationRequest(key = activationKey) {
  return new Request('https://license.example/api/license/activate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId, activation_key: key })
  });
}

test('Worker signs a device-bound license with P-256, preserving expiry', async () => {
  const keypair = await crypto.subtle.generateKey(
    { name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']
  );
  const privateJwk = await crypto.subtle.exportKey('jwk', keypair.privateKey);
  const DB = mockDb();
  const response = await worker.fetch(activationRequest(), {
    DB, LICENSE_SIGNING_PRIVATE_JWK: JSON.stringify(privateJwk)
  });
  assert.equal(response.status, 200);
  const result = await response.json();
  assert.equal(result.authorized, true);
  const cert = result.license_certificate;
  assert.equal(cert.v, 1);
  const payload = JSON.parse(Buffer.from(cert.payload, 'base64url').toString('utf8'));
  assert.equal(payload.v, 1);
  assert.equal(payload.user_id, userId);
  assert.equal(payload.plan, 'annual');
  assert.equal(payload.expires_at, Math.floor(Date.parse(expiresAt) / 1000));
  assert.equal(payload.key_sha256, Buffer.from(
    await crypto.subtle.digest('SHA-256', new TextEncoder().encode(activationKey))
  ).toString('hex').toUpperCase());
  assert.equal(Buffer.from(cert.signature, 'base64url').length, 64);
  assert.equal(await crypto.subtle.verify(
    { name: 'ECDSA', hash: 'SHA-256' }, keypair.publicKey,
    Buffer.from(cert.signature, 'base64url'),
    new TextEncoder().encode(cert.payload)
  ), true);
  assert.ok(DB.statements.some(x => x.sql.includes('last_seen_at')));
});

test('Worker fails closed if signer is absent, without returning unsigned authorization', async () => {
  const response = await worker.fetch(activationRequest(), { DB: mockDb() });
  assert.equal(response.status, 503);
  const body = await response.json();
  assert.equal(body.authorized, false);
  assert.equal(body.code, 'LICENSE_SIGNER_UNAVAILABLE');
});

test('Worker rejects wrong activation key and never issues a certificate', async () => {
  const response = await worker.fetch(activationRequest('B'.repeat(64)), {
    DB: mockDb(), LICENSE_SIGNING_PRIVATE_JWK: 'not used'
  });
  assert.equal(response.status, 403);
  const body = await response.json();
  assert.equal(body.code, 'ACTIVATION_KEY_MISMATCH');
  assert.equal(body.license_certificate, undefined);
});
