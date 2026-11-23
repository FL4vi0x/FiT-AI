# P8.2 — Prévia local do Modelo C (Honda Jazz 1.4 DSi) no HUD

**Prévia experimental, local e reversível.** Não é autorização de uso definitivo nem de redistribuição do asset.

## 1. Onde está o modelo
- Arquivo: `assets/honda-fit-gd/candidates_local/candidate_C1_jazz_gt6.glb` (1,2 MB; cópia idêntica em geometria: `candidate_C2_jazz_gt6.glb`). Os arquivos originais baixados pelo usuário (`honda_jazz_1.4_dsi_se_sport_01*.glb`) permanecem onde foram baixados, sem alteração.
- A pasta e o arquivo estão **fora do Git** (`.gitignore` raiz e o da pasta). Nada foi copiado para `public/`, `src/` ou qualquer pasta rastreada. O modelo A (CC BY) segue a mesma regra.
- A origem registrada pelo autor está preservada: o bloco `asset` do GLB é lido sem modificação (`LoadedVehicle.gltfAsset`) e o crédito aparece no selo de desenvolvimento e na dica do selo.

## 2. Situação conhecida da licença
- Modelo C: "Honda Jazz 1.4 DSi SE Sport '01", Asadawut.Kaewma (Sketchfab). O autor escreve **"Model From Gran Turismo 6"**. A página o rotula CC BY 4.0, mas ele é um ativo extraído de jogo (direitos da Polyphony Digital e da Honda): o rótulo **não garante** que o uploader possa licenciar. **Direitos não confirmados.**
- Modelo A: "2006 Honda Fit GD3", kusuma844, CC BY 4.0, autoria própria declarada. Exige atribuição.
- Honda é marca de terceiros; o projeto não tem vínculo com a Honda.
- Servir em localhost não é licença. As capturas desta prévia (`assets/honda-fit-gd/out/previews/`) mostram o asset, por isso também estão fora do Git e **não devem ser publicadas**.

## 3. Como iniciar a prévia local (Windows)
```
cd FiT-AI\ui
npm run dev                         # servidor de desenvolvimento em 127.0.0.1:5173 (a rota local só existe nele)
```
Abra:
- `http://127.0.0.1:5173/#/active?vehicle=model-c` → modelo C, holograma
- `…?vehicle=model-c&look=grey` (ou `look=original`) → cinza / materiais originais
- `…?vehicle=model-c&yaw=-35.5` → vista lateral (−71 = traseira 3/4)
- `…#/active?demo&vehicle=model-c` → painel de desenvolvimento: trocar modelo (provisório / A / C), aparência, restaurar câmera
- arrastar com o mouse sobre o carro gira o modelo (somente em desenvolvimento)

Pré-requisito: o arquivo `ui/.local/vehicle-models.json` (ignorado pelo Git) com o caminho de cada GLB local:
```json
{ "model-c": "C:/.../candidates_local/candidate_C1_jazz_gt6.glb", "model-a": "C:/.../candidate_A_2006_honda_fit_gd3.glb" }
```
Sem esse arquivo (ou sem o modelo), a tela continua funcionando com o carro procedural e o selo diz "MODELO LOCAL AUSENTE". Para ver "Sistema Conectado" suba o Core (`scripts\start-stack.ps1`).

### Modelo C como carro padrão desta máquina (decisão do usuário, 2026-11-22)
O usuário decidiu seguir com o modelo C. Nesta máquina, `npm run dev` abre a tela ativa **já com o carro C**, sem `?vehicle=`. O mecanismo é o arquivo local, ignorado pelo Git, `ui/.env.development.local`:
```
VITE_FIT_DEFAULT_VEHICLE=model-c
```
- O Vite lê esse arquivo só no servidor de desenvolvimento: builds, `vite preview` e testes **nunca** o veem, então o padrão do código continua sendo o carro procedural.
- Voltar atrás é reversível: apagar o arquivo, ou abrir `#/active?vehicle=placeholder`.
- Se o `.glb` ou a config local faltarem, a tela mostra o carro procedural e o selo "MODELO LOCAL AUSENTE".
- Isso **não** muda a situação jurídica: o C continua sem direitos confirmados, só roda localmente (localhost) e não entra no Git, em build publicado ou em screenshot público. Quem usa assume essa responsabilidade; qualquer publicação exige autorização do titular ou troca do modelo.

