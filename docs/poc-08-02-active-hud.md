# P8.2 — Tela 02: Active Holographic Vehicle Interface

**Status: PARCIAL.** Toda a interface está implementada e testada, mas o veículo é um **modelo provisório** (procedural), não um Honda Fit GD 2005. Pelo critério de aceite do brief ("sem modelo 3D licenciado e fiel, a entrega é parcial"), a tela **não** pode ser considerada visualmente aprovada até que um modelo licenciado e fiel seja fornecido.

Referência: `Imagem do ChatGPT 22 de nov. de 2026, 14_58_22.png` (1672 × 941, fora do repositório).

## 1. Arquitetura
```
Root.tsx                    #/ → Standby · #/active → direto na tela ativa · #/hud → protótipo HoloDrive · ?demo → painel de demonstração (só DEV)
screens/Experience.tsx      orquestra Standby → Active (as duas montadas durante a transição)
screens/ActiveScreen/       tela ativa (2D: SVG + CSS + Motion) + CSS module
components/active/          ActiveHeader, AICore, AmbientRings, VehiclePlatform, VoiceWaveform, Bars, HondaMark,
                            VehicleStage (lazy + fallbacks), HolographicVehicle (canvas, ciclo de vida)
three/                      VehicleScene (renderer, loop, dispose), hologram (shaders/materiais), fitPlaceholder (geometria provisória)
motion/                     activeTimeline.ts, activeVariants.ts (+ timings/variants da P8.1)
state/                      visualState.ts (máquina de estados), useServiceStatus.ts (checagens reais)
```
Separação: UI 2D (SVG/CSS), cena 3D (`three/`, sem React), estado visual, dados do backend e motion são módulos distintos. O palco usa o mesmo espaço de coordenadas da referência (1672 × 941), como a Standby. O **header** fica fora do palco escalado (largura real da janela, fontes em px com `clamp`), para continuar legível em 1024 × 600.

### Three.js: decisão
Só `three@0.170.0` (+ `@types/three@0.170.0`, dev), versões exatas, lockfile, `npm audit` = 0. **Não usei React Three Fiber nem Drei**: o 3D é uma única cena sem eventos, então um wrapper de ~60 linhas com ciclo de vida explícito (`VehicleScene.dispose()`) evita duas dependências e dá controle direto de pausa, perda de contexto e liberação de recursos. O módulo 3D é carregado com `React.lazy` (chunk separado, só a tela ativa o puxa). Header, ícones, textos, anéis, core e waveform são SVG/CSS e não dependem de WebGL.

## 2. Modelo Honda Fit — pesquisa e licença
Busca feita em 2026-11-22 por modelos do Honda Fit/Jazz GD (2005) com licença que permita uso e redistribuição:
- Sketchfab: nenhum Fit/Jazz GD com licença Creative Commons encontrado (os CC achados eram Honda e Interior e Honda T360).
- 3D Warehouse (Jazz/Fit de 2006): sem licença informada.
- 3DCadBrowser, TurboSquid, CGTrader, RenderHub, 3DExport: modelos pagos ou "Royalty-Free" **sem** redistribuição dos arquivos-fonte; os da geração GD que apareceram são de 2002/2004, ou os modelos são de outras gerações (2014, 2017, 2018).

**Nada foi baixado e nenhum modelo de terceiros foi incorporado.** Bloqueio: não existe, nas fontes pesquisadas, um modelo do Fit GD 2005 com licença verificável. A busca foi superficial (resultados de busca, sem abrir cada página); pode haver modelos que ela não achou.

### O que foi implementado no lugar
`three/fitPlaceholder.ts`: carroceria procedural (loft de seções transversais sobre um perfil lateral feito à mão), com proporções aproximadas de um Fit (3,9 m × 1,68 m × 1,54 m, entre-eixos 2,45 m): capô curto, para-brisa inclinado, teto alto, traseira quase vertical, linhas de cintura, **quatro portas laterais** (cortes) mais traseira, faróis, lanternas, grade, retrovisores, quatro rodas. O `PLACEHOLDER_ID` é `procedural-placeholder-not-honda-fit-gd`, o canvas expõe `data-model` com esse valor e, em desenvolvimento, aparece o aviso "MODELO PROVISÓRIO · não é o Honda Fit GD".

**Fidelidade realmente alcançada:** reconhece-se um monovolume compacto holográfico; **não** se reconhece um Honda Fit GD (faróis, para-choques, vincos e proporções finas não são reproduzidos). Não há malha detalhada de capô/motor como na referência.

### Como encaixar o modelo licenciado
`VITE_FIT_MODEL_URL=/models/fit-gd.glb` (arquivo fora do Git até que a licença permita). `VehicleScene` tenta carregar o GLB (`GLTFLoader` por import dinâmico; só baixa quando a variável existe); hoje, mesmo com GLB carregado, a conversão para o material holográfico **não está implementada** e a cena reporta `model-missing` e mantém o provisório. Falta: converter materiais, gerar contornos, escalar/centralizar.

