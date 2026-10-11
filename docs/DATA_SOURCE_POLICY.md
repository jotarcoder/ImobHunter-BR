# Política de Fontes, Dados e Integrações — ImobHunter-BR

Versão 1.0.

## 1. Objetivo

O ImobHunter-BR é uma ferramenta de inteligência imobiliária e prospecção. Ele organiza informações provenientes de fontes públicas, oficiais, licenciadas ou fornecidas/autorizadas pelo usuário para ajudar na localização, conferência e enriquecimento de imóveis.

O sistema não é um cadastro imobiliário governamental e não substitui certidão, matrícula, registro de imóveis, consulta tributária oficial ou parecer jurídico.

## 2. Regra-mãe de integração

Toda fonte deve obedecer simultaneamente a estes princípios:

1. origem identificável;
2. finalidade compatível com o uso;
3. acesso autorizado;
4. minimização de dados;
5. preservação de proveniência e data da consulta;
6. respeito a limites técnicos, termos de uso e licenças;
7. nenhuma tentativa de burlar autenticação, CAPTCHA, firewall ou controle de acesso;
8. processamento pesado preferencialmente no computador do usuário;
9. dado público não é tratado como autorização automática para qualquer finalidade;
10. uma fonte deve poder ser desativada sem quebrar o restante do sistema.

## 3. Como cada integração é utilizada

### GeoSampa
Camada municipal geoespacial de São Paulo. Pode fornecer lote, quadra, CIB/SQL, endereço, área e geometria quando disponíveis. É usada para resolução territorial e enriquecimento cadastral. Não é apresentada como prova definitiva de propriedade.

### IBGE / CNEFE
Base de endereços e características do entorno/endereço. Ajuda a normalizar e conferir endereço, CEP, bloco, coordenadas e elementos censitários. Não é tratada como fonte de titularidade.

### SINTER / CIB
Camada relacionada à identificação cadastral imobiliária. O adapter trabalha com dados autorizados e preserva CIB, localização, quadra, lote, área e demais campos efetivamente fornecidos. A disponibilidade pode depender do ambiente oficial e de credenciais.

### SNCR / INCRA
Camada rural. Pode enriquecer imóveis com código, localização rural, área, situação e titularidade quando esses campos forem fornecidos por fonte autorizada. APIs oficiais com autenticação não são presumidas como abertas.

### SICAR / CAR
Camada ambiental/rural. Serve para verificar cadastro ambiental, situação, área e atributos ambientais quando disponíveis. Não representa matrícula nem prova de propriedade.

### SIGEF
Camada de parcelas georreferenciadas. Pode fornecer código de parcela, área, situação, matrícula/transcrição, titular/detentor e geometria quando presentes no dado autorizado. O acesso oficial pode exigir autenticação.

### CNIR
Integra informações cadastrais rurais relacionadas ao SNCR e CAFIR. O CIB é tratado como identificador cadastral quando fornecido. Não se presume consulta anônima; o adapter também aceita exportações/cache autorizados.

### Receita Federal / CNPJ
Usada para enriquecer estabelecimentos e pessoas jurídicas com CNPJ, razão social, nome fantasia, situação cadastral, CNAE e outros campos disponíveis. Não deve ser interpretada como prova de propriedade imobiliária. O sistema aceita o formato alfanumérico de CNPJ vigente.

### INDE
É uma camada de descoberta de geosserviços. Ajuda a localizar WMS/WFS/WCS e outras fontes públicas. Não é tratada como cadastro imobiliário e não gera titularidade.

### ICMBio
Camada ambiental federal. Pode indicar unidades de conservação, cavernas, áreas embargadas, autos e outras camadas ambientais. O uso é territorial: proximidade ou sobreposição pode gerar alerta, mas não determina propriedade.

### IPHAN
Camada de patrimônio histórico e arqueológico. Pode indicar bens protegidos, processos, tombamento, categoria e localização. Serve para alertar sobre restrições e contexto patrimonial; não determina titularidade.

### OpenStreetMap
Camada geográfica complementar para ruas, pontos, categorias e contexto territorial. Deve manter atribuição do OSM e respeitar a licença aplicável. O aplicativo não realiza consultas sistemáticas silenciosas ao Nominatim ou Overpass públicos.

### IPTU municipal
Camada tributária municipal. Pode registrar no_debt_found, debt_found, query_unavailable, authentication_required ou captcha_required, além de exercício, valor, vencimento e descrição quando disponíveis. CAPTCHA e autenticação nunca são contornados.

### Matrícula de imóvel / Registro de Imóveis
O campo explícito de matrícula é preenchido somente quando uma fonte autorizada consultada fornece esse dado, como o campo de registro de matrícula presente em determinados conjuntos SIGEF. O número é apresentado com a proveniência da fonte que o forneceu. Não se presume que endereço, SQL/inscrição de IPTU, CIB, quadra ou lote sejam uma matrícula. Quando nenhuma fonte consultada retornar o número, o aplicativo informa “não localizada nas fontes consultadas” e oferece acesso ao portal oficial RI Digital/ONR: https://registradores.onr.org.br/. A pesquisa registral pode depender de cartório, modalidade, cobertura, credenciais ou pagamento; o sistema não contorna autenticação nem simula uma consulta oficial.

### DDD / cobertura
O DDD é apenas um agrupador de navegação e cobertura. Não é equivalente a estado ou município. Um DDD pode abranger mais de uma UF.

## 4. Dados pessoais

Nome, CPF/CNPJ e outros identificadores somente devem aparecer quando a fonte autorizada efetivamente os disponibilizar para aquela finalidade. O ImobHunter não incorpora bases vazadas, grupos privados, listas de Telegram ou bancos obtidos sem origem legítima.

CPF não deve ser inferido. Se não houver campo oficial/autorizado, o resultado permanece ausente.

## 5. Proveniência

Cada fato importante deve poder ser associado a fonte, momento da consulta, referência e nível de confiança. Conflitos entre fontes não devem ser silenciosamente escondidos: o sistema deve sinalizar divergências.

## 6. Armazenamento

O desenho local-first mantém buscas, cache e processamento pesado no computador do usuário. O backend remoto é reservado para funções mínimas de autenticação, licenciamento, ativação e configuração. O projeto não deve enviar mapas, dumps GIS ou histórico completo de pesquisa para o servidor sem finalidade e consentimento apropriados.

## 7. Segurança

É proibido no projeto:
- contornar CAPTCHA;
- explorar autenticação;
- usar credenciais de terceiros;
- incorporar bases vazadas;
- mascarar a origem de dados;
- coletar dados além da finalidade do produto;
- vender uma fonte como oficial quando ela não é;
- afirmar propriedade com base apenas em enriquecimento geográfico.

## 8. Atualização

Fontes públicas mudam. Cada adapter deve registrar indisponibilidade e permitir atualização independente. Uma falha de uma fonte não pode derrubar toda a pesquisa.

## 9. Responsabilidade do usuário

O usuário deve usar os resultados para finalidades legítimas e fazer a validação documental necessária antes de decisões comerciais, jurídicas, tributárias ou registrais.

Este documento é uma especificação de produto e transparência. Para lançamento comercial, termos contratuais e tratamento de dados devem passar por revisão jurídica adequada à operação da empresa.
