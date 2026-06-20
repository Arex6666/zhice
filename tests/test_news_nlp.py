"""确定性 事实/情绪/推断 分类器（让治理 R6 长牙）。"""
import importlib.util


def _nlp():
    s = importlib.util.spec_from_file_location("nlp", "services/agent-service/news_nlp.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_fact_with_numbers():
    nlp = _nlp()
    assert nlp.classify_claim("公司公告2023年营收120亿元，同比增长35%") == "fact"


def test_inference_markers_win():
    nlp = _nlp()
    # 含"营收"(事实词)但被"预计/有望"(推断词)覆盖 → inference
    assert nlp.classify_claim("预计明年营收有望翻倍") == "inference"
    assert nlp.classify_claim("传闻公司将被收购") == "inference"


def test_sentiment_text():
    nlp = _nlp()
    assert nlp.classify_claim("市场情绪乐观，利好频出") == "sentiment"


def test_unverifiable_defaults_to_sentiment():
    nlp = _nlp()
    assert nlp.classify_claim("这只股票感觉不错") == "sentiment"


def test_to_evidence_type_mapping():
    nlp = _nlp()
    assert nlp.to_evidence_type("fact") == "news_fact"
    assert nlp.to_evidence_type("sentiment") == "news_sentiment"
    assert nlp.to_evidence_type("inference") == "news_inference"