## 3. Material holográfico (`three/hologram.ts`)
`ShaderMaterial` único para o corpo: vidro escuro quase transparente, rim âmbar por fresnel (normal por derivadas de tela, estável em malha loftada), faixa de varredura sutil e recorte por altura (`uReveal`) para o carro ser "escaneado" de baixo para cima. Contornos em `LineBasicMaterial` âmbar (linhas longitudinais escolhidas + anéis de seção + detalhes), **sem** wireframe denso de todas as faces. Reflexo no piso: segundo grupo espelhado (`scale.y = -1`) com opacidade baixa. Sem pós-processamento, sem texturas.

## 4. Movimento e linha do tempo (a partir da ativação, ms)
| Fase | Janela | O que acontece |
|---|---|---|
| 1 Ativação | 0–500 | luz âmbar sobe; core começa a se formar (100–1000) |
| 2 Contração | 500–1200 | a identidade da Standby encolhe (escala uniforme 1 → .6, nunca deformada) e some; os anéis aparecem (500–1400) |
| 3 Veículo | 1000–2400 | carro escaneado de baixo para cima (reveal 1,4 s); plataforma acende (900–1900) |
| 4 Header | 1800–2700 | entrada com fade + 14 px |
| 5 Ativo | 2500–3200 | waveform; estado `active` aos 3200 |

Easing `[0.22, 1, 0.36, 1]`, só opacidade/transform; sem flash. Rotação ambiental: oscilação de ±11,5° com período de 50 s em torno da vista três-quartos (velocidade máxima < 0,1 rad/s, verificada em teste). Pausa com a aba oculta (`visibilitychange`). **Reduced motion:** estado final imediato, 0 animações CSS em execução, cena renderizada uma vez, sem loop e sem rotação. O gatilho da ativação é o usuário (botão invisível de tela cheia com `aria-label="Ativar o Fit AI"`, teclado e ponteiro); nada ativa sozinho.

## 5. Estados visuais (`state/visualState.ts`)
`FitAIVisualState = standby | activating | active | listening | processing | responding | unavailable`.
- `listening`, `processing`, `responding` têm representação pronta (velocidade/amplitude das barras e giro do anel do core por `data-state`), mas **nada no produto entra nesses estados**: só o painel de demonstração (`#/active?demo`, apenas em build de desenvolvimento).
- `unavailable` é derivado de um fato real: Core fora do ar (tela escurecida e barras achatadas).
- Uma segunda ativação durante `activating` é ignorada (a sequência não reinicia); timers são limpos no unmount.

## 6. Backend
Reutiliza só `GET /health` e `GET /api/v1/vehicle/status`, a cada 10 s, com a aba visível, **apenas depois que a tela ativa está em cena** (Standby = zero requisições). Nunca chama `/chat` nem lê telemetria. Mesma origem pelo proxy do Vite (inalterado): não enfraquece CORS nem o BrowserGuard; backend não foi modificado.
- **OCTAVE** (chip): `Conectado` / `Sem veículo` / `Indisponível` / `Sem Core` / `Verificando`, conforme `/vehicle/status`.
- **Ollama** (chip): `Não verificado`. O Core não expõe endpoint com o estado do Ollama, então a UI não tem como saber; por isso nunca aparece como online. Para ter esse indicador real é preciso um endpoint novo no backend (fora do escopo).
- Sistema: "Sistema Conectado" só com Core e OCTAVE conectados; "Sistema parcial"; "Sistema desconectado".
- Nenhum valor de sensor é exibido. O OCTAVE segue fornecendo só telemetria simulada; `simulated` é lido, mas ainda não exibido.

## 7. Header
Fiel à composição da referência: marca + FIT AI + subtítulo + "Honda Fit GD (2005)" + estado; navegação central (Home selecionada com luz laranja; Telemetria, Manutenção, Histórico e Configurações **desabilitadas** e com "em breve" para leitores de tela: essas páginas não existem); chips de serviço e relógio à direita (hora e data reais). Em ≤1280 px some o bloco do veículo; em ≤1100 px some o subtítulo.

## 8. Testes
- **Unitários (Vitest/RTL): 130, todos passando** (92 anteriores + 38 novos): header, navegação sem falsa navegação, chips honestos, ActiveScreen voice-first (sem campo de texto/chat/telemetria), estados, fallback sem WebGL, máquina de estados (fases, reduced, interrupção, cleanup), `useServiceStatus` (desabilitado, conectado, Core fora, OCTAVE fora), Experience (sem requisição na Standby, só os dois GETs, sem chat/telemetria), roteamento, geometria provisória, `VehicleScene` com renderer simulado (primeiro frame, rotação lenta e limitada, reduced, pausa/retomada, perda/restauração de contexto, dispose idempotente de renderer/contexto/geometrias/materiais, modelo ausente). As mensagens "Not implemented: HTMLCanvasElement.getContext" no log são do jsdom nos testes do caminho sem WebGL, não falhas.
- **Navegador real (`e2e/active.mjs`, Edge headless com WebGL por software): todos passando:** 1920×1080, 1600×900, 1366×768, 1280×720, 1024×600 (estado ativo, sem overflow, sem erros de console, só as duas requisições de leitura, carro WebGL renderizado, header sem corte); rotação lenta; pausa com aba oculta e retomada; Standby → Active quadro a quadro (sem chat/telemetria); reduced motion; Core offline ("Sem Core", nunca "Conectado"); redimensionamento.
- `e2e/standby.mjs` (31 verificações) e e2e do HUD (14/14) continuam passando. `npm audit`: 0.
- **Não testado:** dispositivo real com GPU, tela automotiva, perda de contexto WebGL em navegador real (só unitário), carga de um GLB real.

