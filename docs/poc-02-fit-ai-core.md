# PoC 02 — GUI do OCTAVE + Fit AI Core (2026-11-16)

## 1. Objetivos
A) Validar a interface gráfica do OCTAVE no Windows. B) Criar o Fit AI Core (Python/FastAPI) que lê RPM, velocidade e temperatura do OCTAVE e as expõe via HTTP local, somente leitura. Sem IA, voz ou hardware.

## 2. Ambiente
Windows 11 Pro 10.0.26200, Python 3.14.3 (venv em `FiT-AI/.venv`), OCTAVE v0.9.6 instalado por usuário em `Desktop\FIT\runtime\octave`. Pacotes: ver §5. Tela 1920x1080 (escala 125%).

## 3. Arquitetura
Ver `README.md`. Resumo: `adapters/octave.py` (SDK oficial, somente leitura, conexão persistente, thread) → `domain/telemetry.py` (modelo, contrato, erros) → `services/telemetry.py` → `api/routes.py` (FastAPI). `create_app(provider=...)` injeta qualquer provedor.

Decisões:
- **Somente leitura imposta em código**: o cliente do SDK só é acessível via `_ReadOnlyClient` (6 leituras de propriedade + `parameterCatalog.info`). Teste confirma que `set`/`request`/outras chamadas nunca ocorrem. *(Atualizado na PoC 02.5: passou a existir uma chamada permitida a mais, `obdManager.setParameterDemand`, ver "Correções posteriores".)*
- **Unidades verificadas, não presumidas**: a cada conexão o adaptador consulta o catálogo do OCTAVE; velocidade `MPH`→km/h (×1,609344), `km/h` sem conversão, outra unidade ⇒ recusa (`octave_protocol_incompatible`). Temperatura só aceita °C.
- **Sem dado velho**: se `obdManager.connected` for falso, a telemetria é erro (`vehicle_link_down`) em vez de devolver o último valor do `paramStore`. *(Esta garantia era incompleta na PoC 02: com o link conectado mas sem ninguém pedindo o PID, o valor podia estar congelado. Corrigido na PoC 02.5.)*
- **`simulated: bool | None`** (o contrato sugerido era `bool`): vem de `sim.active`; `null` se não der para saber, para nunca afirmar "real" sem evidência.
- SDK carregado por `importlib` (na PoC 02 a partir de `externals/octave/sdk/python`; desde a PoC 02.5 o padrão é o SDK da release em `runtime/octave-sdk-0.9.6`), sem alterar `sys.path` e sem gravar bytecode no checkout de terceiros. Protocolo aceito: apenas v3.
- Hosts do Core e do OCTAVE precisam ser loopback (validado na configuração).

## 4. Estrutura criada
```
FiT-AI/
├── pyproject.toml  .gitignore  README.md (reescrito)
├── src/fit_ai/{__init__,__main__,main,config}.py
│   ├── domain/telemetry.py   ├── adapters/octave.py
│   ├── services/telemetry.py └── api/routes.py
├── tests/{conftest.py, unit/, api/, integration/}
└── docs/{poc-02-fit-ai-core.md, evidence/*.png}
```
Difere da sugestão: testes em 3 subpastas (unit/api/integration) em vez de dois arquivos.
Fora do projeto: `runtime/tools/winshot.ps1` e `click.ps1` (captura só da janela do OCTAVE; clique) e `runtime/logs/`.

## 5. Dependências (somente no venv do projeto)
fastapi 0.163.1, uvicorn 0.54.0, pydantic 2.14.3, starlette 1.10.0; dev: pytest 9.2.0, httpx 0.28.1 (anyio 4.16.0 vem como dependência). Todas instalaram em Python 3.14.3 sem problemas. Aviso conhecido: `starlette.testclient` informa que `httpx` está depreciado em favor de `httpx2` (não tratado).

## 6. Resultado da GUI do OCTAVE
Comando: `OCTAVE.exe --sim --service 9876` (GUI + simulador + serviço na mesma execução; o serviço escutou em 127.0.0.1:9876).

Observado (capturas só da janela do OCTAVE, em `docs/evidence/`):
- `octave-gui-01-home.png`: tela inicial com player ("No track playing"), SPD 0 MPH, RPM 800, CLT 90,0 °C, VOLT 14,1 V e barra de navegação (5 botões). Valores coincidem com os lidos pela API no mesmo momento.
- `octave-gui-02-obd.png`: após clicar no botão OBD, página "Simulated · Connected — OBD interface connected successfully", log do ELM327 simulado e cartões Dashboards / Trouble Codes / Trip History (apenas a página; os cartões não foram abertos).
- `octave-gui-03-after-restart.png`: GUI reiniciada, mostrando de novo valores do simulador.
- Log: nenhum erro crítico. Avisos repetidos de DirectWrite (`CreateFontFaceFromHDC failed` para "MS Sans Serif"), que não impediram a renderização.

**Não validado**: abrir um Dashboard, Trouble Codes, Trip History, mídia, sensores e Configurações. Parei de enviar cliques no meio da sessão porque o primeiro plano passou a ser a "Sobreposição da Ferramenta de Captura" do Windows (o usuário estava usando a máquina) e não quis injetar mais entrada no desktop. Uma captura logo após o clique no OBD ainda mostrava a tela anterior (a captura estava defasada); a seguinte já mostrava o hub OBD. A GUI está, portanto, validada para: abre, renderiza dados do simulador, aceita clique e navega até o hub OBD.

