# P9.1 — Reconhecimento de voz local (STT) com push-to-talk

Estado: **implementado, validado tecnicamente e aprovado no teste prático do usuário com a própria voz (2026-11-23).** Portão 3 funcionalmente aprovado.
Essa aprovação é uma **validação humana qualitativa de um único falante, não um benchmark estatístico de precisão** (ver §10). Ainda não versionado: nada é commitado ou publicado sem autorização.
Escopo: ouvir e transcrever, em português do Brasil, sem internet. **Não** há TTS, wake word, escuta contínua nem envio ao chat.
Pendência de licenciamento antes de qualquer distribuição: o wheel do PyAV embute FFmpeg com componentes GPL (ver §12).

## 1. Resumo

Na tela Active, o núcleo circular é o controle de push-to-talk. O usuário segura (mouse, toque, Espaço ou Enter), fala e solta. O navegador
captura o áudio, converte para 16 kHz mono PCM 16-bit, envia ao Core local (`POST /api/v1/voice/transcribe`) e o Core transcreve em memória
com o **faster-whisper `small`** (CPU, int8). O texto fica disponível para a interface (visível só em build de desenvolvimento) e **não** é
enviado a lugar nenhum: nem ao `/api/v1/chat`, nem ao Ollama.

## 2. ADR — escolha do motor

**Decisão:** faster-whisper 1.2.1 (CTranslate2 4.9.1), modelo `Systran/faster-whisper-small` (multilíngue), int8, CPU.

**Alternativa avaliada:** whisper.cpp b5907 (binário oficial Windows), modelo `ggml-small.bin`. Mesma família de pesos (Whisper `small`).

Medido nesta máquina (i5-1235U, 10 núcleos, 31,7 GB, sem GPU dedicada, Windows 11), 8 threads, beam 5, **áudio sintético** (voz Microsoft Maria):

| | faster-whisper | whisper.cpp (CPU) |
|---|---|---|
| Carga do modelo | 1,5 s | 1,1 s |
| Latência, fala de 3 / 5 / 10 s | 2,5 / 2,6 / 2,8 s | 5,2 / 5,5 / 5,9 s |
| RAM após carga (USS) / pico | 340 MB / 1,0 GB | 574 MB / 780 MB |
| WER (sintético, limpo) | 7,1 % | 5,9 % |
| Texto inventado em silêncio e ruído | nenhum | `[Música]`, `[Som de futebol]` |
| Instalação | pacote Python com wheels para Python 3.14 | binário zip; **trava com caminho de modelo não-ASCII** (ex.: pasta de usuário com acento) |

Razões: cerca de 2x mais rápido nesta CPU; menos RAM; não inventa texto em silêncio (relevante para push-to-talk); é uma biblioteca no
processo do Core, sem processo filho nem restrição de caminho. A diferença de precisão (1–2 palavras num conjunto sintético pequeno) **não é
significativa**. Variante whisper.cpp+BLAS: o resultado registrado foi medido com a CPU já ocupada (99 % antes de iniciar) e **não é comparável**.

**Não medido:** rodada com o Ollama carregado (cancelada pelo usuário); `large-v3-turbo` (não baixado, por instrução); precisão estatística com voz humana
(existe apenas a validação qualitativa do §10).

Dica de vocabulário (`initial_prompt`): com "Fit AI, Honda Fit, RPM, arrefecimento, velocidade, temperatura do motor." o faster-whisper acertou
"Honda Fit" em 5 de 5 clipes sintéticos (sem a dica: "onda fit"). **O prompt contém as palavras do teste**, então o ganho medido é otimista. O teste humano
do §10 foi feito com a configuração padrão (dica ligada); **não houve comparação com e sem a dica com voz humana**. Desligue com `FIT_AI_STT_INITIAL_PROMPT=` (vazio).

## 3. Arquitetura

```
 UI (React)                                         Core (FastAPI, só loopback)
 ┌───────────────────────────┐   POST audio/wav     ┌──────────────────────────────────────────────┐
 │ VoiceControl (o núcleo)   │ ───────────────────► │ HostGuard → RequestContext → BrowserGuard     │
 │ useVoiceInput (máquina)   │                      │   (Origin, Sec-Fetch-Site, audio/wav, tamanho)│
 │ capture.ts (AudioWorklet) │ ◄─────────────────── │ speech_routes  → SpeechService                │
 │ audio.ts (16 kHz, WAV)    │   {text, silent,…}   │   parse_wav → porta de silêncio → 1 vaga      │
 └───────────────────────────┘                      │   → thread worker → STTProvider (protocolo)   │
                                                    └──────────────────────────────────────────────┘
```