## 4. Arquitetura do carregamento
- `vite.local-assets.mjs`: middleware **só do servidor de desenvolvimento** (`apply: 'serve'`; não existe em `vite build` nem em `vite preview`). Atende `GET/HEAD /__local_vehicle/<id>.glb` apenas para soquetes de loopback com `Host` de loopback (sem LAN, sem DNS rebinding), apenas para ids presentes na configuração local, **nunca** montando caminho a partir da URL, sempre `Cache-Control: no-store`.
- `three/vehicleAssets.ts`: tipos e leitura do registro; `three/vehicleAssets.local.ts`: o registro dos modelos A e C (nomes, créditos, papéis das peças). **O segundo módulo só é importado atrás de `import.meta.env.DEV`**; em produção ele não entra no pacote (verificado: nenhuma string "Gran Turismo", rota local ou `.glb` no `dist`).
- `three/vehicleModel.ts`: `GLTFLoader` (import dinâmico), `normalizeModel` (nariz para +X, **uma única escala uniforme** até 3,83 m, centraliza e apoia no piso: eixos nunca esticados), variantes de aparência por peça (holograma, cinza, original), linhas âmbar só nos vincos reais (`EdgesGeometry` por ângulo e por papel da peça: carroceria 32°, vidros 40°…), cache de arestas compartilhado com o reflexo.
- `three/VehicleScene.ts`: troca o carro procedural pelo modelo (liberando os recursos do procedural), `setAppearance`, `resetView`, arrasto (dev), medições no `dataset` do canvas (dev).
- `components/active/VehicleStage.tsx` + `DevVehiclePanel.tsx` (lazy, só em desenvolvimento): seletor, selo de direitos e painel. Em produção o carro é sempre o procedural e nada é requisitado.
- O arquivo original nunca é alterado: os materiais do GLB ficam nas malhas; holograma e cinza são instâncias separadas. Voltar ao original é trocar a aparência.

## 5. Materiais holográficos
Fundo `#030304`, âmbar `#FF8500`, âmbar luminoso `#FFAA38`, sombra da carroceria `#130A04`. Por peça: carroceria escura e translúcida com luz âmbar de borda (fresnel); vidros mais escuros; pneus quase pretos; centros de roda e detalhes com mais brilho; linhas âmbar só nos vincos (nada de malha total); reflexo no piso com a mesma geometria, opacidade baixa. A altura do "scan de revelação" usa a altura do mundo, então vale para qualquer modelo.

## 6. Capturas (navegador real, Edge headless, WebGL por software)
`assets/honda-fit-gd/out/previews/` (fora do Git): `model-c-active-front34.png`, `-side.png`, `-rear34.png`, `-hologram.png`, `-grey.png`; as mesmas para o A (`model-a-active-*`); `model-c-active-{1920x1080,1366x768,1280x720,1024x600}.png`; `compare-A-vs-C-active.png`. Capturas de comparação usam movimento reduzido (quadro parado, mesma câmera, enquadramento, luz, material e resolução).

## 7. Comparação A × C (mesma interface)
| Aspecto | A (GD3, CC BY) | C (Jazz GT6) |
|---|---|---|
| Fidelidade ao Fit GD | reconhecível; cabine e frente simples | mais fiel: recortes de porta, maçanetas, tampa do tanque, colunas A/B/C |
| Faróis | em bloco único | peças separadas, formato em gota |
| Grade dianteira | barra fina com H pequeno | grade com H em relevo |
| Portas e janelas | janelas definidas, poucas divisões | vincos de porta bem marcados |
| Lanternas traseiras | integradas à traseira | altas, em peças separadas |
| Holograma | lê-se quase como carro **sólido laranja** (uma malha de carroceria com 70 mil triângulos, interior e sub-estrutura visíveis como superfícies) | **escuro com contornos âmbar**, mais próximo da referência |
| Cinza (forma) | completo, mas com painéis de face única (por isso o cinza usa face dupla) | completo |
Ambos têm rodas de liga em vez das calotas do LX brasileiro. No C a antena toca visualmente o anel do núcleo; o interior aparece através do vidro (é o que o modelo contém).

