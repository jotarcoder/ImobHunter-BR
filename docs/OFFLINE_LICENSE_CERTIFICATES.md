# Licença offline até o vencimento — ImobHunter-BR

## Política

- A primeira ativação exige internet e emissão de um certificado de licença pelo Worker.
- O certificado é assinado com ECDSA P-256/SHA-256 e contém user_id, SHA-256
  da chave, plano, emissão e vencimento. O aplicativo verifica a assinatura
  com a chave pública embutida.
- Após a ativação, indisponibilidade de internet/Cloudflare não desloga o usuário:
  a licença continua válida offline até o vencimento indicado no certificado.
- O aplicativo revalida a cada 5 minutos em thread de rede e atualiza o certificado
  quando há autorização online. Renovações exigem conexão.
- Negação explícita pelo Worker (suspensa, excluída, vencida, chave trocada)
  bloqueia o aplicativo e persiste um marcador local de bloqueio. O desbloqueio
  exige uma autorização online verdadeira.
- Erros de DNS, TLS, timeout, HTTP 5xx, páginas HTML de WAF e respostas malformadas
  não provam revogação e não apagam a chave armazenada.
- A validade offline depende do relógio local. Um retrocesso significativo exige
  nova verificação online. Nenhum controle local é absolutamente inviolável.
- Suspensões e trocas de chaves durante um período offline só serão conhecidas
  na próxima reconexão, limitação inerente ao acesso offline até o vencimento.

## Chaves do servidor (obrigatório antes do deploy)

1. Gerar um par ECDSA P-256 em ambiente seguro. Guardar chave privada apenas
   no segredo Cloudflare Worker LICENSE_SIGNING_PRIVATE_JWK (JSON JWK com
   kty=EC, crv=P-256, x, y e d).
2. Chave pública não secreta fica em imobhunter/offline_license.py,
   como PUBLIC_KEY_HEX, no formato 04 || x || y.
3. Nunca adicionar JWK privado, chaves de clientes ou dados pessoais no Git,
   CI, logs ou instaladores.
4. Configurar o segredo antes de publicar o Worker novo. Caso ausente, API
   responde HTTP 503 LICENSE_SIGNER_UNAVAILABLE; não emite certificado sem assinatura.
5. Guardar backup seguro da chave privada. Rotação exigirá política versionada
   para manter certificados antigos válidos nos desktops existentes.

## Ordem de entrega

1. PR com código Worker e desktop, testes de pytest, ruff, compileall e Node.
2. Configurar e confirmar segredo Worker; não publicar se ausente.
3. Merge no main após validação, deploy Worker primeiro, instaladores depois.
4. Homologar Windows, Linux, macOS Intel e macOS Apple Silicon.
5. Só publicar os quatro instaladores no R2 após homologação.

## Testes críticos

- Timeout após ativação mantém acesso sem apagar chave.
- Sem internet na primeira ativação não concede acesso.
- Expiração, adulteração, ID ou chave divergente e relógio retrocedido não
  recebem autorização offline.
- Negação explícita bloqueia o uso local mesmo se a internet cair depois.
- Renovação online assina novo certificado e remove o marcador de bloqueio.
- Worker sem segredo de assinatura retorna HTTP 503.
- Nenhum teste modifica dados do D1 de produção.
