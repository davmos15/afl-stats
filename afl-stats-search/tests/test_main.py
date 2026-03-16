from fastapi.testclient import TestClient

from main import app
from bs4 import BeautifulSoup

client = TestClient(app)


def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "AFL Stats Search" in response.text
    assert 'name="query"' in response.text


def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_search_no_api_key(monkeypatch):
    # Clear env var to ensure no key is found server-side
    monkeypatch.delenv("GOOGLE_AI_STUDIO_API_KEY", raising=False)
    response = client.post("/search", data={"query": "test", "provider": "gemini", "api_key": ""})
    assert response.status_code == 200
    assert "No API key" in response.text


def test_search_with_answer(monkeypatch):
    async def mock_query_llm(query, provider, api_key):
        return {
            "answer": "Collingwood won the 2023 AFL Grand Final.",
            "data": [{"Team": "Collingwood", "Score": "12.18 (90)"}],
            "r_code": 'library(fitzRoy)\nresult_df <- fetch_results(2023)',
            "need_clarification": False,
            "options": [],
            "_usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150, "model": "test"},
        }

    monkeypatch.setattr("main.query_llm", mock_query_llm)

    response = client.post("/search", data={"query": "Who won 2023 GF?", "provider": "gemini", "api_key": "fake"})
    assert response.status_code == 200
    assert "Collingwood" in response.text
    soup = BeautifulSoup(response.content.decode(), "html.parser")
    assert soup.find("table") is not None


def test_search_clarification(monkeypatch):
    async def mock_query_llm(query, provider, api_key):
        return {
            "answer": "",
            "data": None,
            "r_code": None,
            "need_clarification": True,
            "options": ["Brownlow Medal winners", "Coleman Medal winners"],
        }

    monkeypatch.setattr("main.query_llm", mock_query_llm)

    response = client.post("/search", data={"query": "medal winners", "provider": "gemini", "api_key": "fake"})
    assert response.status_code == 200
    soup = BeautifulSoup(response.content.decode(), "html.parser")
    buttons = [btn.text.strip() for btn in soup.find_all("button")]
    assert "Brownlow Medal winners" in buttons


def test_search_error(monkeypatch):
    async def mock_query_llm(query, provider, api_key):
        return {"error": "Request timed out. Please try again."}

    monkeypatch.setattr("main.query_llm", mock_query_llm)

    response = client.post("/search", data={"query": "test", "provider": "gemini", "api_key": "fake"})
    assert response.status_code == 200
    assert "timed out" in response.text


def test_dark_mode_support():
    response = client.get("/")
    assert "dark:" in response.text
    assert "toggleTheme" in response.text