Backend (`src/fit_ai/speech/`): `audio.py` (parser estrito de WAV), `config.py` (ambiente, validado), `provider.py` (protocolo `STTProvider`),
`faster_whisper_provider.py` (real), `fake_provider.py` (testes), `service.py` (concorrência, timeout, cancelamento), `errors.py` (erros tipados).
Rotas em `api/speech_routes.py`. O STT **não conhece** o Ollama nem o chat.

UI (`ui/src/voice/`): `audio.ts` (resampling e WAV), `capture.ts` (microfone), `voiceMachine.ts` (estados), `useVoiceInput.ts` (orquestração),
`levels.ts` (nível ao vivo), `voiceMessages.ts` (textos). Componente `components/active/VoiceControl.tsx`.

## 4. Fluxo de áudio

1. Gesto do usuário (pointer/teclado/clique acessível) → `getUserMedia({audio: {channelCount: 1, …}, video: false})`. Só áudio, dispositivo padrão.
2. `AudioContext` na taxa da placa (tipicamente 48 000 Hz), `AudioWorklet` (`public/worklets/pcm-capture.js`, mesma origem, coberto pelo `script-src 'self'`)
   entrega blocos float32; o nível (RMS) alimenta as barras e o brilho do núcleo.
3. Ao soltar/cancelar/falhar/desmontar: **as trilhas são encerradas e o contexto fechado antes** de a interface entrar em `processing`.
4. Conversão explícita: filtro passa-baixa + reamostragem por sinc janelada (Blackman, tabela de kernel) até 16 kHz, float → int16 com clipping, WAV canônico de 44 bytes.
   Testado: a frequência de um tom de 440 Hz permanece 440 ± 3 Hz (a voz não muda de velocidade); tons de 10/12/15 kHz saem ≥ 40 dB abaixo (sem *aliasing*).
   Não se presume WAV 16 kHz do navegador e `MediaRecorder` não é usado.
5. `POST /api/v1/voice/transcribe`, `Content-Type: audio/wav`. O Core valida, transcreve e responde `{text, silent, duration_s, processing_ms, language, model}`.

## 5. Máquina de estados

`idle → permission_requested → listening → transcribing → completed`, mais `cancelled` e `error`. Cada evento carrega o **número da sessão**; um cancel passa
para uma sessão nova, então qualquer resultado atrasado (permissão tardia, transcrição tardia, erro tardio) é descartado num único ponto (`voiceReducer`).
Uma permissão concedida depois do cancelamento é liberada na hora. Uma captura por vez. Mapeamento visual: `listening` só com o microfone aberto,
`processing` só depois de fechado; o estado `responding` **não** é usado.

Interações: segurar para falar; toque rápido (< 350 ms) inicia e o próximo toque para (alternativa acessível); Esc cancela; perder foco da janela (ouvindo),
aba oculta, `hashchange`, `pagehide`, tela Active desmontada ou Core offline cancelam. Duração máxima 20 s (o Core aceita até 30 s); menos de 0,35 s é recusado localmente.

## 6. Privacidade (verificada por testes)

- O microfone só abre por gesto explícito; Standby nunca o toca (e2e: 0 chamadas a `getUserMedia`, 0 requisições).
- Sem escuta contínua, sem wake word, sem gravação em disco, sem SQLite, sem Ollama, sem nuvem. O Core não escreve arquivo temporário (teste: diretório vazio depois).
- Logs do Core: só números (duração, ms, quantidade de caracteres). Nunca texto nem áudio (teste com `caplog`). Erros do motor registram só o **tipo** da exceção.
- Respostas com `Cache-Control: no-store`. Mensagens de erro sem caminhos do sistema.
- O texto reconhecido só aparece na UI em build de desenvolvimento (`import.meta.env.DEV`); verificado que a string de depuração **não existe** no bundle de produção.
- Sem download silencioso: o Core não tem código de rede para modelos (`local_files_only=True`; teste de ausência de `urllib/requests/httpx/socket/huggingface`).

## 7. Segurança da rota

