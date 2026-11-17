# Matriz de reutilização open source (PoC 02.5)

Levantamento somente leitura dos checkouts em `externals/` (commits: octave `d51553d` = v0.9.6+48, overdash `0c67877`, carwatch `dda949b`, openvoiceos/ovos-core `ff20121`). Baseado em estrutura de arquivos, docstrings, READMEs e `pyproject.toml`. **Não executei** Overdash, CarWatch nem OVOS; "Windows" abaixo é avaliação, não teste, exceto o OCTAVE.

Legenda. Estado: Impl. = implementado segundo o código/README, Exp. = experimental, Plan. = planejado. Estratégia: **API** (processo separado), **SDK**, **Direto** (copiar/usar código), **Reimpl.** (ideia, código próprio). Decisão: Adotar / Investigar / Adiar / Descartar.

**Regra para copiar código**: só MIT/Apache-2.0, com aviso de licença. GPL/AGPL: nunca copiar; ideias só por reimplementação independente.

## OCTAVE — GPL-3.0+ (SDK, API, templates e `examples/frontends`: MIT)

| Funcionalidade | Módulo de origem | Estado | Licença | Estratégia | Windows | Prior. | Decisão |
|---|---|---|---|---|---|---|---|
| Protocolo de serviço (JSON-lines/WebSocket) | `src/service/`, `docs/api/` | Impl. (v3, verificado) | GPL-3.0+ (o `NOTICE` isenta só `sdk/`, `templates/`, `examples/frontends/`) | API | Nativo (verificado) | Alta | **Adotar** |
| SDK Python | `sdk/python/octave_client` | Impl. | MIT | SDK (fixar na versão da release) | Nativo (verificado) | Alta | **Adotar** |
| Simulador de carro | `src/sim/`, objeto `sim` (experimental) | Impl. | GPL | API | Nativo (verificado) | Alta (testes) | **Adotar** |
| Leitura OBD/ELM327, 129 leituras, catálogo de PIDs | `obdmanager*`, `parametercatalog`, `elm327protocol` | Impl. | GPL | API (`paramStore`, `parameterCatalog`) | Nativo para simulador; **hardware real não testado** | Alta | **Adotar** |
| PIDs customizados (modo 21/22) | `custompids`, `docs/CUSTOM_PIDS.md` | Impl. | GPL | API/config | Nativo | Média (PIDs Honda) | **Investigar** |
| Caixa-preta / histórico de viagens (SQLite) | `triprecorder`, `tripstore` | Impl. | GPL | API (`rows`) | Nativo | Média | **Investigar** (evita criar histórico próprio duplicado) |
| Player de mídia local, capa colorindo a UI | `mediamanager`, `nowplaying`, `frontend/` | Impl. | GPL | Aplicativo OCTAVE (processo separado) | Nativo (GUI verificada, mídia não testada) | Alta | **Adotar** como UI de mídia |
| Dashboards, editor de painéis | `frontend/dashboards`, `dashboardmanager` | Impl. | GPL | Aplicativo OCTAVE | Nativo (home/hub OBD verificados; dashboards não abertos) | Média | **Adotar** |
| Plataforma de frontends instaláveis (exemplos Svelte, Go, Rust, SDL2, Textual) | `frontendmanager`, `examples/frontends`, `templates/` | Impl./beta | MIT (exemplos, templates) | Direto (cópia permitida, MIT) | Depende do exemplo; não testado | Baixa (hoje) | **Investigar** se formos criar nossa UI |
| Integração Spotify (Web API, Premium) | `spotifymanager` | Exp. | GPL | Aplicativo OCTAVE | Não testado | Média | **Investigar**; deve ser a única fonte de Spotify (ver App Launcher) |
| Espelhamento de celular / Android Auto / AirPlay | `phonemirrormanager`, `androidautomanager`, `airplaymanager` | Exp./beta (AirPlay: Linux) | GPL (+Apache-2.0 no servidor do celular) | — | Requer ADB | Baixa | **Descartar** (objetivo é independência do celular) |
| Leitura/limpeza de DTC | `diagnosticsManager`/`obdManager` | Impl. | GPL | API (leitura); limpar = escrita | Nativo (simulador) | Média | **Adiar** (limpeza só como ferramenta com confirmação) |
| Adaptador OBD próprio (hardware) | `hardware/obd-adapter` | **Plan.** (não construído, conforme README) | GPL-3.0+ (sem licença própria no diretório; não verificado além do `NOTICE`) | — | n/a | Baixa | **Descartar** nesta fase |

