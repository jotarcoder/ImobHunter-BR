# Recuperação independente do instalador macOS Apple Silicon v2.1.0

## Motivo

Na geração original da v2.1.0 (Actions run `41527699227`),
os builds Windows, Linux e macOS Intel produziram artefatos completos.
O job `macos-arm`, agendado em `macos-26`, foi cancelado **sem iniciar
nenhuma etapa de compilação**. O fluxo original não conseguiu produzir
o quarto `.dmg` nem o manifesto SHA-256. Não há evidência de que o
código do aplicativo ou a compilação ARM tenha falhado: o runner
nem chegou a executar o script.

## Nova construção, independente do workflow anterior

Este é um **novo workflow**, `.github/workflows/macos-apple-silicon-standalone.yml`,
não uma repetição nem um remendo do job cancelado:

1. Somente depois de **CI verde na main**, e apenas para o merge
   com o identificador `standalone v2.1.0 Apple Silicon installer`,
   a recuperação é habilitada.
2. Uma verificação curta em Linux confirma que o commit alterou o
   novo workflow, que a origem dos três instaladores existentes é
   `b26ebfaf439db046fddf7fa91c5fc3956a207b98` e que os três
   artefatos ainda estão disponíveis no GitHub.
3. O macOS Apple Silicon usa **`macos-15`** e comprova ARM64 via
   `uname -m`, `platform.machine()` e `lipo -archs`. Este é um
   runner ARM64 oficialmente suportado para repositórios privados.
4. A compilação parte do **mesmo commit v2.1.0** dos outros três
   instaladores, com PySide6 6.8.3 e PyInstaller 6.22.3.
5. O novo `.app` é compilado do zero, validado quanto à arquitetura
   e ao certificado HTTPS embutido, empacotado em DMG e validado por
   `hdiutil verify`.
6. Somente o novo DMG é enviado para o GitHub Actions como artefato.
   Não são refeitos os builds Windows, Linux ou Mac Intel.
7. Um job final **baixa os três arquivos existentes**, baixa o
   ARM recém-gerado, verifica os quatro e produz manifesto SHA-256.

### Segurança do release

Nenhuma ação faz upload ao Cloudflare R2, substitui downloads,
publica GitHub Release, cria tag ou promove artefato a versão pública.
O fluxo antigo não é reexecutado nem suas etapas reaproveitadas.
O download dos três instaladores originais é somente leitura.

Os artefatos resultantes continuarão sendo **candidatos para homologação**.
A instalação real e os testes visuais em Apple Silicon permanecem
pendentes até haver uma máquina macOS ARM disponível.

### Restrições externas

O runner `macos-15` é suportado pelo GitHub, mas a disponibilidade
imediata depende da capacidade e dos limites da conta. Se não receber
runner, a geração seguirá na fila; o workflow não declara sucesso
antes de produzir e validar o DMG.