- Segue só em loopback; `HostGuard` (rebinding) e `BrowserGuard` valem para a rota. Sem CORS, pré-voo não respondido.
- Política própria por rota no `BrowserGuard` (`audio_paths`): `Content-Type` exatamente `audio/wav` (ou `audio/x-wav`), corpo limitado por `Content-Length` **e** durante o streaming
  (upload *chunked* sem `Content-Length` é cortado em 413). O chat manteve sua regra (JSON, 16 KB), com teste.
- Parser estrito: RIFF/WAVE, PCM, mono, 16-bit, 16 kHz, cabeçalho consistente, arquivo truncado/vazio/curto/longo recusados, no máximo 16 chunks. Sem caminhos, URLs, nome de modelo, idioma ou comando na requisição.
- Uma transcrição por vez; uma segunda recebe `429 stt_busy` (`Retry-After: 2`). A vaga só é liberada quando a thread do motor **realmente** termina (timeout e desconexão não acumulam trabalho na CPU). Timeout 30 s.
- Áudio sem sinal (pico < 0,004) responde `silent: true` sem rodar o motor.
- Falha de configuração (`FIT_AI_STT_*`) desliga a voz e registra o erro; o Core continua servindo telemetria.

Códigos: `invalid_audio`, `audio_empty`, `audio_too_short` (422), `audio_too_long`, `payload_too_large` (413), `unsupported_media_type` (415), `origin_not_allowed`, `cross_site_request` (403),
`invalid_host` (400), `stt_busy` (429), `stt_timeout` (504), `stt_failed` (502), `stt_disabled`, `stt_unavailable`, `stt_model_missing` (503).
`GET /api/v1/voice/status` informa `available | disabled | model_missing | engine_missing | unavailable` sem abrir microfone nem carregar modelo.

## 8. Configuração

| Variável | Padrão | Efeito |
|---|---|---|
| `FIT_AI_STT_ENABLED` | `true` | `false` desliga a funcionalidade (503 `stt_disabled`; a UI mostra "Voz indisponível"). |
| `FIT_AI_STT_MODEL_DIR` | `<repo>/../runtime/stt-models/faster-whisper-small` | Diretório **local** do modelo. Recusados: URL, compartilhamento de rede, nome de hub. |
| `FIT_AI_STT_THREADS` | `8` (1–16) | Threads de CPU. |
| `FIT_AI_STT_BEAM_SIZE` | `5` (1–10) | Largura do beam. |
| `FIT_AI_STT_TIMEOUT_S` | `30` (5–120) | Limite por transcrição. |
| `FIT_AI_STT_MAX_AUDIO_S` | `30` (1–30) | Duração máxima aceita. |
| `FIT_AI_STT_MIN_PEAK` | `0.004` (0–0,5) | Abaixo disso o áudio é tratado como silêncio. |
| `FIT_AI_STT_INITIAL_PROMPT` | dica automotiva | Texto de vocabulário (≤ 200 caracteres); vazio desliga. |
| `FIT_AI_STT_LANGUAGE` | `pt` | Só `pt` é aceito nesta fase. |

O modelo é carregado **na primeira transcrição** e mantido (≈ 340 MB). Ainda não há aquecimento nem descarregamento por ociosidade.

## 9. Instalação no Windows (manual, sem download automático)

Requisitos: Python 3.14 (o `.venv` do projeto), Node 22+, Windows 11.

1. **Motor** (baixa do PyPI na primeira vez; depois funciona offline):
   `.\.venv\Scripts\python.exe -m pip install -e ".[stt]"` (`faster-whisper==1.2.1`, `numpy`). Para ambiente sem internet, copie os wheels e use `pip install --no-index --find-links <pasta>`.
