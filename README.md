# FiT-AI
Projeto de Teslalizar meu honda fit 2005.

## 1. Visão

Transformar o Honda Fit LX 2005 em um computador de bordo independente do smartphone: multimídia personalizável, assistente de IA local com voz e memória, monitoramento e diagnóstico, navegação e apps (YouTube, WhatsApp, Chrome, Maps, Waze, Spotify, Teams), funcionando sem depender de APIs pagas de IA.

## 2. Objetivos e limitações

**Estado atual: PoC 02.5.** Existe só a infraestrutura de telemetria. Não há IA, voz, memória, App Launcher, GPS nem interface própria, e **nenhum hardware real foi conectado** (tudo foi testado com o simulador do OCTAVE). Os planos para o que falta estão em `docs/`.

## 3. Arquitetura atual

```
OCTAVE (GUI ou --headless, --sim, 127.0.0.1:9876)
        │  protocolo de serviço v3, SDK Python oficial (MIT)
        ▼
adapters/octave.py ─► domain/telemetry.py ◄─ services/telemetry.py ◄─ api/routes.py  (FastAPI, 127.0.0.1:8000)
```

- `domain/`: modelo `VehicleTelemetry`, contrato `TelemetryProvider`, erros. Não conhece OCTAVE nem HTTP.
- `adapters/octave.py`: único ponto que fala com o OCTAVE. Nunca escreve no veículo. Faz leituras em lista de permissões e **uma** chamada com efeito no OCTAVE: `obdManager.setParameterDemand`, que pede ao OCTAVE que consulte RPM, velocidade e temperatura (sem isso o OCTAVE não atualiza esses valores e eles ficam congelados). Conexão persistente com reconexão; SDK em thread; unidades verificadas pelo catálogo (MPH→km/h); erros traduzidos.
- `services/`: casos de uso. `api/`: rotas, modelos e mapeamento erro→HTTP. `main.py`: `create_app(provider=...)` troca a fonte de telemetria.

## 4. Tecnologias

Python (testado em 3.14.3), FastAPI, Uvicorn, Pydantic; testes com pytest, anyio e httpx. Fonte de dados: OCTAVE v0.9.6 (C++/Qt 6).

## 5. Dependências

- Execução: `fastapi>=0.115`, `pydantic>=2`, `uvicorn>=0.30` (ver `pyproject.toml`).
- Desenvolvimento: `pytest>=8`, `httpx>=0.27`, `anyio>=4`.
- Externas: OCTAVE **v0.9.6** (referência principal; instalado em `..\runtime\octave`, instalação por usuário, sem admin) e o **SDK Python da mesma release**, extraído para `..\runtime\octave-sdk-0.9.6\sdk\python` (ou outro caminho em `OCTAVE_SDK_PATH`). Nada de terceiros é copiado para este repositório.
- Para criar o SDK da release a partir do checkout (somente leitura, não altera `externals/`):
  ```powershell
  $d="..\runtime\octave-sdk-0.9.6"; New-Item -ItemType Directory $d | Out-Null
  git -C ..\externals\octave archive --format=tar v0.9.6 sdk/python/octave_client sdk/python/LICENSE -o $env:TEMP\octave-sdk.tar
  tar -xf $env:TEMP\octave-sdk.tar -C $d
  ```
  Conferência: `git hash-object ..\runtime\octave-sdk-0.9.6\sdk\python\octave_client\__init__.py` deve dar `af32cccda9b3c2231419f86a87e6752dd5b40cfe` (o blob da tag `v0.9.6`).

## 6. Windows: instalação

