import importlib.util


def _tools():
    spec = importlib.util.spec_from_file_location(
        "ztools", "services/mcp-tool-service/tools.py"
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


HTML = open("tests/fixtures/sample.html", encoding="utf-8").read()


def test_clean_text():
    t = _tools()
    out = t.html_to_text(HTML)
    assert "Hello World" in out and "microservices" in out
    assert "var a=1" not in out  # script stripped
    assert "color:red" not in out  # style stripped


def test_get_title():
    t = _tools()
    assert t.get_title(HTML) == "Sample Page"


def test_extract_links():
    t = _tools()
    links = t.extract_links_from_html(HTML, base_url="http://site.com/page")
    hrefs = {link["href"] for link in links}
    assert "http://site.com/about" in hrefs  # relative -> absolute
    assert "https://ext.com/x" in hrefs


def test_crawl_structured():
    t = _tools()
    items = t.crawl_structured_from_html(HTML, ".item")
    assert [i["text"] for i in items] == ["Alpha", "Beta"]
