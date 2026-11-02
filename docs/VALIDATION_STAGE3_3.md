# Etapa 3.3 — Configurações e fontes municipais sincronizadas

O cadastro de endpoints exibido em **Configurações > Fontes cadastrais municipais**
é gerado diretamente dos **mesmos URLs constantes dos adaptadores de consulta**.
Isso evita que a tela de Configurações descreva um endpoint diferente do
efetivamente usado pela Prospecção.

## Endpoints disponíveis

| Município | Integração | Tipo | Notas |
| --- | --- | --- | --- |
| São Paulo capital/SP | GeoSampa, geoportal:lote_cidadao | WFS | Exclusivo da capital; endpoint configurável somente em domínio HTTPS gov.br |
| Praia Grande/SP | Cadastro municipal | WFS | O retorno espacial não implica SQL/IPTU |
| Santos/SP | Cadastro municipal | WFS | SQL/IPTU não garantido nos dados efetivamente retornados |
| Bertioga/SP | Cadastro municipal | WFS | Portal indisponível conforme teste manual; manter TLS ativo |
| Belo Horizonte/MG | BHMap | WFS | Camadas anunciadas via GetCapabilities |
| Rio de Janeiro/RJ | Imóveis territoriais e GeoPAL | ArcGIS | GeoPAL é fallback, não fonte primária |
| Brasília/DF | IDE-DF | ArcGIS | Apenas atributos efetivamente divulgados |
| Goiânia/GO | Mapa municipal | ArcGIS | Inscrição não equivale automaticamente a SQL |
| Blumenau/SC | Lotes | ArcGIS | Identificador IQ é distinto de SQL |
| Recife/PE | Dados abertos IPTU | CKAN | Catálogo não garante API de linhas/endereço ou geometria |
| Porto Alegre/RS | Lotes fiscais | ArcGIS | SQL individual não garantido |

Outros municípios podem ter descoberta de geosserviços via INDE, que é
um recurso separado e não constitui integração cadastral validada.

## Seleção do endpoint

O adaptador só consulta seu serviço oficial quando o **município e a UF**
correspondem à integração. **GeoSampa não é utilizado** para Bertioga,
Santos, Praia Grande nem outro município fora de São Paulo capital.
A fonte de Rio de Janeiro utiliza GeoPAL apenas se a camada territorial
não retornar registros. Fontes não integradas não são rotuladas como se
tivessem cadastro SQL disponível.

## Testes na janela de Configurações

O botão de cada município executa somente o teste de metadados:

- WFS: GetCapabilities (GeoSampa em 1.0.0; os demais iniciam em 2.0.0,
  com versões anteriores em caso de HTTP 403);
- ArcGIS REST: JSON de descrição da camada;
- CKAN Recife: confirmação da resposta do catálogo.

As chamadas usam HTTPS oficial com verificação de certificados, limite de
tempo de **8 segundos** e workers Qt em segundo plano. A interface exibe
separadamente **metadados acessíveis**, **falha de conexão** ou **timeout**,
sem bloquear edição de outras configurações.

Um teste de metadados bem-sucedido **não comprova dados de um imóvel**,
SQL/IPTU, área, proprietário nem lote.

## Validação

- Unitários MockTransport sem chamadas reais de rede: URLs da interface,
  roteamento por município/UF, protocolos WFS/ArcGIS/CKAN e falhas TLS.
- Teste Qt offscreen: abre Configurações, verifica links somente-leitura,
  testa o botão em worker e confirma o estado exibido.
- CI: compileall, pytest e Ruff; não há necessidade de builds Windows/macOS.
- A homologação visual dos instaladores Windows/Linux permanece etapa de
  release posterior; nenhum upload R2 é acionado aqui.