Nota: o `NOTICE` do OCTAVE diz que `sdk/`, `templates/` e `examples/frontends/` são MIT "para que frontends construídos sobre eles possam usar qualquer licença", e `docs/api/README.md` afirma que um cliente só via protocolo é um programa separado. O backend e os arquivos de `docs/api/` são GPL-3.0-or-later. É a leitura do projeto, não aconselhamento jurídico: validar antes de distribuir.

## Overdash — MIT (dependências: python-can LGPL-3.0, aiohttp Apache-2.0, websockets BSD-3-Clause)

Pi/Chromium kiosk, backend asyncio. Windows não declarado no README/INSTALL (sem menções), tratado como "adaptação".

| Funcionalidade | Módulo de origem | Estado | Licença | Estratégia | Windows | Prior. | Decisão |
|---|---|---|---|---|---|---|---|
| Barramento de sinais (pub/sub asyncio) | `backend/data_bus.py` | Impl. | MIT | Reimpl. (≈25 linhas, só ideia) | Adaptação | Baixa | **Descartar**: duplica `paramStore` do OCTAVE + nosso `TelemetryProvider` |
| Fonte K-line ISO 9141-2/KWP2000 (init lento, Modos 01/03/07) | `backend/sources/obd_kline.py` (pyserial) | Impl. | MIT | Direto (com aviso MIT) ou referência | Adaptação (pyserial) | **Média**: o Fit 2005 provavelmente é K-line (não verificado) | **Investigar** como plano B se o ELM327 via OCTAVE não bastar |
| Fonte ELM327 / CAN-OBD | `elm327.py`, `can_obd.py` | Impl. | MIT (python-can LGPL) | Referência | Adaptação | Baixa | **Descartar**: duplica o OCTAVE |
| Fonte de dados simulada | `sources/mock_vehicle.py` | Impl. | MIT | Referência | Adaptação | Baixa | **Adiar** (OCTAVE `sim` já cobre) |
| Servidor WebSocket 30 Hz | `server/websocket.py` | Impl. | MIT | Reimpl. no Core quando houver streaming | Adaptação | Baixa | **Adiar** |
| Dashboards canvas e editor no navegador (PWA) | `frontend/` | Impl. | MIT | — | Navegador | Baixa | **Descartar**: duplica os dashboards do OCTAVE |
| Odômetro/viagem persistidos | `processors/odometer.py` | Impl. (grava `data/odometer.json`) | MIT | Referência | Adaptação | Baixa | **Adiar** |
| GPS NMEA | `sources/gps_nmea.py` | Impl. | MIT | Referência | Adaptação | Média (navegação futura) | **Investigar** depois do hardware |
| Histórico de telemetria | — | **Não encontrado** (só odômetro) | — | — | — | — | — |

## CarWatch — **AGPL-3.0** (só biblioteca padrão Python; Raspberry Pi + systemd; foco em Mercedes)

AGPL: copiar código para um serviço que ofereça acesso por rede obriga a disponibilizar o código-fonte. **Nenhum código será copiado; só ideias, reimplementadas.**

| Funcionalidade | Módulo de origem | Estado | Licença | Estratégia | Windows | Prior. | Decisão |
|---|---|---|---|---|---|---|---|
| **Grounding**: o modelo só afirma o que está num bloco KNOWN FACTS com fontes reais; o que não é sensível é listado como "não sensível" | `carwatch/grounding.py`, `selfstate.py` | Impl. (README: "proven") | AGPL | **Reimpl.** (conceito) | Python puro; independente de SO | **Alta** | **Adotar a ideia** (base do critério de aceite da PoC 03) |
| RAG local do manual do dono (léxico, com citação de página) | `carwatch/manual.py` (usa `pdftotext`/poppler) | Impl. | AGPL | Reimpl. | `pdftotext` no Windows: não verificado | Média | **Investigar** (manual do Fit) |
| Escuta contínua: VAD por energia + whisper.cpp offline | `listen.py`, `voice.py` | Impl. (README: medido num Pi 5) | AGPL | Reimpl. | Depende de arecord/whisper-cli: Linux | Média | **Investigar** só como inspiração |
| Agente em sala de chat (GroupMind), outbox | `agent.py`, `room.py`, `outbox.py` | Impl. | AGPL | — | Depende de serviço de nuvem | — | **Descartar** |
| Seletor de modelo (.gguf, llama.cpp, rollback, recusa se não cabe na RAM) | `models.py`, `webchat.py` | Impl. | AGPL | Reimpl. (conceito) | Linux/Pi | Baixa | **Adiar** (usaremos Ollama) |
| OBD/CAN próprios (Mercedes: DoIP, UDS) | `obd*.py`, `elm327.py`, `candecode.py`, `deepscan.py` | Impl. | AGPL | — | Linux | — | **Descartar** (outro carro; duplica OCTAVE) |
| Nuvem do carro (Mercedes me via Home Assistant) | `mercedesme.py`, `cloudcar.py` | Impl. | AGPL | — | — | — | **Descartar** |
| Painel web de 3,6 mil linhas, túneis, auto-update, Wi-Fi AP | `webchat.py`, `wifi_join.py`, `systemd/`, `update.sh` | Impl. | AGPL | — | Linux | — | **Descartar** |
| Dashcam, presença, viagens | `wolfbox.py`, `presence.py`, `trips.py` | Impl. | AGPL | — | — | Baixa | **Adiar** |

