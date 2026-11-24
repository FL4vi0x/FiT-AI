# Fit AI · HoloDrive (interface)

Interface gráfica do Fit AI: um HUD laranja/âmbar em volta de um desenho técnico do Honda Fit 2005. Ela só **consome** a API
existente do Core (`GET /health`, `GET /api/v1/vehicle/status`, `GET /api/v1/vehicle/telemetry`, `POST /api/v1/chat`); nenhum
contrato foi criado ou alterado. Documentação completa: [`docs/poc-03-p8-ui.md`](../docs/poc-03-p8-ui.md).

Stack: React 19 · TypeScript (estrito) · Tailwind CSS 3 · Framer Motion 11 · Vite 6 · Vitest. Sem fontes nem recursos de rede
externos (a central multimídia pode estar offline).

## Rodar (Windows, PowerShell)

Pré-requisitos já usados pelo projeto: Node 20+ (testado com 24), o `.venv` do Core e a pasta `..\runtime` (OCTAVE, Ollama).

```powershell
cd FiT-AI\ui
npm install                                   # uma vez (scripts de dependências desativados em .npmrc; versões exatas)

# 1) a stack local (loopback): OCTAVE em simulação + Core com a origem da UI liberada (+ Ollama para o chat)
powershell -NoProfile -File scripts\start-stack.ps1 -WithLlm

# 2) a interface
npm run dev                                   # http://127.0.0.1:5173  (Standby; o HUD fica em /#/hud)

# ao terminar
powershell -NoProfile -File scripts\stop-stack.ps1
```

`start-stack.ps1` recusa subir se uma porta (8000, 9876, 11434) já estiver em uso, registra o que iniciou em `.stack.json` e o
`stop-stack.ps1` encerra **somente** isso. Sem `-WithLlm` o Ollama não sobe: telemetria e varredura funcionam, o chat responde
com erro de modelo indisponível.

### Por que o Core precisa de `FIT_AI_CHAT_ALLOWED_ORIGINS`

O navegador chama a UI em `127.0.0.1:5173`, e o servidor de desenvolvimento repassa `/api` e `/health` ao Core (mesma origem: o
Core não emite CORS, de propósito). O `POST /api/v1/chat` leva o cabeçalho `Origin: http://127.0.0.1:5173`, e o Core só aceita
origens da lista `FIT_AI_CHAT_ALLOWED_ORIGINS` (a guarda contra páginas maliciosas). O script já faz isso. Se você subir o Core
à mão, use:

```powershell
$env:FIT_AI_CHAT_ALLOWED_ORIGINS = 'http://127.0.0.1:5173,http://127.0.0.1:4173'
.\.venv\Scripts\python.exe -B -m fit_ai
```

Sem isso, a UI mostra o erro `origin_not_allowed` com essa instrução (a GET continua funcionando).

## Scripts

| Comando | O que faz |
|---|---|
| `npm run dev` | servidor de desenvolvimento em `127.0.0.1:5173` (proxy para o Core em `127.0.0.1:8000`) |
| `npm run build` | `tsc --noEmit` + build de produção em `dist/` (com CSP restrita) |
| `npm run preview` | serve o build em `127.0.0.1:4173` |
| `npm run typecheck` | TypeScript estrito |
| `npm test` | testes de API, estado, componentes, voz (áudio, captura, máquina de estados) e App com API falsa |
| `npm run e2e` | roteiro no **Edge headless** contra o build e um Core simulado (14 passos; capturas em `e2e/out/`) |
| `npm run e2e:real` | o build contra a **stack real** (OCTAVE + Core + Ollama; `-- --no-llm` pula o chat) |
| `node e2e/perf.mjs` | custo de renderização por estado |

`FIT_AI_CORE_URL` (padrão `http://127.0.0.1:8000`) muda o destino do proxy; só endereços de loopback são aceitos.

## Voz (P9.1): push-to-talk local

Na tela Active, o **núcleo circular** é o controle de voz: segure (mouse, toque, Espaço ou Enter), fale e solte; um toque rápido inicia e o próximo toque para; Esc cancela.
O microfone só abre por esse gesto, é liberado ao soltar e nunca é usado no Standby. O áudio vai só ao Core local (`/api/v1/voice/transcribe`) e o texto reconhecido aparece
apenas no modo de desenvolvimento (`npm run dev`); ele **não** é enviado ao chat. Precisa do motor e do modelo locais: veja `../docs/poc-09-01-local-stt.md`.
Teste com navegador (dispositivo de captura **falso**, voz sintética): `FIT_E2E_SPEECH_WAV=<wav> node e2e/voice.mjs`.

## Estrutura

```
ui/
  src/
    api/         types.ts (contrato espelhado do backend) · client.ts (fetch com timeout, erros normalizados)
    state/       store.ts (reducer + modo visual derivado, puros) · useFitAi.ts (orquestra as chamadas) · useNow.ts
    lib/         vehicleZones.ts (geometria do palco) · labels.ts (origens, ferramentas, erros) · format.ts
    components/  os 14 componentes do HUD + SystemCallout e VehicleStage
    App.tsx · main.tsx · index.css (tokens e animações)
  e2e/           mock-core.mjs · run.mjs · real.mjs · perf.mjs
  scripts/       start-stack.ps1 · stop-stack.ps1
```

## Carro 3D da tela ativa
Por padrão, e em qualquer build de produção, a tela ativa (`#/active`) usa um carro **procedural provisório** (não é um Honda Fit GD). Em desenvolvimento é possível pré-visualizar um modelo 3D local que você tenha direito de usar; ele fica fora do Git. Como configurar, os limites jurídicos e as variantes de URL (`?vehicle=`, `look=`, `view=`, `cam=`, `?demo`): `docs/poc-08-02-model-c-preview.md`, seções 3 e 12.