## 8. Métricas reais (Edge headless, rasterização por software: pessimista)
| | Modelo C | Modelo A | Procedural |
|---|---|---|---|
| Arquivo | 1,2 MB | 3,1 MB | — |
| Triângulos no arquivo / malhas | 25.920 / 33 | 117.801 / 5 | — |
| Chamadas de desenho por quadro | 132 | 20 | 122 |
| Triângulos desenhados (carro + reflexo) | 51.840 | 235.602 | 3.584 |
| Geometrias na GPU | 66 | 10 | 54 |
| Texturas na GPU | 0 | 0 | 0 |
| Carga (parse do GLB, local) | ~110 ms | ~55 ms | — |
| Página até o modelo na tela | ~2,7 s | ~1,7 s | — |
| rAF/s em 1920×1080 | 59 | 60 | 59 |
| Thread principal ocupada | 44% | 32–35% | 42–47% |
| Heap JS | 17 MB | 11 MB | 11 MB |
Essas medidas variam entre execuções em alguns pontos percentuais. "rAF/s" é a cadência do requestAnimationFrame no headless, **não** um FPS de tela; o consumo de GPU não é mensurável aqui (renderização por software). Nenhuma geometria foi reduzida para melhorar esses números.

## 9. Testes
- Vitest: **161 passando** (eram 130): registro de modelos e papéis, `normalizeModel` (escala uniforme, orientação, centro, piso), aparências reversíveis e linhas só em vincos, cache de arestas, `loadVehicleGlb` (carga e falha), rota local (recusa não-loopback, Host falso, ids estranhos, config ausente ou quebrada, arquivo não-GLB), troca do carro procedural pelo modelo com liberação de recursos, arrasto e reset, modelo ausente.
- Navegador (`e2e/model-preview.mjs`, todas passando): rota local só em loopback e recusando Host falso e id suspeito; modelos C e A carregam na tela real e entram em uma caixa de carro (3,83 m, escala uniforme); todas as requisições de rede ficam em loopback; troca A ⇄ C ⇄ provisório sem vazamento de geometrias na GPU (contagens 66 → 10 → 66 → 10 → 66); aparência cinza e volta ao holograma; arrasto e restaurar câmera; **modelo ausente**: o provisório permanece e o selo avisa; 1920×1080, 1366×768, 1280×720 e 1024×600 sem overflow nem erros de console; rotação lenta, pausa com a aba oculta, reduced motion sem rotação.
- Falha de WebGL: coberta nos testes unitários (aviso acessível, HUD intacto).
- Regressão: e2e da tela ativa em produção (`e2e/active.mjs`), da Standby e do HUD antigo (14/14) passam. O backend não foi tocado.

## 10. Limitações e pendências jurídicas
1. **Direitos do modelo C não confirmados** (extraído de Gran Turismo 6). Uso só local e para avaliação; não versionar, não publicar, não incluir em build ou em screenshot público. Antes de qualquer uso definitivo é preciso autorização do titular ou outro modelo.
2. Esta prévia não é decisão de produto. O modelo A tem licença CC BY (atribuição obrigatória: ver seção 2), mas com menos detalhe e holograma "mais sólido".
3. Não foi medido consumo de GPU nem FPS de tela real.
4. As rodas são de liga, não calotas do LX; a antena e o interior aparecem.
5. Nomes de componentes para integração futura (`Body`, `Headlights`, âncoras de motor etc.) ainda não existem: o modelo vem separado por material, não por peça funcional.

## 11. Refinamento visual do holograma (hierarquia exterior × interior)
**Problema:** na frente, o corpo todo com a mesma transparência deixava bancos, painel, interior das portas e piso do compartimento do motor competindo com a silhueta.

**O que foi feito (só material, renderização, câmera e luz; o modelo C e seus arquivos não foram alterados):**
- **Exterior × interior sem mexer na malha:** uma passada de visibilidade na GPU (`three/visibility.ts`) renderiza o modelo de 25 pontos de vista (ao redor, em 3 alturas, e por cima; nunca por baixo), cada triângulo pintado com seu id. Um triângulo é "exterior" se uma fração real da sua área aparece (≥ 40%); o que só aparece por frestas (grade, arco de roda) fica "interior". Resultado nas duas cascas grandes (carroceria e acabamentos pretos): **8.828 triângulos exteriores e 4.817 interiores**; a passada custa ~150–360 ms uma vez, ao carregar (em software). A divisão é uma **cópia reordenada do índice** em dois grupos que compartilham os buffers originais (`splitByMask`): o índice do arquivo continua intacto.
- **Camadas:** A) carroceria exterior: luz âmbar de borda nítida (fresnel de potência 2,8: superfícies planas ficam escuras e só a silhueta acende), opacidade moderada; B) interior: fantasma (opacidade 0,035, quase sem brilho, sem linhas); C) linhas âmbar só nos vincos reais que tocam triângulos exteriores (`exteriorEdges`, sem linhas artificiais no corte da máscara); D) detalhes (faróis, lanternas, placas etc.) com mais brilho e linhas mais fortes; vidros, pneus e acabamentos mais discretos.
- **Profundidade:** o lado do carro mais distante da câmera recua (esmaece até 30% por distância de vista) e a névoa escurece as linhas distantes, então o lado próximo lê primeiro.
- **Normais suaves** do arquivo para o brilho de borda (esconde as facetas dos painéis grandes).
- **Câmera:** a antiga era uma lente de 22° a 8,4 m (achatava o nariz). Testadas `legacy`, `refined`, `high` e `wide` (`model-c-refined-camera-tests.png`). **Escolhida `refined`**: 30°, a 6,9 m e um pouco mais alta, vista base 3/4 a ~38° do eixo do nariz (antes 54°, lateral demais). Ficou melhor porque a frente ganha profundidade, o carro preenche a plataforma e a antena deixa de tocar o anel principal do núcleo (resolvido por composição, sem deformar o modelo). A `high` mostra mais o capô, mas empurra o carro para cima, em direção ao núcleo.
- Rotação ambiental, pausa em segundo plano e reduced motion preservados. HUD, anéis, waveforms e plataforma não foram alterados.

