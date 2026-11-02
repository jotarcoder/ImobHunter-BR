# ImobHunter-BR v2.1.0 — instaladores candidatos

Esta versão incorpora as etapas integradas à `main` após v2.0.0:
mapa cadastral navegável, dossiê e janelas ajustados à resolução,
fontes cadastrais municipais, teste de conectividade e cadastro local
de novas fontes municipais com importação de CSV, XLSX, JSON e GeoJSON.

## Versionamento

A versão v2.1.0 é única para:

- `pyproject.toml`;
- `imobhunter/__init__.py`;
- recurso de versão Windows `packaging/windows/version_info.txt`;
- padrão do Inno Setup `packaging/windows/ImobHunter-BR.iss`.

O extra desktop mantém PySide6 6.8.3, homologado com os testes Qt Linux.

## Produção dos quatro instaladores

A compilação **só** se inicia depois do CI verde da `main` **quando
o commit tiver mudado a versão em pyproject.toml**. Commits comuns sem
nova versão não acionam o trabalho de Windows/macOS/Linux.

O workflow `Release installers` compila e anexa quatro arquivos como
artefatos privados de CI na própria execução, sem publicar release ou R2:

| Destino | Artefato | Arquivo interno |
| --- | --- | --- |
| Windows | ImobHunter-BR-Windows | ImobHunter-BR-Setup-Windows.exe |
| Linux x86_64 | ImobHunter-BR-Linux | ImobHunter-BR-Linux.AppImage |
| macOS Intel | ImobHunter-BR-macOS-Intel | ImobHunter-BR-macOS-Intel.dmg |
| macOS Apple Silicon | ImobHunter-BR-macOS-AppleSilicon | ImobHunter-BR-macOS-AppleSilicon.dmg |

Quando os quatro builds passam, um job final verifica que os arquivos
não estão vazios e anexa `ImobHunter-BR-Checksums-v2.1.0` com hash SHA256,
versão e commit de origem. Se um runner, por exemplo macOS ARM, não
estiver disponível, o manifesto **não** pode ser aprovado.

Os testes automatizados validam código, metadados, versão e certificados
CA incorporados aos executáveis. Eles não substituem um teste humano de
instalação/ativação, Qt, mapa e importação em Windows/Linux/macOS.

## Publicação no R2 — proibida nesta fase

O workflow `Publish installers to Cloudflare R2` **não responde mais
automaticamente** ao sucesso do build. É necessário dispará-lo
manualmente com uma tag de release que já tenha quatro instaladores
validados e marcar `confirm_publish=true`.

O workflow de build preserva um comando manual `workflow_dispatch`
para um release futuro, mas o uso automático de v2.1.0 só produz artefatos
para avaliação. Não substituir os downloads atuais do Cloudflare R2 nem
afirmar que o aplicativo novo já está publicado até a homologação final.
