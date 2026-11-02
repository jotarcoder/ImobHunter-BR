# Etapa 3 — homologação do mapa e fontes oficiais

Esta etapa é um PR único para estabilizar a Prospecção depois da integração
do mapa cadastral nativo. Não modifica a Inteligência de Mercado, não publica
instaladores e não cria novos serviços externos.

## 3.1 — Mapa cadastral

- Testes Qt reais, em Linux com tela virtual (QT_QPA_PLATFORM=offscreen),
  criam a janela de dossiê, fornecem dois polígonos diferentes, abrem a aba
  Mapa cadastral, selecionam o vizinho, conferem a ausência do SQL do alvo
  na ficha do vizinho, copiam os dados e alteram o nível geográfico de zoom.
  Todas as buscas HTTP de mosaicos são desativadas nesses testes.
- Outro teste confirma que uma geocodificação pontual sem GeoJSON não
  vira uma geometria fiscal inventada.
- Downloads dos mosaicos são limitados a 3 trabalhos concorrentes por mapa
  (máximo 36 mosaicos diferentes por viewport), usando o pool de threads
  compartilhado do processo. Fechar a janela não espera dezenas de requisições
  HTTP enfileiradas; o mapa permite tentar novamente ruas temporariamente offline.
- A validação de anéis GeoJSON é estrita: vértice ou buraco inválido invalida
  o polígono em vez de gerar novos limites conectando pontos distantes.

## 3.2 — Cadastro oficial e erro de fonte

- Em WFS, o GetCapabilities pode responder, mas o GetFeature de uma
  determinada camada devolver HTTP 400 ou uma ServiceException. Tentamos
  protocolos 2.0.0, 1.1.0 e 1.0.0 com os parâmetros adequados a cada versão,
  registrando cada tentativa. Uma camada falha não impede tentar outra;
  HTTP 429 e erros 5xx não disparam novas tentativas por versão.
- Uma camada válida, mas vazia, não transforma a falha de outra camada
  cadastral em "imóvel não encontrado". A consulta é sinalizada como
  erro/consulta parcial, preservando os diagnósticos.
- A Prospecção e o teste de integração exibem falha municipal como
  fonte indisponível em vez de "nenhum imóvel encontrado".
- O relatório live registra, por município, SQL/IPTU explícito, quadra/lote,
  polígono válido, nível de correspondência e erro do próprio município;
  não mistura falhas de consultas de outras cidades.
- Endpoints permanecem em HTTPS governamental com validação de certificados.
  Bertioga: o usuário confirmou manualmente a API indisponível.
  Não há confirmação de manutenção programada e nenhuma tentativa de
  burlar TLS foi implementada. Quando o servidor voltar, o diagnóstico
  pode ser executado novamente.

### Critérios e limitações

1. Executar compilação Python, pytest, ruff e o job Linux Qt offscreen.
2. Inspecionar os relatórios de São Paulo capital e Praia Grande para
   registros e geometria genuínos. Santos, Bertioga e Recife permanecem
   sujeitos a respostas dos serviços externos; o aplicativo não pode
   garantir SQL, área ou lotes a partir de geocodificação isolada.
3. Fazer também o aceite visual do instalador no Windows e Linux, com
   conexão ativa e modo offline. O teste Qt virtual não substitui esta
   homologação manual.
4. Não incorporar na main antes do CI verde; não executar builds de
   quatro plataformas nem subir arquivos no R2 até uma etapa de release
   expressamente autorizada.

### Fluxo de aceite desktop

1. Pesquisar Avenida Paulista, 1000, São Paulo/SP e registrar a situação
   real do GeoSampa, incluindo camada, SQL/IPTU, quadra, lote e geometria
   somente se houver dados oficiais efetivos.
2. Abrir a aba Mapa cadastral, arrastar, aproximar, enquadrar, clicar em
   dois lotes adjacentes e copiar seus identificadores separadamente.
3. Pesquisar Avenida Presidente Costa e Silva, Praia Grande/SP, revisar
   a fonte municipal e verificar atributos fiscais quando fornecidos.
4. Desconectar a internet: o dossiê e os polígonos anteriormente retornados
   continuam acessíveis; mosaicos de ruas podem faltar. Reativar rede e
   testar o botão Recarregar ruas.
5. Pesquisar Avenida Anchieta, Bertioga/SP: se o portal ainda estiver
   indisponível, deve aparecer o erro de conexão/certificado — nunca
   "não existe imóvel".
