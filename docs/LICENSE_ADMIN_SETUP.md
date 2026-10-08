# Licenças e painel administrativo

## Arquitetura

- Supabase Postgres guarda somente metadados de licença e ativações.
- Supabase Auth autentica o único administrador permitido: `juninhoovf@gmail.com`.
- Render mantém o endpoint administrativo e de verificação.
- O executável desktop nunca recebe a chave secreta do Supabase.
- A chave de licença é armazenada no banco apenas como SHA-256; o valor completo aparece somente no momento da emissão.
- O identificador do dispositivo também é armazenado somente como hash.
- Processamento imobiliário continua local no PC.

## Segredos no Render

Configure no serviço `ImobHunter-BR`:

- `SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY`
- `SUPABASE_SECRET_KEY`
- `IMOBHUNTER_LICENSE_SIGNING_SECRET`

A secret key nunca deve entrar no GitHub, navegador, instalador ou executável. O Supabase recomenda que chaves secretas permaneçam somente em componentes backend controlados.

## Supabase

1. Criar um projeto Supabase.
2. Criar o usuário administrador `juninhoovf@gmail.com` no Supabase Auth e definir a senha no próprio Supabase.
3. Executar `supabase/migrations/20261008_license_system.sql` no SQL Editor.
4. Copiar a URL e a publishable key para os segredos do Render.
5. Criar uma secret key para o backend e colocá-la somente no Render.
6. Gerar um segredo aleatório forte para `IMOBHUNTER_LICENSE_SIGNING_SECRET`.

## Painel

Depois dos segredos e da migração, o painel fica em:

`/admin/`

O painel não expõe a secret key e não grava senhas próprias. A autenticação passa pelo Supabase Auth.
