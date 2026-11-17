# PoC 03 — arquitetura prevista da IA local (especificação, sem implementação)

Nada aqui foi instalado ou implementado. Ollama não está instalado; nenhum modelo foi baixado.

## 0. Ponto de partida e restrições

- Máquina de desenvolvimento medida: Intel i5-1235U (10 núcleos), 31,7 GB de RAM, GPU integrada Iris Xe, sem GPU dedicada. Isso limita a PoC 03 a modelos pequenos/quantizados em CPU; **o hardware final do carro é desconhecido** e muda a escolha do modelo.
- Base existente: Fit AI Core (FastAPI) com `TelemetryProvider`, API local e testes.
- Princípios: a IA **só** conhece o carro por ferramentas autorizadas; tudo local por padrão; módulos trocáveis por interface; nada de dependência obrigatória de API paga.
- Reaproveitamento (ver matriz): a ideia de grounding do CarWatch (AGPL) é reimplementada, sem copiar código.

## 1. Visão geral

```
voz (opcional) ─► Voice Engine ──► texto ┐
texto (CLI/HTTP) ────────────────────────┤
                                          ▼
                              Conversation Service
                    ┌────────────┬─────────────┬──────────────┐
                    ▼            ▼             ▼              ▼
               AI Engine   Memory Engine  Tool Registry   Audit log
             (LLMProvider)  (SQLite)      (tipadas, perm.)  (JSONL/SQLite)
                    │                          │
                  Ollama                 get_vehicle_telemetry ─► Fit AI Core (TelemetryService)
                                         get_vehicle_status
                                         (futuro: launch_app, ...)
```
Mesmo processo do Core na PoC 03 (módulos Python com `Protocol`); sem microserviços. Novos pacotes: `fit_ai/ai/`, `fit_ai/memory/`, `fit_ai/tools/`, `fit_ai/voice/` (este por último).

## 2. AI Engine

```python
@dataclass(frozen=True)
class ChatMessage: role: Literal["system","user","assistant","tool"]; content: str; tool_call_id: str | None = None

@dataclass(frozen=True)
class ToolSpec: name: str; description: str; parameters_schema: dict   # JSON Schema gerado de um modelo pydantic

@dataclass(frozen=True)
class LLMReply: text: str | None; tool_calls: list[ToolCall]; model: str; finish_reason: str; usage: Usage | None

class LLMProvider(Protocol):
    async def generate(self, messages: list[ChatMessage], *, tools: list[ToolSpec] = (), timeout_s: float, max_tokens: int) -> LLMReply: ...
    async def stream(...) -> AsyncIterator[str]: ...          # fase 2
    async def health(self) -> ProviderHealth: ...             # modelo carregado, tempo de resposta
```
- **Ollama**: `OllamaProvider` por HTTP em `127.0.0.1:11434` (cliente `httpx`, sem SDK novo). Apenas loopback.
- **Troca de modelo** por configuração (`FIT_AI_MODEL`, registro de modelos em arquivo), sem alterar serviços: eles dependem só de `LLMProvider`.
- **Timeout** obrigatório por chamada, com cancelamento; falha vira erro tipado (`llm_timeout`, `llm_unavailable`), e a conversa responde de forma degradada ("não consigo pensar agora"), nunca inventa.
- **Controle de contexto**: orçamento de tokens por chamada; prioridade do que entra: regras do sistema > fatos conhecidos (§5) > memória relevante > histórico recente (janela deslizante, com resumo opcional). O que não cabe é descartado de forma determinística e registrada.
- Testes sem modelo: `FakeLLMProvider` programável.

## 3. Voice Engine (depois do texto funcionar)

Interfaces separadas, uma implementação por vez:
```python
class SpeechToText(Protocol):  async def transcribe(self, audio: bytes, sample_rate: int, *, language: str | None) -> Transcript: ...
class TextToSpeech(Protocol):  async def speak(self, text: str, *, voice: str | None) -> AudioClip: ...
class WakeWord(Protocol):      def detect(self, frame: bytes) -> bool: ...        # opcional
```
- Começar com **push-to-talk** (sem wake word) para evitar captar conversas; wake word é opcional e desligável.
- **Offline por padrão**; qualquer serviço em nuvem é um provedor à parte, opt-in explícito e visível.
- Candidatos (a avaliar, não escolhidos): STT com whisper (whisper.cpp ou faster-whisper), TTS com Piper, wake word openWakeWord; plugins OVOS como alternativa (ver matriz). Medir latência e uso de CPU na máquina real antes de decidir.
- Áudio de entrada não é gravado em disco por padrão.

## 4. Memory Engine

