"""P5 harness helpers: scoring rules and statistics (no server, no model)."""
import json

from bench.p5_runner import aggregate, percentile
from bench.p5_scenarios import TOOL_NAMES, build_p5_scenarios
from fit_ai.ai import LLMResponse, ToolCall

SC = {s.id: s for s in build_p5_scenarios()}


def resp(content="", calls=(), finish="stop") -> LLMResponse:
    return LLMResponse(content=content, model="m:t", finish_reason=finish,
                       tool_calls=tuple(ToolCall(name=n) for n in calls))


def test_scenario_ids_unique_and_nonce_leads_the_user_turn():
    ids = [s.id for s in SC.values()]
    assert len(ids) == len(set(ids))
    for s in SC.values():
        msgs = s.build("r9")
        first_user = next(m for m in msgs if m.role == "user")
        assert first_user.content.startswith("[r9] ")  # defeats whole-turn prompt-cache reuse
        assert msgs[0].role == "system"  # identical system prefix for both models


def test_no_invention_scoring():
    s = SC["UNAV_tyre_notools"].score
    assert s(resp("Não tenho acesso aos sensores, não consigo informar a pressão."))[0]
    assert not s(resp("A pressão está em 32 psi."))[0]
    assert not s(resp("Está tudo normal."))[0]  # neither invents a number nor admits the gap
    assert not s(resp("", ["ler_rotacao_motor"]))[0]  # no tools exist in this scenario


def test_tool_scoring():
    pos = SC["TOOL_rpm"].score
    assert pos(resp("", ["ler_rotacao_motor"]))[0]
    assert not pos(resp("", ["ler_velocidade_veiculo"]))[0]
    assert not pos(resp("Cerca de 800 rpm."))[0]
    neg = SC["TOOLNEG_greeting"].score
    assert neg(resp("Bom dia! Tudo bem."))[0] and not neg(resp("", ["ler_rotacao_motor"]))[0]
    assert "ler_rotacao_motor" in TOOL_NAMES


def test_intent_and_struct_scoring():
    assert SC["INT_multimidia"].score(resp(json.dumps({"intencao": "multimidia"})))[0]
    assert not SC["INT_multimidia"].score(resp(json.dumps({"intencao": "navegacao"})))[0]
    assert not SC["INT_multimidia"].score(resp("not json"))[0]
    good = {"codigo_dtc": "p0301", "origem_dado": "informado_pelo_usuario", "gravidade": "media"}
    assert SC["STRUCT_dtc"].score(resp(json.dumps(good)))[0]
    assert not SC["STRUCT_dtc"].score(resp(json.dumps({**good, "origem_dado": "medido_por_sensor"})))[0]


def test_pt_check_rejects_english_and_truncation():
    pt = SC["PTCHAT_oil"].score
    assert pt(resp("A troca de óleo é a renovação do lubrificante do motor, que protege as peças contra o desgaste."))[0]
    assert not pt(resp("Oil change is the replacement of the engine oil and it is important for the engine."))[0]
    assert not pt(resp("A troca de óleo é a renovação do lubrificante que protege o motor de desgaste", finish="length"))[0]


def test_percentile_and_aggregate():
    assert percentile([1, 2, 3, 4, 5], 50) == 3
    assert percentile([1, 2, 3, 4, 5], 95) == 4.8
    assert percentile([], 95) is None
    rows = [{"model": "m", "scenario": "S", "category": "c", "ok": i < 4, "reason": "ok" if i < 4 else "x",
             "total_s": 10 + i, "load_s": 1.0, "gen_tps": 5.0, "completion_tokens": 20, "round": i,
             "infer_ws_mb": 3000} for i in range(5)]
    rows.append({"warmup": True, "model": "m", "load_s": 3})  # warm-ups never enter the statistics
    a = aggregate(rows)["models"]["m"]
    assert a["scenarios"]["S"]["passed"] == 4 and a["scenarios"]["S"]["n"] == 5
    assert a["scenarios"]["S"]["total_s"]["median"] == 12
    assert a["scenarios"]["S"]["steady_s"]["median"] == 11


def test_suspension_artifacts_are_excluded_from_statistics():
    good = {"model": "m", "scenario": "S", "category": "c", "ok": True, "reason": "ok", "total_s": 10.0, "load_s": 0.0}
    bad = {"model": "m", "scenario": "S", "category": "c", "ok": False, "reason": "suspend_suspected",
           "error": "LLMTimeout", "wall_s": 4370.0, "invalid": True}
    agg = aggregate([good, bad, {**good, "retry": True}])
    assert agg["invalid_excluded"] == 1
    assert agg["models"]["m"]["scenarios"]["S"]["n"] == 2 and agg["models"]["m"]["scenarios"]["S"]["errors"] == 0
