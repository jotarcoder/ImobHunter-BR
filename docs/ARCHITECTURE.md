# Arquitetura

O PC do cliente executa consultas, GIS, cache e análise. O servidor fica restrito a autenticação, licença, ativação e configuração mínima.

Fontes externas são adapters isolados. O domínio não conhece URLs ou detalhes de provedores.

Cada fato externo deverá carregar proveniência: fonte, instante, referência e confiança.

GeoSampa será o primeiro adapter municipal real, sem transformar São Paulo em dependência nacional.

As fontes rurais e ambientais com APIs oficiais restritas, como SNCR/INCRA, SICAR/CAR e SIGEF, mantêm adapters próprios mesmo quando o acesso em produção depende de credenciais institucionais. O aplicativo não presume acesso anônimo: pode consumir exportações/cache autorizados localmente e fica preparado para integração oficial quando houver credenciais válidas.

O SICAR é exposto pelo Conecta gov.br em APIs separadas para imóvel, temas, demonstrativo e consulta CPF/CNPJ. A API de imóvel consulta o código CAR e retorna dados cadastrais/status; demonstrativo e tema complementam a análise ambiental. A integração runtime deve respeitar o onboarding, firewall e credenciais exigidos pelo Conecta.

O SIGEFGEO fornece consulta de parcelas georreferenciadas certificadas ou em regularização e, no ambiente oficial, é disponibilizado via Conecta gov.br com autenticação e controles de acesso. O adapter local mantém os campos de parcela, matrícula/transcrição, titular/detentor, área e geometria quando presentes em dados autorizados.

O CNIR integra dados do SNCR/INCRA e do CAFIR/RFB. O CIB é o identificador do imóvel rural no CAFIR. O serviço CNIR é autenticado e as consultas do usuário são realizadas dentro do ambiente oficial; o adapter CNIR aceita exportação/cache autorizado localmente, preservando CIB, código SNCR, situação cadastral, localização, dimensão e titularidade quando esses campos estiverem disponíveis. O aplicativo não presume uma API pública anônima para CNIR/CAFIR.

A Receita Federal disponibiliza consulta CNPJ por API no Conecta gov.br, com serviços básico, QSA e empresa, sujeitos a credenciais e regras de acesso. Também existem dados abertos da RFB para consumo automatizado. O adapter CNPJ permanece local-first: aceita exportações/dados abertos autorizados em CSV ou JSON e preserva situação cadastral, razão social, nome fantasia, natureza jurídica, CNAE e demais atributos disponíveis. A integração deve aceitar CNPJs alfanuméricos, pois o novo formato entrou em produção em 2026; não se deve validar CNPJ assumindo exclusivamente 14 dígitos numéricos.

A INDE atua como camada nacional de descoberta de geosserviços. Seu catálogo identifica serviços OGC como WMS, WFS e WCS e ajuda o aplicativo a localizar fontes municipais, estaduais e federais. Ela não é tratada como fonte cadastral de imóveis e, portanto, não gera PropertyRecord nem participa da reconciliação de identidade.

O ICMBio disponibiliza dados geoespaciais oficiais por meio dos geosserviços WFS/WMS da INDE, incluindo limites de Unidades de Conservação federais, cavernas, autos de infração, áreas embargadas e Planos de Ação Nacional. O adapter ICMBio mantém o processamento pesado local e aceita exportações/cache oficiais em CSV, JSON, GeoJSON ou JSONL. A integração pode evoluir para consulta WFS oficial, respeitando disponibilidade, limites e regras do serviço. Dados ambientais não são tratados como titularidade do imóvel: entram como enriquecimento territorial e podem indicar sobreposição ou proximidade ambiental.
