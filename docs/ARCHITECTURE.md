# Arquitetura

O PC do cliente executa consultas, GIS, cache e análise. O servidor fica restrito a autenticação, licença, ativação e configuração mínima.

Fontes externas são adapters isolados. O domínio não conhece URLs ou detalhes de provedores.

Cada fato externo deverá carregar proveniência: fonte, instante, referência e confiança.

GeoSampa será o primeiro adapter municipal real, sem transformar São Paulo em dependência nacional.
