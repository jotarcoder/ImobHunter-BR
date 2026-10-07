# Arquitetura

O PC do cliente executa consultas, GIS, cache e análise. O servidor fica restrito a autenticação, licença, ativação e configuração mínima.

Fontes externas são adapters isolados. O domínio não conhece URLs ou detalhes de provedores.

Cada fato externo deverá carregar proveniência: fonte, instante, referência e confiança.

GeoSampa será o primeiro adapter municipal real, sem transformar São Paulo em dependência nacional.

A INDE atua como camada nacional de descoberta de geosserviços. Seu catálogo identifica serviços OGC como WMS, WFS e WCS e ajuda o aplicativo a localizar fontes municipais, estaduais e federais. Ela não é tratada como fonte cadastral de imóveis e, portanto, não gera PropertyRecord nem participa da reconciliação de identidade.
