"""L7 LLM 因子挖掘编排（propose-then-prove 闯关）—— 核心逻辑依赖注入, 脱 LLM 可测。"""
import importlib.util


def _ml():
    s = importlib.util.spec_from_file_location("mlf", "scripts/mine_llm_factors.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_mine_one_accepts_good_factor():
    ml = _ml()
    out = ml.mine_one(
        llm_propose=lambda: "Ref(C,21)/Ref(C,252)-1",
        compute_factor=lambda f: [0.1, 0.2, 0.3],
        alpha_evaluate=lambda v: {"passes": True, "pps": 0.5, "pfs": 0.9},
        originality_check=lambda v, lib: {"original": True, "max_corr": 0.1},
        library=[])
    assert out["accepted"] is True and out["formula"] == "Ref(C,21)/Ref(C,252)-1"


def test_mine_one_rejects_unsafe_dsl():
    ml = _ml()

    def compute(f):
        raise ValueError("非白名单调用")

    out = ml.mine_one(lambda: "__import__('os')", compute, lambda v: {}, lambda v, l: {}, [])
    assert out["accepted"] is False and out["stage"] == "dsl_parse"


def test_mine_one_rejects_failed_alpha_eval():
    ml = _ml()
    out = ml.mine_one(lambda: "C", lambda f: [1, 2, 3],
                      lambda v: {"passes": False, "pps": 0.0, "pfs": 0.5},
                      lambda v, l: {"original": True}, [])
    assert out["accepted"] is False and out["stage"] == "alpha_eval"


def test_mine_one_rejects_unoriginal():
    ml = _ml()
    out = ml.mine_one(lambda: "C", lambda f: [1, 2, 3], lambda v: {"passes": True},
                      lambda v, l: {"original": False, "max_corr": 0.95}, [])
    assert out["accepted"] is False and out["stage"] == "originality"


def test_extract_formula_strips_fences():
    ml = _ml()
    assert ml._extract_formula("```\nRef(C,5)/C-1\n```") == "Ref(C,5)/C-1"
    assert ml._extract_formula('公式: `ts_mean(C,10)`') == "ts_mean(C,10)"