**Arquivos:** `three/visibility.ts` (novo), `three/cameraPresets.ts` (novo), `three/hologram.ts`, `three/vehicleModel.ts`, `three/VehicleScene.ts`, `dev/devPreview.ts` (`cam=`, `view=`, `look=split`), componentes do palco, testes e `e2e/refine-shots.mjs`.
**Diagnóstico de desenvolvimento:** `#/active?vehicle=model-c&look=split` pinta exterior em verde e interior em vermelho.
**Capturas (fora do Git):** `assets/honda-fit-gd/out/previews/model-c-refined-{front34,front,side}.png`, `model-c-before-*.png`, `model-c-refined-compare-before-after.png`, `model-c-split-*.png`, `model-c-refined-camera-tests.png`.

**O que ainda não está perfeito:** o interior não some, fica fantasma (bancos e volante ainda se adivinham pelo para-brisa); a roda dianteira vista quase de frente aparece como dois anéis concêntricos (pneu e aro); a antena ainda se projeta para cima, perto dos anéis finos do núcleo; faróis em facetas (baixa resolução do arquivo). A classificação é geométrica e heurística (fração de área vista), não um dado do arquivo.

## 12. Sem o modelo C, e como usar um modelo 3D local autorizado
**Sem o modelo C (o caso de quem clona o repositório).** Nada depende dele. A tela ativa mostra o carro procedural, com a legenda "MODELO PROVISÓRIO · não é o Honda Fit GD" em desenvolvimento. Um build de produção (`npm run build`) nunca contém, requisita ou lê um modelo local: a rota `/__local_vehicle/` só existe no servidor de desenvolvimento e o registro dos modelos (`three/vehicleAssets.local.ts`) só é importado atrás de `import.meta.env.DEV`. Se o arquivo local faltar, a tela cai no carro procedural e o selo diz "MODELO LOCAL AUSENTE".

**Para usar um modelo 3D local que você tenha direito de usar:**
1. Guarde o `.glb` fora de qualquer pasta versionada (por exemplo `assets/honda-fit-gd/candidates_local/`, já ignorada; `*.glb` e `*.fbx` são ignorados em todo o repositório).
2. Crie `ui/.local/vehicle-models.json` (ignorado) com o caminho de cada arquivo, por id: `{ "model-c": "C:/.../meu_modelo.glb" }`. Os ids aceitos são `model-a` e `model-c`.
3. Descreva o modelo em `ui/src/three/vehicleAssets.local.ts`: `frontAxis` (eixo do arquivo, em espaço glTF Y para cima, para onde aponta o nariz: `+x`, `-x`, `+z` ou `-z`), `roles` (nome do material para papel da peça: `body`, `trim`, `glass`, `tyre`, `rim`; o resto é `detail`), crédito e situação de direitos. Para descobrir os materiais e a orientação, rode `blender --background --python assets/honda-fit-gd/scripts/inspect_candidate.py -- arquivo.glb`.
4. Para abri-lo por padrão nesta máquina, crie `ui/.env.development.local` (ignorado) com `VITE_FIT_DEFAULT_VEHICLE=<id>`; ou use `#/active?vehicle=<id>` na URL. Reinicie o `npm run dev` depois de mudar a configuração.
5. Confira as atribuições e licenças exigidas pelo modelo antes de qualquer uso além da sua máquina. Servir em localhost não é licença.

A escala é sempre uniforme até 3,83 m (comprimento do manual); a orientação, o centro e o piso são normalizados no Three.js; o arquivo nunca é alterado.
