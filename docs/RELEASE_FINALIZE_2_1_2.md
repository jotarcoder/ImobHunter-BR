# Publicação v2.1.2 de ImobHunter — autorização explícita do proprietário

O Windows 2.1.2 já foi compilado e validado no run 41892355706.
SHA256 do EXE: `811DB6716B8AB635BEDDFE30E07B07F835DDC1770E76AA987009ED04B986F537`.
A assinatura Authenticode continua **NotSigned**, pois não foi fornecido certificado.
Uma varredura do Windows Defender no runner finalizou sem ameaça detectada,
mas a proteção em tempo real estava desabilitada; não é garantia absoluta.

Este workflow especial executa apenas após o CI verde da PR que o adicionou à
`main`, e apenas se o código do aplicativo for equivalente ao do Windows já
gerado. O Windows é **reaproveitado** e não recompilado. Os três pacotes que
ainda faltam são gerados uma única vez:

* Linux AppImage
* macOS Intel DMG
* macOS Apple Silicon ARM64 DMG

O publish só roda se os três jobs ficarem verdes, o Windows preservar o SHA256
validado e os quatro arquivos tiverem tamanhos não nulos. Os arquivos são
publicados na pasta **releases/v2.1.2/** do R2, sem sobrescrever ainda os links
do site e sem excluir o conjunto anterior durante o upload.

Depois da verificação pública, alterar `web/index.html` via PR e validar
Cloudflare Pages, **então** remover os objetos v2.1.1 e atualizar os aliases
na raiz. Se qualquer build falhar, o R2 não é alterado e o 2.1.1 permanece.
Não instruir o usuário a desativar ou ignorar o antivírus.