## OpenVoiceOS (ovos-core) — Apache-2.0 (permite reuso com aviso)

Este repositório contém só o núcleo (intents, skills, instalador). O listener/wake word, o barramento (`ovos-messagebus`) e áudio/TTS são **pacotes separados**, vistos apenas nos extras do `pyproject.toml`; seu código não foi inspecionado. Windows não é mencionado em README/FAQ/QUICK_FACTS (alvos: Raspberry Pi, Buildroot, instalador Linux).

| Funcionalidade | Módulo de origem | Estado | Licença | Estratégia | Windows | Prior. | Decisão |
|---|---|---|---|---|---|---|---|
| Serviço de intents (pipelines adapt/padatious/converse/fallback/stop) | `ovos_core/intent_services/` | Impl. | Apache-2.0 | SDK/plugin (via PyPI) | WSL2/adaptação (não verificado) | Média | **Investigar**; **conflita** com a seleção de ferramentas feita por LLM, não usar os dois na mesma responsabilidade |
| Barramento de eventos e plugins (OPM) | dep. `ovos-bus-client`, `ovos-plugin-manager`, `ovos-messagebus` | Impl. (pacotes externos) | Apache-2.0 | API/Direto | Adaptação | Baixa | **Adiar**; nosso Core usa `Protocol` + injeção, um barramento só agrega se houver vários processos |
| Skills (ecossistema) | `skill_manager.py`, `ovos-workshop` | Impl. | Apache-2.0 | SDK | Adaptação | Baixa | **Adiar** |
| Wake word / listener | `ovos-dinkum-listener` (pacote externo) | Impl. (não inspecionado) | Apache-2.0 | Plugin | Não verificado | Média | **Investigar** na PoC de voz |
| STT/TTS por plugin | `ovos-plugin-manager` (plugins externos) | Impl. (não inspecionado) | Apache-2.0 | Plugin | Não verificado | Média | **Investigar** |
| Persona/LLM | `ovos-persona` (extra) | Impl.? (não inspecionado) | Apache-2.0 | Plugin | Não verificado | Baixa | **Adiar** |
| Reprodução de mídia (OCP) | `ovos_ocp_pipeline_plugin` | Impl. (externo) | Apache-2.0 | — | — | — | **Descartar**: duplica o player do OCTAVE |

## Duplicações e recomendação concreta

| Responsabilidade | Candidatos | Recomendação |
|---|---|---|
| Fonte de telemetria | OCTAVE (`paramStore`), Overdash (fontes, DataBus), CarWatch (OBD próprio) | **Só OCTAVE** via API. Overdash `obd_kline.py` fica como plano B para K-line. |
| UI/dashboards | OCTAVE, Overdash | **OCTAVE**. Overdash descartado. |
| Mídia | OCTAVE, OVOS OCP | **OCTAVE**. |
| Spotify | OCTAVE `spotifymanager` (exp.), App Launcher (web) | **Um só**. Decidir após testar o do OCTAVE. |
| Voz (STT/TTS/wake word) | CarWatch (ideias, AGPL), OVOS (plugins, Apache) | **Voice Engine próprio com interface; avaliar plugins OVOS** na PoC de voz. Não adotar os dois. |
| Seleção de ações a partir da fala | Intents do OVOS, LLM com ferramentas (nosso plano) | **LLM com ferramentas** (PoC 03); OVOS adiado. |
| Grounding contra alucinação | CarWatch (conceito) | **Reimplementar a ideia** no Tool Execution. |
| Barramento de eventos | OVOS bus, Overdash DataBus | **Nenhum** por enquanto (processo único). |
