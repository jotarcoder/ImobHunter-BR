# ImobHunter-BR — After Effects Motion Direction

## Objetivo

Transformar a identidade atual do produto em um **product film cinematográfico premium**, sem transformar a landing page em uma versão funcional do sistema.

A landing continua institucional. O After Effects demonstra capacidade, arquitetura e posicionamento através de uma linguagem audiovisual contemporânea.

## Sistema visual

- Fundo: `#06111B`
- Verde assinatura: `#35FF77`
- Texto principal: `#EDF5FA`
- Texto secundário: `#91A5B6`
- Painéis: `#0A1827` / `#0E1C2B`
- Grade: `#1D3449`
- Acentos: `#68B8FF`, `#FF7894`
- Tipografia: Inter; Bold para títulos e Regular para suporte.
- Grade editorial: 160 px vertical / 120 px horizontal em 1920x1080.
- Linguagem: precisão, profundidade, escala, silêncio e microdetalhes.

## Cinematografia V2 — 16 segundos

**0–1,2 s — Atmosfera**
- câmera começa distante;
- partículas discretas em diferentes planos Z;
- grade nasce em baixa intensidade;
- glow verde e azul muito controlado;
- uma linha de varredura reforça o eixo editorial.

**1,2–1,75 s — Hero**
- “CAÇANDO OPORTUNIDADES • BRASIL” entra primeiro;
- “Dados reais.” e “Decisões inteligentes.” entram em stagger;
- pequeno deslocamento Z e escala, sem bounce;
- a câmera começa a aproximar.

**1,75–4,05 s — Produto**
- interface entra como objeto material 3D;
- barra, campo de busca, badge e cards entram em sequência;
- cursor de busca funciona como microdetalhe;
- luz pontual cria sensação de volume;
- câmera faz push-in e arco lateral.

**4,05–6,2 s — Inteligência**
- a interface perde protagonismo;
- fontes surgem como rede de evidências;
- nós e conexões criam uma constelação documental;
- o ritmo fica mais preciso e menos publicitário.

**6,2–10 s — Dossiê**
- a rede converge para um painel de dossiê;
- identificação, endereço, área, coordenadas, proveniência e confiança aparecem em camadas;
- a mensagem visual é: informação dispersa → evidência reconciliada → dossiê.

**10–14,9 s — Assinatura**
- a composição simplifica agressivamente;
- “Caçando oportunidades.”;
- ImobHunter-BR;
- CTA visual;
- marca mínima.

**14,9–16 s — Outro**
- câmera respira;
- elementos recuam em profundidade;
- fade cinematográfico, sem corte brusco.

## Referências corretas de linguagem

Usar como referência de **princípios**, não como cópia:

1. **Apple product films** — câmera, luz, escala, materialidade e silêncio visual.
2. **Linear** — dark UI, tipografia, grid, contraste e microinterações.
3. **Mapbox** — câmera sobre informação geográfica, escala espacial e dados como ambiente.
4. **Stripe** — composição editorial, clareza, ritmo e hierarquia.
5. **Motion editorial contemporâneo** — partículas discretas, transições motivadas pelo conteúdo e uso econômico de efeitos.

A referência deve orientar **fotografia, ritmo, composição, profundidade e comportamento**, nunca copiar layout, texto, identidade ou animação específica.

## Arquivo principal

`motion/after-effects/ImobHunter_Cinematic_V2_16s.jsx`

O script cria uma composição procedural 1920×1080 / 30 fps / 16 s com:
- câmera 3D;
- parallax por profundidade;
- grade editorial;
- partículas;
- luz pontual;
- glows;
- tipografia;
- UI material;
- rede de evidências;
- dossiê;
- CTA;
- marcadores de timeline.

## Render

Master: ProRes 422 HQ, 1920×1080, 30 fps.

Web: H.264, 1920×1080, 15–25 Mbps, AAC 48 kHz.

Versão vertical posterior: 1080×1920, reposicionando a composição e preservando a gramática — não apenas escalando.

## Refinamento final no After Effects

Depois de executar o JSX:
- revisar a fonte Inter disponível na máquina;
- ajustar curvas de velocidade individualmente;
- calibrar motion blur;
- calibrar profundidade, luz e blur;
- conferir legibilidade em 100% e 50%;
- fazer color management e render final;
- revisar a peça inteira antes de publicar.

O objetivo do V2 é sair de uma animação “bonita” para uma peça com **sensação de produto real, profundidade e direção cinematográfica**.