## 7. Resultado da API (Core real, 127.0.0.1:8000, contra o OCTAVE em execução)
```
GET /health                    200 {"status":"ok","service":"fit-ai-core","version":"0.1.0"}
GET /api/v1/vehicle/status     200 {"available":true,"state":"connected","source":"octave","simulated":true,
                                    "protocol_version":3,"octave_version":"0.9.6","detail":"Connected"}
GET /api/v1/vehicle/telemetry  200 {"rpm":800,"speed_kmh":0.0,"coolant_temp_c":90.0,"missing":[],
                                    "source":"octave","simulated":true,"timestamp":"2026-11-16T19:57:20.254505-03:00"}
```
Cenários reais exercitados:
- **Conversão**: com o simulador em movimento, OCTAVE `SPEED=47.8 mph` ↔ Core `speed_kmh=76.9` (esperado 76,9).
- **Dados parciais**: logo após reiniciar o OCTAVE: `{"rpm":800,"speed_kmh":null,"coolant_temp_c":null,"missing":["speed_kmh","coolant_temp_c"]}` (HTTP 200).
- **Link do veículo simulado caiu** (`sim.setLinkUp(false)`, feito por mim fora do Core): telemetria 503 `vehicle_link_down`; status 200 `state=vehicle_link_down`. Ao restaurar, a telemetria voltou a 200 sozinha.
- **OCTAVE encerrado**: telemetria 503 `octave_unavailable`; status 200 `available=false`; `/health` segue 200. Ao reiniciar o OCTAVE o Core voltou a responder 200 em ~2 s, sem reiniciar.
- Bind verificado com `netstat`: `127.0.0.1:8000` (LISTENING), sem exposição à rede.

Não exercitado ao vivo: `octave_timeout` e `octave_protocol_incompatible` (cobertos só por testes com fakes).

## 8. Resultado dos testes automatizados (pytest, Python 3.14.3)
- Com OCTAVE rodando: **62 passed**.
- Com OCTAVE parado: **58 passed, 4 skipped** (os 4 de integração, ignorados automaticamente).
- Divisão: 45 unitários (conversão, mapeamento, dados indisponíveis, falha de conexão, timeout, protocolo, somente leitura, config, serviço), 13 de API (injeção de provedor falso, health/telemetria/status, mapeamento de erros, só GET, OpenAPI) e 4 de integração real (leitura dos 3 parâmetros, status, "Core não altera o simulador" comparando `sim.status` antes/depois, API ponta a ponta).
- Verificação de sensibilidade: troquei temporariamente o fator para 1,6 → 5 testes falharam; revertido.
- Os testes de integração são só de leitura. Pytest roda com `PYTHONDONTWRITEBYTECODE=1`; verificado que nenhum `__pycache__` apareceu em `externals/`.

## 9. Problemas encontrados
- **Erro meu na PoC 01**: o relatório dizia que o OCTAVE não ficava rodando, mas o processo headless (PID 33548) seguia ativo na porta 9876. Encerrado no início desta PoC.
- Em `externals/` o estado é o mesmo de antes: `octave/android/.gradle/` (não rastreado, origem não identificada, criado antes da instalação) e `openvoiceos/translations/nl-NL/intents.json` modificado (já existia na PoC 01). Nenhum arquivo foi alterado por esta PoC (conferido com `git status`; não executei hooks).
- O README anterior (uma linha) foi reescrito, preservando a frase de abertura em essência.
- A velocidade do OCTAVE responde de forma gradual a `sim.setSpeed` (rampa); por isso o teste de conversão compara leituras simultâneas.
- Temperatura do simulador constante em 90 °C nas observações; a unidade/conversão de temperatura não foi exercitada com variação.

## 10. Próximos passos
Streaming (WebSocket) de telemetria, mais PIDs (combustível, tensão), reconexão com backoff configurável, teste com adaptador OBD real no Fit (protocolo e PIDs do carro ainda não verificados), terminar a validação dos menus da GUI (com autorização para interação manual), e só então o módulo conversacional.

## Correções posteriores (PoC 02.5)
Os números das seções 8 e 9 refletem o estado da PoC 02. Desde então (detalhes em `consolidation-review.md`):
- **Dado velho**: provado que sem demanda de PID o `paramStore` congela com o link "conectado" (SPEED=0 com o simulador a 126 mph). O adaptador agora registra `obdManager.setParameterDemand("fit-ai-core", [RPM, SPEED, COOLANT_TEMP])` ao conectar e a libera ao encerrar. É a única chamada de escrita permitida; ela só pede ao OCTAVE que consulte PIDs (escopo `read` na API do próprio OCTAVE) e nada é escrito no veículo.
- **SDK da release**: o adaptador falhava com o SDK exato da v0.9.6 (sem `OctaveConnectError` nem `Client.closed`); corrigido, e a suíte passa com os dois SDKs.
- **Falha de conexão no Windows** virava 504 com o SDK da release; agora é 503 `octave_unavailable` (latência de ~2 s: o Windows demora a recusar conexão em porta fechada de loopback).
- Teste de leitura de temperatura com asserção frouxa corrigido; testes adicionados (demanda, corrida de `_drop`, partida). Contagem atual: ver `consolidation-review.md` §4.