```powershell
cd FiT-AI
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## 7. Executar o OCTAVE

```powershell
..\runtime\octave\OCTAVE.exe --sim --service 9876              # com interface gráfica
..\runtime\octave\OCTAVE.exe --headless --sim --service 9876   # sem janela
```
`--sim` usa um carro simulado em configuração temporária. O serviço escuta só em `127.0.0.1`. Não use `--service-bind`.

## 8. Executar o Fit AI Core

```powershell
$env:PYTHONDONTWRITEBYTECODE=1   # evita gravar __pycache__ no checkout de terceiros
.\.venv\Scripts\python.exe -m fit_ai
```
Documentação OpenAPI: <http://127.0.0.1:8000/docs>. Variáveis (opcionais; hosts precisam ser loopback): `FIT_AI_HOST`, `FIT_AI_PORT` (8000), `OCTAVE_HOST`, `OCTAVE_PORT` (9876), `OCTAVE_TIMEOUT_S` (2.0), `OCTAVE_SDK_PATH`.

## 9. Endpoints (somente GET)

| Endpoint | Descrição |
|---|---|
| `/health` | Saúde do Core (não consulta o OCTAVE) |
| `/api/v1/vehicle/telemetry` | `rpm`, `speed_kmh`, `coolant_temp_c`, `missing`, `source`, `simulated`, `timestamp` |
| `/api/v1/vehicle/status` | Estado da ligação com o OCTAVE (sempre 200; o estado vai em `state`) |

Erros de telemetria: `{"error": {"code", "message"}}` com 503 (`octave_unavailable`, `vehicle_link_down`, `no_data`), 504 (`octave_timeout`) ou 502 (`octave_protocol_incompatible`, `octave_error`). Um campo indisponível vem `null` (listado em `missing`); nada é inventado nem repetido de leituras antigas.

### Segurança da API local

- Escuta só em loopback (`FIT_AI_HOST` e `OCTAVE_HOST` precisam ser endereços locais, senão o Core não inicia).
- **Validação do cabeçalho `Host`** (proteção contra DNS rebinding): só `127.0.0.1`, `localhost` e `[::1]` (com ou sem porta) são atendidos; qualquer outro `Host`, ausente, duplicado ou malformado recebe `400 invalid_host` antes de chegar ao serviço.
- Sem CORS: nenhuma resposta traz `Access-Control-*`; uma página de outra origem não consegue ler as respostas.
- Superfície exposta: apenas os 3 endpoints GET acima e a documentação do FastAPI (`/docs`, `/redoc`, `/openapi.json`). Não há endpoints administrativos nem de escrita. Observação: `/docs` e `/redoc` carregam scripts de um CDN público no navegador.

## 10. Testes

```powershell
.\.venv\Scripts\python.exe -m pytest                        # tudo; os de integração são ignorados se o OCTAVE não estiver rodando
.\.venv\Scripts\python.exe -m pytest tests/unit tests/api   # sem OCTAVE
.\.venv\Scripts\python.exe -m pytest -m integration         # só contra o OCTAVE real
```
Resultado mais recente (ver `docs/consolidation-review.md`): 70 testes; com OCTAVE real 70 passed, sem OCTAVE 66 passed + 4 skipped. Cobertura 94%.

## 11. Integrações confirmadas

- OCTAVE v0.9.6, protocolo v3: leitura de RPM, velocidade e temperatura do **simulador** (e da interface gráfica rodando junto). Interface: home e hub OBD verificados; demais menus não.
- SDK da release v0.9.6 (padrão); a suíte também foi executada com o SDK do checkout.

## 12. Integrações planejadas

IA local (Ollama), voz (STT/TTS/wake word), memória, App Launcher, GPS, adaptador OBD real no Fit. Ver `docs/poc-03-architecture.md`, `docs/app-launcher-spec.md`, `docs/open-source-reuse-matrix.md`. Nada disso existe ainda.

## 13. Licenças e atribuições

- **Código próprio do Fit AI**: publicado no GitHub **apenas para consulta e estudo**. Não há licença open source (nem MIT, GPL ou outra) e **nenhuma autorização geral de reutilização, modificação ou redistribuição**; todos os direitos reservados ao autor. Ver o arquivo e o histórico para consulta, não para reuso.
- Os componentes de terceiros mantêm suas próprias licenças, avisos e obrigações, que continuam valendo integralmente (lista abaixo). Isto não se aplica a eles.
- OCTAVE (`github.com/RobDeGeorge/OCTAVE`): GPL-3.0-or-later; SDKs, templates e exemplos de frontend: MIT. O Core é um processo separado que fala o protocolo e **não contém código do OCTAVE**. Se um dia o OCTAVE for distribuído junto, a GPL se aplica a ele. Esta leitura é do projeto, não aconselhamento jurídico.
- Overdash: MIT (dependências: python-can LGPL-3.0, aiohttp Apache-2.0, websockets BSD-3-Clause). CarWatch: **AGPL-3.0** (somente ideias, sem copiar código). OpenVoiceOS ovos-core: Apache-2.0. Ver a matriz de reutilização.
- Os projetos em `externals/` são de terceiros e não são versionados aqui.

## 14. Roadmap resumido

1. PoC 03: AI Engine (Ollama) + ferramentas tipadas com permissão e auditoria, memória em SQLite, voz opcional (ver `docs/poc-03-architecture.md`).
2. Adaptador OBD real no Fit e levantamento dos PIDs do carro.
3. App Launcher com bloqueio durante a condução (ver `docs/app-launcher-spec.md`).
4. Decidir se o OCTAVE será a interface ou apenas a fonte de dados (impacto da GPL).