## 9. Desempenho (Edge headless, **rasterização por software**: pessimista)
- Bundle: JS principal 396,0 kB (127,7 kB gzip); chunk 3D carregado sob demanda 531,2 kB (136,5 kB gzip); `GLTFLoader` 46,1 kB (13,7 kB gzip) só baixa se `VITE_FIT_MODEL_URL` existir. CSS 25,8 kB (6,8 kB gzip).
- Idle em 1920×1080 com a cena ativa: thread principal ocupada ~27–37 % (duas medições, 6 s cada), 60 rAF/s (cadência do requestAnimationFrame no headless, **não** FPS de tela), heap JS ~6 MB. Sem GPU esses números não representam uma máquina real; não há afirmação de 60 fps em hardware.
- Mitigações: pixel ratio ≤ 1,5; sem pós-processamento; reflexo = mesma geometria; loop suspenso com aba oculta e em reduced motion; dispose completo; waveform e giros em CSS (transform/opacity).

## 9b. Revisão visual independente (agente de QA)
Um agente de QA, sem alterar arquivos, comparou a referência com as capturas. Conclusões, sem nota de similaridade:
- **O carro não se lê como Honda Fit**, e sim como uma perua/monovolume genérica e quadrada (sem grade, faróis, retrovisor e teto afunilado; faixas verticais de ruído no teto e nas laterais; fios soltos na frente; roda traseira quase escondida). É o bloqueio já registrado.
- Piso: a referência tem chão preto brilhante com faixas verticais laranja/azuladas e reflexos fortes; a implementação tem só o espelho fraco do carro.
- Plataforma: o anel da referência é mais fino, mais brilhante e com bloom/ticks.
- Core: a referência usa onda fina de linha e flares horizontais; a implementação usa barras cheias.
- Fundo: a referência tem túnel desfocado com bokeh; a implementação tem arcos nítidos sobre preto.
- Header: a referência tem moldura trapezoidal inclinada e emblema com brilho laranja; a implementação tem barra reta e emblema cromado cinza.
- Em 1024 × 600 os rótulos da navegação ficam com ~10 px (difíceis de ler); em 1366 e 1920 o topo do anel do core encosta na linha do header.
- A transição foi considerada gradual e limpa (sem flash, salto ou elemento solto); o reduced motion bate com o estado final.
Nenhum desses pontos foi corrigido nesta etapa além do que já consta acima.

## 10. Screenshots
`ui/e2e/out/active/` (ignorado pelo Git): `active-*`, `transition-*` (a latência do screenshot é de centenas de ms, então os rótulos subestimam o tempo real), `reduced-*`, `offline-*`, `resized-*`.

## 11. Como rodar (Windows)
```
cd FiT-AI\ui
npm run dev                        # http://127.0.0.1:5173  (Standby; clique ou Enter/Espaço ativa)
                                   # http://127.0.0.1:5173/#/active        direto na tela ativa
                                   # http://127.0.0.1:5173/#/active?demo   + painel de estados (só dev)
npm test
npm run build; node e2e/active.mjs  # precisa do Edge instalado
```
Para ver "Sistema Conectado" é preciso o Core em 127.0.0.1:8000 (`scripts\start-stack.ps1`); sem ele a tela mostra, corretamente, "Sistema desconectado".

## 12. Limitações
1. **Modelo do carro provisório (bloqueio principal).** Não é um Honda Fit GD.
2. Fidelidade visual à referência é parcial: o carro é bem mais simples (sem capô aberto/motor, sem rodas e faróis reais), o piso não tem os reflexos azulados da imagem, o core tem barras em vez da onda fina da referência. Comparação feita a olho, sem métrica.
3. Ollama não verificável (falta endpoint no Core).
4. Telemetria não exibida; `listening/processing/responding` só pelo demo.
5. Sem voz, microfone, STT/TTS ou wake word (por instrução).
6. Emblema Honda: ver a seção "Marca e licenciamento" de `docs/poc-08-01-standby-screen.md`.
7. Headers pequenos em 1024 × 600: os rótulos de navegação ficam com ~10 px.

## 13. Preparação para voz e consultas contextuais
`FitAIVisualState` já tem `listening/processing/responding`; um futuro serviço de voz só precisa chamar `demoSet`-equivalente (uma função de transição de produção) e a tela reage. O core e o waveform são independentes do carro 3D. A navegação desabilitada e o foco no veículo (motor, rodas, arrefecimento) dependem do modelo licenciado, que traria zonas nomeadas.