- Armazenamento local: **SQLite** (stdlib), arquivo em pasta de dados do usuário, fora do Git.
- Três tabelas lógicas: `conversation_turns`, `preferences` (chave/valor tipadas, ex.: unidades, idioma), `facts` (fatos do usuário ditos por ele, com origem e data).
- Busca contextual: **FTS5** (lexical) na primeira versão; embeddings só se a lexical se mostrar insuficiente (evita modelo extra).
- Privacidade e retenção: tudo local; o usuário pode listar, apagar e exportar; retenção configurável do histórico (padrão proposto: 30 dias para turnos, indefinido para preferências); nada de telemetria externa; áudio não persistido; campos marcados como sensíveis (localização, contatos) só entram na memória com ação explícita.
- **Telemetria viva não vai para a memória** (é dado em tempo real; ver §5).

## 5. Tool Execution e grounding (o núcleo de segurança)

Regra: **a IA só afirma sobre o veículo o que veio de uma ferramenta nesta conversa.**

- Cada ferramenta tem: nome, esquema de entrada (pydantic), esquema de saída, `permission` e `side_effect`.
- Níveis de permissão: `READ` (telemetria, status), `ACTION_LOW` (ex.: abrir app permitido), `ACTION_CONFIRM` (exige confirmação do usuário: ex.: limpar DTC), `FORBIDDEN` (nunca exposto: escrita na ECU, aceleração/freio/direção). Só `READ` na PoC 03.
- Separação leitura/escrita no registro; a IA recebe só as ferramentas habilitadas por contexto (ex.: apps visuais sem estar estacionado nem aparecem como disponíveis).
- Primeira ferramenta: `get_vehicle_telemetry` → `TelemetryService.get_telemetry()`. Resultado inclui `timestamp`, `simulated`, `missing` e **erros estruturados**; a IA deve repassar "não disponível" em vez de estimar.
- **Bloco KNOWN FACTS** montado a cada turno a partir das ferramentas e do estado (com idade do dado e se é simulado), e lista explícita do que **não** se pode sensorizar. Ideia reimplementada a partir do conceito do CarWatch (sem copiar código AGPL).
- **Validação de saída** (fase 2): checar números citados contra os fatos da ferramenta; divergência ⇒ regenerar ou responder só com os fatos.
- **Auditoria**: cada chamada de ferramenta grava (data/hora, ferramenta, argumentos, resultado resumido, quem pediu, estado de condução, decisão). Sem segredos nem áudio.
- Dependência de segurança: antes de qualquer ferramenta de ação, o Core precisa validar `Host`/origem (DNS rebinding, ver `consolidation-review.md`) e ter o estado de condução do App Launcher.

## 6. Plano e critérios de aceite da PoC 03

**Escopo**: AI Engine com Ollama + 1 modelo pequeno, Conversation Service em texto (CLI e `POST /api/v1/chat`), Memory Engine básico, ferramenta `get_vehicle_telemetry`, auditoria. Voz fica para PoC 03b. Sem App Launcher.

**Dependências previstas**: Ollama (binário externo, instalação por usuário, a autorizar), um modelo (a escolher e baixar com autorização), `httpx` já no dev (passa a runtime). SQLite é stdlib. Nada de frameworks de agentes pesados.

**Critérios de aceite** (todos com evidência executada):
1. `LLMProvider` com duas implementações (Ollama e Fake); o Conversation Service passa a mesma suíte com ambas, sem alteração.
2. Pergunta "qual a rotação?" com OCTAVE rodando ⇒ a resposta contém o RPM **igual** ao da ferramenta daquele turno (teste automatizado com fake de telemetria e verificação manual com o simulador).
3. Com OCTAVE parado ou link caído ⇒ a resposta diz que não há dado; **nunca** um número (teste automatizado + manual).
4. Pergunta sobre algo sem ferramenta (ex.: pressão dos pneus, nível do óleo) ⇒ declara que não sabe medir, sem inventar (conjunto de perguntas de regressão).
5. Timeout do modelo ⇒ resposta degradada em tempo limitado; sem travar a API (teste com fake lento).
6. Troca de modelo por configuração, sem mudar código de serviço (teste).
7. Memória: preferência dita pelo usuário persiste após reiniciar; apagar remove de fato; busca FTS retorna o item (testes).
8. Auditoria: toda chamada de ferramenta aparece no log, e nenhuma ferramenta além de `READ` está registrada (teste).
9. Latência medida e registrada (tokens/s, tempo até a primeira resposta) na máquina de desenvolvimento, **sem prometer** que serve no hardware do carro.
10. Nenhuma alteração em `externals/`; nenhum código GPL/AGPL copiado; modelos e dados fora do Git.

**Riscos**: desempenho em CPU, qualidade de chamada de ferramentas de modelos pequenos (pode exigir saída estruturada/validação), hardware do carro desconhecido, licença do modelo escolhido (verificar antes de usar).
