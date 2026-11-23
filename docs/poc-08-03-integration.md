# P8.3 — Estabilização do backend e integração da interface

Estado: implementado e validado localmente, **sem commit**. Nada aqui implementa voz (STT, TTS, wake word).

## 1. O que mudou

| Área | Mudança |
|---|---|
| Bug "Não está disponível" | Corrigido na causa (secção 2), com testes de regressão. |
| Status do Ollama | `GET /api/v1/llm/status` real, somente leitura; a UI deixa de mostrar um estado fixo. |
| Warm-up / keep-alive | Opt-in, ciente de RAM e CPU, não bloqueante, desligado por padrão. |
| Telemetria na UI | Painel só com dados reais (RPM, km/h, temperatura do arrefecimento, estado da conexão). |
| Qualidade da UI | Legibilidade em 1024×600, auditoria axe-core, separação do chunk do Three.js. |
| Infra | `.gitattributes`, GitHub Actions, Dependabot, política de testes que precisam do SDK. |

## 2. Causa raiz do "Não está disponível" em pergunta geral

Três caminhos levavam ao mesmo sintoma. Dois foram corrigidos; o terceiro é uma limitação conhecida (secção 7).

1. **Falso positivo do guarda de vazamento do prompt.** `leaks_prompt` comparava trechos de 6 palavras da resposta com *toda* a mensagem de sistema. A primeira frase do sistema é a identidade do assistente; uma resposta correta a "quem é você?" a repete e era rejeitada como vazamento. Agora só o texto *após* a primeira frase é protegido (`_guarded_text`). As regras internas continuam protegidas.
2. **Mensagem de correção específica de telemetria.** Ao rejeitar uma resposta, a segunda tentativa recebia uma instrução sobre "valores de sensores/leituras" mesmo em turnos sem nenhuma leitura. O modelo ficava confuso e a segunda resposta falhava também. Sem leituras, a correção agora é neutra (`correction_message(codes, with_readings=False)`).
3. **"motor" classificava a pergunta como telemetria.** "Como funciona um motor de quatro tempos?" disparava leitura de sensores. `motor` saiu do vocabulário de telemetria; só conta quando não há pedido de explicação (`o que é`, `como funciona`, `explique`, `diferença entre`, …).

O verificador **não foi afrouxado** para fazer o teste passar. Evidência: reprodução com o modelo real antes e depois; a primeira pergunta de identidade passa na primeira tentativa.

Testes: `tests/orchestration/test_general_question_regression.py` (+ ajuste em `test_prompt_leak_guard.py`).

## 3. Endpoint `GET /api/v1/llm/status`

Resposta: `{ "state": "available" | "model_not_installed" | "unavailable" | "unverified" | "not_configured", "model": str | null, "checked_at": str }`.

- `available`: o Ollama responde e o modelo configurado está instalado. `model_not_installed`: responde, mas o modelo falta. `unavailable`: recusa conexão (só isso prova que está desligado). `unverified`: timeout ou resposta estranha, não prova nada. `not_configured`: o Core subiu sem runtime de chat. Nunca "available" por suposição. A UI mostra, respectivamente, `Disponível`, `Modelo ausente`, `Desligado`, `Não verificado` e `Sem modelo`.
- Somente leitura (`/api/version` + `/api/tags`). Não inicia o Ollama e **não carrega modelo**.
- Sem URL vinda do cliente, timeout de 2,5 s, cache de 5 s, sem detalhes de erro na resposta. Host/Origin continuam protegidos.
- Logo após subir, o primeiro status pode vir `unverified` e se corrige dentro do TTL.

## 4. Warm-up e keep-alive (opt-in)

| Variável | Padrão | Efeito |
|---|---|---|
| `FIT_AI_LLM_WARMUP` | desligado | Liga o pré-aquecimento em segundo plano. |
| `FIT_AI_LLM_WARMUP_MIN_FREE_RAM_MB` | 6000 (faixa 1024–131072) | Não aquece se a RAM livre for menor. |
| `FIT_AI_LLM_KEEP_ALIVE` | não enviado | Formato `30s`–`24h` (ex.: `30m`). |

Pula o aquecimento se a CPU estiver ocupada (> 80 %). Não bloqueia a subida do Core e é cancelado no encerramento.

