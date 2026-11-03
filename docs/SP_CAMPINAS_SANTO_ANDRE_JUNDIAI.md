# Consulta cadastral oficial: Campinas, Santo André e Jundiaí (SP)

## Campinas
A Prefeitura informa que seu Zoneamento aceita busca por endereço e número,
sem login, e pode devolver um código cartográfico de 12 números, quarteirão,
quadra e lote. Os sufixos por tipo de imóvel e unidades em condomínio devem
ser confirmados com a Prefeitura. O portal NÃO é uma API automaticamente homologada.

Fonte: https://portal-adm.campinas.sp.gov.br/servico/busca-do-codigo-cartografico
Portal: https://zoneamento.campinas.sp.gov.br/

## Santo André
O SIGA oferece busca por logradouro oficial e número predial e retorna a
classificação fiscal composta por setor, quadra e lote, segundo a Prefeitura.
Seu WFS anônimo previamente testado não publicou uma API cadastral por endereço.
A consulta ao vivo deve ser feita na busca fiscal, não no WFS cartográfico.

Portal: https://sigamapa.santoandre.sp.gov.br/index.aspx?id=search_sql
Orientações oficiais: https://siga.santoandre.sp.gov.br/Perguntas

## Jundiaí
A Prefeitura confirmou a busca pública pelo número do contribuinte por endereço
no GeoJundiaí. Para condomínios pode ser necessário selecionar uma unidade.
Não consultar módulos restritos a funcionários sem autorização.
A camada GeoJundiai:lotes_jund é somente cartografia e não prova SQL/IPTU.

Portal: https://geo.jundiai.sp.gov.br/geojundiai/cfImob.jsp
Anúncio: https://jundiai.sp.gov.br/noticias/2025/07/26/jundiai-disponibiliza-consulta-publica-ao-numero-de-cadastro-fiscal-imobiliario-pelo-geojundiai/

## Implementação
As Configurações passam a mostrar entradas de websites fiscais com botões
"Abrir fonte" e "Testar conexão". Um HTTP 200 de website só confirma a página,
não o registro do imóvel. Campinas recebe roteamento próprio sem GeoSampa.
Santo André e Jundiaí preservam seus adaptadores atuais e ganham referências
ao portal fiscal humano. Nenhum campo cadastral é inventado.

## Homologação pendente
Identificar endpoint e contrato público que recebam endereço/número e devolvam
identificação fiscal individual. Validar consulta real, incluindo unidade
condominial, e executar regressões antes de liberar preenchimento automático.

Sem executáveis novos, publicações no R2, scrape autenticado ou CAPTCHA bypass.
