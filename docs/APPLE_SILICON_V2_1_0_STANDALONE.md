# ImobHunter-BR v2.1.0 — Apple Silicon por compilação cruzada no Mac Intel

## Falha identificada

O workflow v2.1.0 original [#41527699227](https://github.com/jotarcoder/ImobHunter-BR/actions/runs/41527699227) preservou os instaladores Windows, Linux e macOS Intel; o job de macOS ARM64 foi cancelado **sem sequer executar um passo**. A tentativa independente [#41532746465](https://github.com/jotarcoder/ImobHunter-BR/actions/runs/41532746465) repetiu o problema mesmo em `macos-15` ARM.

Portanto, **não há evidência de falha de código do aplicativo**: a máquina ARM64 não foi disponibilizada. Não é útil recompilar os outros três instaladores nem repetir a mesma fila.

## Correção de arquitetura

O workflow independente `.github/workflows/macos-apple-silicon-standalone.yml` foi adaptado para gerar um aplicativo **ARM64 usando `macos-15-intel`**, o mesmo tipo de runner que já executou a build Intel da v2.1.0.

A compilação cruzada é suportada pelo PyInstaller com a opção `--target-arch arm64`, desde que a instalação do Python e as dependências nativas contenham ARM64 em pacotes `universal2`. O PySide6 6.8.3 fornece wheels `universal2`, e o `actions/setup-python` usa distribuições Python `universal2` para Python 3.11+. Fontes técnicas:

- https://www.pyinstaller.org/en/stable/feature-notes.html
- https://github.com/actions/setup-python/issues/960
- https://pypi.org/project/PySide6/6.8.3/

## Regras e verificações

1. O job só é liberado após **CI verde na main**, com o commit que alterou este workflow e contém o marcador de recuperação. Não é disparado por PR.
2. Um job em Linux confere que os **três artefatos originais** estão íntegros no GitHub Actions e associados ao SHA `b26ebfaf439db046fddf7fa91c5fc3956a207b98`.
3. Em `macos-15-intel`, o build checa `x86_64` (host), Python 3.11 com código `arm64` disponível, versão `2.1.0` e `PySide6.QtCore` com uma fatia ARM64.
4. Compila **do zero a partir do mesmo SHA da release** com `python -m PyInstaller --target-arch arm64`, preservando recursos de interface e base de DDD.
5. Verifica o executável principal **somente arm64** e cada biblioteca/plugin Mach-O embarcado com uma fatia `arm64`; rejeita automaticamente módulos x86_64-only. Confere também `cacert.pem`.
6. Cria o arquivo `ImobHunter-BR-macOS-AppleSilicon.dmg`, exige `hdiutil verify` e publica **somente o artefato privado do GitHub Actions**.
7. O manifesto final baixa os três arquivos antigos + DMG ARM novo, calcula SHA-256 e lista versões e commit de origem.

## Limitações

Compilação cruzada **não executa o aplicativo num Mac Apple Silicon**. Portanto, mesmo com o DMG íntegro e dependências ARM64 verificadas, é necessária a homologação visual/manual num Mac ARM antes de disponibilizar a clientes. O workflow não inventa essa verificação.

Nenhuma etapa modifica os instaladores existentes, publica GitHub Release ou transfere arquivos ao Cloudflare R2. Se a compilação falhar por alguma dependência sem ARM64, o job fica vermelho com o componente indicado, em vez de entregar um DMG inválido.
