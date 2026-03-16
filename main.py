from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from jinja2 import Template
import os
import json
import asyncio
import httpx
import logging

from data import fetch_live_context

load_dotenv()

PROVIDERS = {
    "gemini": {
        "name": "Google Gemini",
        "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        "env_key": "GOOGLE_AI_STUDIO_API_KEY",
        "signup": "https://aistudio.google.com/apikey",
    },
    "openai": {
        "name": "OpenAI (ChatGPT)",
        "url": "https://api.openai.com/v1/chat/completions",
        "env_key": "OPENAI_API_KEY",
        "signup": "https://platform.openai.com/api-keys",
    },
    "anthropic": {
        "name": "Anthropic (Claude)",
        "url": "https://api.anthropic.com/v1/messages",
        "env_key": "ANTHROPIC_API_KEY",
        "signup": "https://console.anthropic.com/settings/keys",
    },
}

prompt_template = Template(open("prompts/r_code.tmpl", "r", encoding="utf-8").read())

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Shared HTTP client for LLM calls
_llm_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _llm_client
    _llm_client = httpx.AsyncClient(timeout=30, limits=httpx.Limits(max_connections=10))
    yield
    await _llm_client.aclose()


app = FastAPI(title="AFL Stats Search", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")


def get_api_key(provider: str) -> str | None:
    return os.environ.get(PROVIDERS[provider]["env_key"])


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse(request, "index.html", {"providers": PROVIDERS})


@app.post("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    query: str = Form(...),
    provider: str = Form("gemini"),
    api_key: str = Form(""),
):
    key = api_key.strip() or get_api_key(provider)
    if not key:
        return templates.TemplateResponse(
            request,
            "partials/results.html",
            {
                "result": {"error": f"No API key set. Click the AI selector and paste your {PROVIDERS[provider]['name']} key."},
                "query": query,
                "provider": provider,
                "provider_name": PROVIDERS[provider]["name"],
            },
        )
    result = await query_llm(query, provider, key)
    return templates.TemplateResponse(
        request,
        "partials/results.html",
        {"result": result, "query": query, "provider": provider, "provider_name": PROVIDERS[provider]["name"]},
    )


async def query_llm(query: str, provider: str, api_key: str) -> dict:
    live_data = await fetch_live_context(query)
    logger.info("Query: %s (provider: %s, context: %d chars)", query, provider, len(live_data))
    prompt = prompt_template.render(query=query, live_data=live_data)

    try:
        if provider == "gemini":
            return await _call_gemini(prompt, api_key)
        elif provider == "openai":
            return await _call_openai(prompt, api_key)
        elif provider == "anthropic":
            return await _call_anthropic(prompt, api_key)
        else:
            return {"error": f"Unknown provider: {provider}"}
    except httpx.TimeoutException:
        return {"error": "Request timed out. Please try again."}
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status == 429:
            return {"error": "Rate limited. Wait a few seconds and try again."}
        elif status == 401:
            return {"error": "Invalid API key. Check your key in the AI settings."}
        elif status == 403:
            return {"error": "API key doesn't have access. Check permissions."}
        logger.exception("LLM request failed")
        return {"error": f"API error ({status}): {e.response.text[:200]}"}
    except Exception as e:
        logger.exception("LLM request failed")
        return {"error": f"Something went wrong: {e}"}


async def _call_gemini(prompt: str, api_key: str) -> dict:
    url = PROVIDERS["gemini"]["url"]
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    for attempt in range(3):
        response = await _llm_client.post(
            url, headers={"Content-Type": "application/json"},
            params={"key": api_key}, json=payload,
        )
        if response.status_code == 429 and attempt < 2:
            await asyncio.sleep(2 ** (attempt + 1))
            continue
        response.raise_for_status()
        break

    data = response.json()
    result = _parse_json(data["candidates"][0]["content"]["parts"][0]["text"])
    usage = data.get("usageMetadata", {})
    result["_usage"] = {
        "input_tokens": usage.get("promptTokenCount", 0),
        "output_tokens": usage.get("candidatesTokenCount", 0),
        "total_tokens": usage.get("totalTokenCount", 0),
        "model": "gemini-2.5-flash",
    }
    return result


async def _call_openai(prompt: str, api_key: str) -> dict:
    url = PROVIDERS["openai"]["url"]
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    }
    response = await _llm_client.post(
        url, headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        json=payload,
    )
    response.raise_for_status()
    data = response.json()
    result = _parse_json(data["choices"][0]["message"]["content"])
    usage = data.get("usage", {})
    result["_usage"] = {
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "model": "gpt-4o-mini",
    }
    return result


async def _call_anthropic(prompt: str, api_key: str) -> dict:
    url = PROVIDERS["anthropic"]["url"]
    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}],
    }
    response = await _llm_client.post(
        url,
        headers={"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"},
        json=payload,
    )
    response.raise_for_status()
    data = response.json()
    result = _parse_json(data["content"][0]["text"])
    usage = data.get("usage", {})
    result["_usage"] = {
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        "model": "claude-sonnet-4",
    }
    return result


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"answer": text, "data": None, "r_code": None}


def main():
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