2. **Modelo** (MIT; revisão fixa `536b0662742c02347bc0e980a01041f333bce120` de `Systran/faster-whisper-small`). Em `FIT\runtime\stt-models\faster-whisper-small\` coloque `config.json`, `model.bin`, `tokenizer.json`, `vocabulary.txt`:

   ```powershell
   $rev = '536b0662742c02347bc0e980a01041f333bce120'; $dir = '..\runtime\stt-models\faster-whisper-small'
   New-Item -ItemType Directory -Force $dir | Out-Null
   foreach ($f in 'config.json','model.bin','tokenizer.json','vocabulary.txt') {
     Invoke-WebRequest "https://huggingface.co/Systran/faster-whisper-small/resolve/$rev/$f" -OutFile "$dir\$f" }
   (Get-FileHash "$dir\model.bin" -Algorithm SHA256).Hash   # esperado: 3E305921506D8872816023E4C273E75D2419FB89B24DA97B4FE7BCE14170D671
   ```
   O diretório fica **fora do Git** (nunca versione pesos de modelo).
3. **Iniciar:** `powershell -NoProfile -File ui\scripts\start-stack.ps1 -WithLlm -WithUi` e abrir `http://127.0.0.1:5173/#/active`. Use `127.0.0.1` ou `localhost`: em outro endereço HTTP o navegador não oferece microfone.
4. **Liberar o microfone no Windows 11:** Configurações → Privacidade e segurança → Microfone → ligar "Acesso ao microfone" e "Permitir que aplicativos da área de trabalho acessem seu microfone". No Edge: cadeado ao lado do endereço → Permissões do site → Microfone → Permitir (ou `edge://settings/content/microphone`).
5. **Dispositivo ausente ou errado:** `Get-PnpDevice -Class AudioEndpoint | Where Status -eq OK`; no navegador o microfone padrão é o do Windows (Configurações → Sistema → Som → Entrada). A interface diz "Nenhum microfone encontrado", "Permissão negada" ou "Microfone em uso" conforme o caso.
6. **Desligar:** `FIT_AI_STT_ENABLED=false` (ou não instale o modelo).
7. **Testes:** `python -m pytest -q` (backend), `npm test` e `npm run typecheck` em `ui/`; e2e com navegador: `FIT_E2E_SPEECH_WAV=<wav> node e2e/voice.mjs`; motor real: `FIT_AI_STT_TEST_WAV=<wav> pytest -m integration_stt`.

## 10. Testes

Resultados reais desta execução:

| Verificação | Resultado |
|---|---|
| Backend completo (SDK, OCTAVE e Ollama presentes) | **1959 passed**, 3 skipped, 1 xfailed (o do verificador, da P8.3) |
| Backend voz/segurança sem o motor instalado (como na CI) | 173 passed, 2 skipped (testes ao vivo, por falta do motor) |
| Transcrição ao vivo com o modelo real (`-m integration_stt`) | passou (voz sintética) |
| UI (Vitest) | **363 passed** em 20 arquivos (eram 198 na P8.3) |
| TypeScript estrito, build de produção | sem erros; sem vazamento do modelo local; worklet no `dist`; texto de depuração ausente do bundle |
| e2e voz (`e2e/voice.mjs`, Edge, Core e motor reais) | todos passaram em 1920×1080, 1366×768 e 1024×600, mais teclado, Esc, toque, navegação e Standby |
| e2e anteriores (standby, active, run 14/14, model-preview) e axe | passaram; axe com 0 violações (o item de contraste "needs review" da Active permanece) |

Cobertura do backend: áudio válido, tipo de conteúdo inválido, corpo excessivo (declarado e em streaming), arquivo truncado, vazio, curto, longo, silêncio, modelo ausente,
motor ausente, falha do motor, timeout, concorrência, cancelamento, Host inválido, Origin inválida, *cross-site*, ausência de CORS, nenhum arquivo escrito, nenhum texto nos logs.
Cobertura da UI: permissão concedida/negada/tardia, microfone ausente/ocupado/desconectado, segurar e soltar, toque, cancelar (Esc, foco, aba oculta, navegação, desmontagem),
múltiplas capturas, mudança de estado visual, áudio não enviado quando cancelado, respostas atrasadas descartadas, resampling (tom, *aliasing*, bordas, desempenho) e WAV canônico.

### Validação humana (Portão 3)

Em 2026-11-23 o usuário testou o push-to-talk na tela Active com a **própria voz e o próprio microfone** e aprovou: o reconhecimento de português do Brasil
funcionou de forma satisfatória. Isso aprova a P9.1 funcionalmente.

O que essa validação **é**: confirmação, por quem vai usar o produto, de que o fluxo completo (permissão, captura, envio, reconhecimento e retorno ao repouso) funciona e
entrega texto utilizável em pt-BR real.

O que ela **não é**, e não deve ser citada como:
- um benchmark de precisão: um único falante, sem WER, sem contagem de frases, sem registro das frases, tempos ou erros;
- evidência com ruído de cabine, vários sotaques, motor ligado ou janelas abertas;
- uma comparação com e sem a dica de vocabulário, ou com outros modelos;
- uma medição de latência (os ~3,8 s do §11 são do teste automatizado, com voz sintética).