Medido nesta máquina (Ollama 0.40.16): carregar o modelo ≈ 2,6 s; primeira pergunta real a frio 20,7–25,4 s contra 3,1 s após o aquecimento (655/668 tokens de prefixo em cache); keep-alive padrão do servidor 10 min; `30m` respeitado; custo ≈ 3,0 GB de RAM enquanto o modelo está carregado. Ponta a ponta com o stack real: primeira pergunta em 2,9 s.

## 5. Telemetria na interface

- Só RPM, km/h, temperatura do arrefecimento e estado da conexão. Atualização a cada 2 s, somente GET.
- Quando a origem é OCTAVE simulado, o painel exibe **"DADOS SIMULADOS"** sempre.
- Campo ausente aparece como indisponível, nunca como zero. Sem bateria, pneus ou falhas inventadas e sem afirmar "normal/anormal".
- A tela Active passa a fazer 4 GETs de leitura (`/health`, `/api/v1/vehicle/status`, `/api/v1/vehicle/telemetry`, `/api/v1/llm/status`). O chat continua proibido fora da ação do usuário; os testes e o e2e verificam isso.

## 6. Qualidade, CI e resultados reais

| Verificação | Resultado |
|---|---|
| Backend completo (SDK presente) | 1816 passed, 1 skipped, 1 xfailed |
| Backend em checkout limpo (sem SDK, sem OCTAVE) | 1775 passed, 17 skipped, 1 xfailed, 0 failed |
| UI unit/component | 14 arquivos, 198 testes passed |
| TypeScript | sem erros |
| Build | OK; chunk `three` separado (521 kB / 132 kB gzip) |
| Vazamento do modelo local no bundle | nenhum |
| `npm audit` (high) | 0 |
| axe-core, Standby e Active, 1920×1080 e 1024×600 | 0 violações; 1 item "needs review" de contraste na Active (sobre fundo 3D, não decidível automaticamente) |
| e2e standby / active / run (HUD 14/14) / model-preview | todos passaram |
| Overflow em 1920×1080, 1600×900, 1366×768, 1280×720, 1024×600 | nenhum; fontes mínimas de 12 px |

O `e2e/active.mjs` foi atualizado: aceitava só 2 GETs (P8.2) e agora aceita os 4 GETs de leitura listados acima, mantendo o chat proibido.

**CI** (`.github/workflows/ci.yml`): UI em Ubuntu e Windows (install exato, typecheck, testes, build, checagem de vazamento, audit) e backend em Windows com Python 3.14. Hermético: sem segredos, sem modelo, sem OCTAVE. Testes que precisam do SDK (fora do repositório) são pulados com motivo explícito (`needs_sdk`). Os e2e de navegador (WebGL) rodam na máquina do desenvolvedor, não no CI. O Dependabot só abre PRs.

**Bundle**: `manualChunks` separa apenas o núcleo do Three.js e exclui `three/examples/`, para o `GLTFLoader` não entrar no carregamento inicial. Sem regressão de tamanho.

Capturas reais: `ui/e2e/out/p83/active-{1920x1080,1366x768,1280x720,1024x600}.png` (ignoradas pelo Git).

## 7. Limitações conhecidas

- **Verificador e palavras de número.** Em turno sem leituras, número por extenso usado como contagem ("quatro tempos", "dos dois") é tratado como número não verificado, e uma resposta geral correta cai no fallback. Relaxar exige revisão contra o corpus adversarial e seu oráculo. Registrado como `xfail` estrito.
- O prompt de sistema faz o modelo recusar demais conhecimento geral.
- O item de contraste "needs review" da Active precisa de checagem manual.
- `pip` 25.3 da `.venv` local tem avisos (somente ferramenta).
- `src/fit_ai/grounding/__init__.py` aparece modificado só por fim de linha (CRLF → LF pelo `.gitattributes`); não há mudança de conteúdo.

## 8. Pendências para o P9 (voz)

Sem implementação de STT, TTS ou wake word. Antes de começar: decidir licenças e permissões dos motores de voz; política de microfone e consentimento; revisão do verificador para números por extenso; revisão do prompt de sistema; endpoints `/api/v1/memory/*`; decisão definitiva do modelo do veículo (direitos do modelo C não confirmados, segue só local); licença do repositório; decisões de GPL do OCTAVE/SDK; resíduo `externals/octave/android/.gradle/`.
