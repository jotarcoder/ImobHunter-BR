# Recuperação Apple Silicon v2.1.2 — 04/11/2026

Falha confirmada no run 41898423206, job 126814105164:
PyInstaller IncompatibleBinaryArchError para
`pyarrow/_acero.cpython-311-darwin.so` porque o pacote instalado
no runner Intel contém apenas a arquitetura x86_64 e não pode ser
empacotado como arm64.

A correção substitui o cross-build Intel por **runner macos-15 nativo ARM64**
com PyArrow instalado na própria arquitetura. A compilação e o pacote
DMG exigem lipo arm64 em todos os binários e validação hdiutil.

**Não repetir o que já deu certo:**
- Windows candidato 2.1.2: run 41892355706, hash SHA256
  811DB6716B8AB635BEDDFE30E07B07F835DDC1770E76AA987009ED04B986F537.
- Linux: run 41898423206, job linux sucesso.
- macOS Intel: run 41898423206, job macos-intel sucesso.

Após o único build Apple Silicon nativo, o workflow recupera as outras
três partes sem compilar novamente; valida quatro arquivos e publica em
`releases/v2.1.2/` no Cloudflare R2. Só depois o site muda seus links
em PR separado, e só depois dessa mudança os objetos 2.1.1 são excluídos.

Sem certificado digital Code Signing, os avisos de SmartScreen e
notarização podem persistir; não orientar o usuário a desativar antivírus.