Os números de precisão deste documento (WER, termos acertados) continuam sendo **sintéticos**. Uma medição estatística exigiria um conjunto de frases fixo, vários falantes e condições de
ruído, gravados com consentimento e guardados fora do repositório.

**Distinção importante:** o e2e usa o *dispositivo de captura falso* do Chromium reproduzindo **voz sintética** (Microsoft Maria). Ele prova o encanamento
(permissão, captura, reamostragem, WAV, upload, transcrição, estados, liberação das trilhas), **não** a precisão com voz humana. Nenhum microfone real foi aberto por mim.

## 11. Benchmarks e recursos

Todos com áudio sintético, nesta máquina, **na bateria** quando indicado (o laptop estava descarregando durante parte das medições; ver §12).

- Ativar o microfone (gesto até `listening`, dispositivo falso, permissão auto-aceita): 290–330 ms. Com o prompt real do navegador soma o tempo do usuário.
- Carga do modelo no Core: na primeira requisição (inclui importar o motor); 1,5–1,9 s medidos isoladamente.
- Soltar o botão até o texto (frase de 3,9 s, e2e completo, Core real, 8 threads): **≈ 3,8 s**; a primeira requisição após subir o Core levou 7,4 s (carga do modelo incluída).
- RAM: ≈ 340 MB após carregar (pico ≈ 1,0 GB durante a transcrição). CPU: usa em média ~8 núcleos durante os 2–4 s da transcrição.
- Ao ligar o laptop na bateria, o **mesmo** benchmark ficou ~2x mais lento (4 threads: 5,3 s contra 2,7 s de manhã; 8 threads: 3,5 s). Por isso o padrão passou a 8 threads.
- Não medido: com o Ollama carregado; ligado na tomada depois da queda; latência e precisão com voz humana (só validação qualitativa). Não se declara "tempo real": a latência é praticamente constante (~2,5–4 s) porque o Whisper processa uma janela fixa de 30 s.

## 12. Licenças (software e pesos)

| Componente | Versão | Licença | Observação |
|---|---|---|---|
| faster-whisper (SYSTRAN) | 1.2.1 | MIT | |
| CTranslate2 (OpenNMT) | 4.9.1 | MIT | |
| Pesos `Systran/faster-whisper-small` | rev. `536b0662…` | MIT (declarada no cartão do modelo) | conversão de `openai/whisper-small` |
| OpenAI Whisper (código e pesos) | — | MIT (repositório `openai/whisper`) | o cartão `openai/whisper-small` no Hugging Face declara **Apache-2.0**: ambas permissivas, a divergência foi registrada, não resolvida |
| onnxruntime | 1.32.0 | MIT | dependência do faster-whisper (VAD, não usado aqui) |
| tokenizers / huggingface-hub / hf-xet | 0.23.3 / 2.4.0 / 1.8.0 | Apache-2.0 | |
| numpy | 2.5.5 | BSD-3-Clause (+ 0BSD, MIT, Zlib, CC0) | |
| **av (PyAV)** | 19.0.2 | BSD-3-Clause | **o wheel embute FFmpeg com `libx264` e `libx265`** (codificadores GPL), além de dav1d, opus, vpx, webp, vmaf |
| whisper.cpp | b5907 | MIT | só avaliado, não integrado; pesos `ggml-small.bin` MIT |

### Pendência de redistribuição: PyAV / FFmpeg (GPL)

Fatos verificados (wheel `av-19.0.2-cp312-abi3-win_amd64`, 23 DLLs em `av.libs/`):
- O PyAV é BSD-3-Clause, mas o wheel **embute FFmpeg** (`avcodec`, `avformat`, `avfilter`, `swscale`, `swresample`…) **junto com `libx264` e `libx265`**, que são GPL, além de dav1d, opus, vpx, webp, vmaf e SVT-AV1.
  Isso indica um build de FFmpeg com componentes GPL. Não verifiquei o texto de licença do FFmpeg desse build; é preciso confirmá-lo antes de qualquer distribuição.
- O `faster-whisper` **não funciona sem o `av` instalado**: `faster_whisper/__init__.py` importa `faster_whisper.audio`, que faz `import av` na carga do módulo. Portanto as DLLs são
  **carregadas no processo do Core** na primeira transcrição, mesmo que **o código do Fit AI nunca chame o decodificador** (o áudio chega como `numpy`, `isinstance(audio, np.ndarray)` evita `decode_audio`).
