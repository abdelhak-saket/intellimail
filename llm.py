"""Helper Azure OpenAI — un seul client réutilisé par tous les agents."""
import json
from typing import Optional

from openai import AzureOpenAI

from config import settings


_client: Optional[AzureOpenAI] = None


def get_client() -> AzureOpenAI:
    """Singleton AzureOpenAI client."""
    global _client
    if _client is None:
        _client = AzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        )
    return _client


def _track_usage(resp, usage_sink: Optional[dict]) -> None:
    """Accumule prompt/completion tokens dans le sink (dict partagé du state)."""
    if usage_sink is None or not getattr(resp, "usage", None):
        return
    usage_sink["tokens_in"] = usage_sink.get("tokens_in", 0) + (resp.usage.prompt_tokens or 0)
    usage_sink["tokens_out"] = usage_sink.get("tokens_out", 0) + (resp.usage.completion_tokens or 0)
    usage_sink["llm_calls"] = usage_sink.get("llm_calls", 0) + 1


def chat_json(deployment: str, system: str, user: str, *,
              temperature: float = 0.0, max_tokens: int = 800,
              usage_sink: Optional[dict] = None) -> dict:
    """Appel chat-completion avec response_format=json_object.

    Retourne le dict parsé depuis le JSON du modèle.
    Lève si la réponse n'est pas du JSON valide.
    """
    client = get_client()
    resp = client.chat.completions.create(
        model=deployment,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    _track_usage(resp, usage_sink)
    content = resp.choices[0].message.content
    if not content:
        raise ValueError("LLM a renvoyé un contenu vide")
    return json.loads(content)


def chat_text(deployment: str, system: str, user: str, *,
              temperature: float = 0.3, max_tokens: int = 600,
              usage_sink: Optional[dict] = None) -> str:
    """Appel chat-completion sans contrainte JSON — pour la rédaction."""
    client = get_client()
    resp = client.chat.completions.create(
        model=deployment,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    _track_usage(resp, usage_sink)
    return (resp.choices[0].message.content or "").strip()