- Hoje o projeto **não redistribui** nada disso: o `pip install -e ".[stt]"` baixa do PyPI na máquina do usuário. Nada do `av` está no repositório.

Consequência: para **uso local e desenvolvimento não há obrigação nova**. Um **instalador, imagem ou pacote que inclua esses wheels** seria uma redistribuição de FFmpeg com GPL e teria de cumprir essas obrigações
(ou evitá-las). Decisão pendente, com as opções conhecidas (nenhuma foi adotada):

1. Nunca empacotar: o instalador pede ao usuário que rode o `pip install` ele mesmo (mantém o estado atual; não resolve se o produto distribuído for um bundle).
2. Usar um `av` compilado contra um FFmpeg somente LGPL (build próprio ou de outra origem), e verificá-lo.
3. Trocar o motor pelo whisper.cpp (MIT, sem FFmpeg), aceitando ~2x de latência nesta CPU e o problema de caminhos não-ASCII (medido no §2).
4. Usar o CTranslate2 diretamente, com extração de features própria, sem o pacote `faster-whisper` (mais código e manutenção).
Um *shim* que substitua o módulo `av` por um falso funcionaria só porque o Fit AI passa `numpy`; é frágil e **não é recomendado**.

Nada foi redistribuído. Nenhuma licença permissiva foi adicionada ao código do Fit AI, e os direitos dos demais componentes não foram alterados.

### Dependências opcionais do STT (`pip install -e ".[stt]"`) e de teste

`[stt]` fixa `faster-whisper==1.2.1` e `numpy>=2`; as demais entram por dependência transitiva (versões instaladas: `ctranslate2 4.9.1`, `av 19.0.2`, `onnxruntime 1.32.0`, `tokenizers 0.23.3`,
`huggingface-hub 2.4.0`, `hf-xet 1.8.0`, `httpx2`/`httpcore2 2.16.2`, `pyyaml 6.0.4`, `protobuf 7.36.2`, `flatbuffers 25.12.19`, `fsspec 2026.9.0`, `filelock 4.3.1`), todas com licença permissiva declarada em seus metadados.
`numpy>=2` também entrou no extra `dev` (os testes do provider decodificam PCM com ele); o motor continua opcional e a CI não o instala.
Integridade: 25 wheels conferidos contra o SHA-256 do PyPI, zips do whisper.cpp contra o digest do GitHub, `model.bin` contra o SHA-256 do Hugging Face.

## 13. Limitações

- A validação humana (§10) é qualitativa e de um único falante: todos os **números** de precisão (WER, termos acertados) são sintéticos. A precisão com vários sotaques e ruído de cabine é desconhecida.
- O faster-whisper 1.2.1 não abre arquivos com o `av` 19 (`TypeError`); o Core evita isso decodificando o PCM ele mesmo.
- O whisper.cpp b5907 trava com caminho de modelo não-ASCII; o faster-whisper carrega normalmente de um caminho com acento (ex.: `C:\Users\<nome com acento>\…`).
- Latência de ~2,5–4 s depois de soltar o botão, maior na bateria; a primeira transcrição após subir o Core é mais lenta (carga do modelo).
- O texto é só para validação em desenvolvimento; o HUD de produção não mostra texto.
- A dica de vocabulário foi medida com as próprias palavras do teste.
- O item "needs review" de contraste do axe na tela Active continua (fundo 3D, não decidível automaticamente).
- Sem aquecimento do modelo nem descarregamento por ociosidade; sem seleção de dispositivo (usa o padrão do navegador).

## 14. Preparação para a P9.2

O resultado da transcrição já tem um ponto de entrega único (`voice.transcript`, fase `completed`) e uma sessão identificável. Para ligar ao Core/chat depois: decidir se o texto vai ao
`/api/v1/chat` automaticamente ou com confirmação; tratar `silent`/vazio; definir o momento de aquecer o modelo (opt-in, como o warm-up do LLM); decidir se o Ollama e o STT podem disputar a CPU;
resolver o licenciamento do `av` (§12); ampliar a validação humana (mais falantes, ruído de cabine, medição de WER) e decidir sobre o `initial_prompt`; só então considerar TTS e wake word (fora desta fase).
