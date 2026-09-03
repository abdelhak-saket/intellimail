"""Helper Azure OpenAI — un seul client réutilisé par tous les agents."""
import json
import os
from typing import Optional, Tuple

from openai import AzureOpenAI

from config import settings


_client: Optional[AzureOpenAI] = None


def _identifiants() -> Tuple[str, str]:
    """Endpoint et clé, lus AU MOMENT DE L'APPEL.

    L'environnement a priorité sur `settings`, qui est figé à l'import : sur
    Streamlit Community Cloud, les secrets sont injectés comme variables
    d'environnement, parfois après la construction de Settings. Lire tardivement
    évite un démarrage sans identifiants alors qu'ils sont bien présents.
    """
    endpoint = (os.getenv("AZURE_OPENAI_ENDPOINT")
                or settings.AZURE_OPENAI_ENDPOINT or "")
    cle = (os.getenv("AZURE_OPENAI_API_KEY")
           or settings.AZURE_OPENAI_API_KEY or "")
    # .strip() indispensable : un espace ou un retour à la ligne collé dans un
    # champ de secrets (Streamlit, Key Vault, variable CI) produit un 401
    # « invalid subscription key » alors que la valeur paraît correcte à l'œil.
    return endpoint.strip().rstrip("/"), cle.strip()


def empreinte_identifiants() -> dict:
    """Empreinte non sensible des identifiants, pour diagnostiquer un 401 sans
    exposer la clé : longueur, premiers et derniers caractères, présence
    d'espaces. Une longueur inattendue trahit un caractère parasite."""
    endpoint_brut = os.getenv("AZURE_OPENAI_ENDPOINT") or settings.AZURE_OPENAI_ENDPOINT or ""
    cle_brute = os.getenv("AZURE_OPENAI_API_KEY") or settings.AZURE_OPENAI_API_KEY or ""
    return {
        "endpoint": endpoint_brut.strip(),
        "endpoint_longueur": len(endpoint_brut),
        "endpoint_espaces_parasites": endpoint_brut != endpoint_brut.strip(),
        "cle_apercu": (f"{cle_brute.strip()[:4]}…{cle_brute.strip()[-4:]}"
                       if len(cle_brute.strip()) >= 8 else "(absente)"),
        "cle_longueur": len(cle_brute),
        "cle_espaces_parasites": cle_brute != cle_brute.strip(),
        "source": ("environnement" if os.getenv("AZURE_OPENAI_API_KEY")
                   else "fichier .env"),
        "deployment_classifier": settings.LLM_CLASSIFIER,
        "api_version": settings.AZURE_OPENAI_API_VERSION,
    }


def identifiants_presents() -> bool:
    """Le pipeline peut-il appeler le modèle ? (sans lever d'exception)"""
    endpoint, cle = _identifiants()
    return bool(endpoint and cle)


def get_client() -> AzureOpenAI:
    """Singleton AzureOpenAI client."""
    global _client
    endpoint, cle = _identifiants()
    if not endpoint or not cle:
        raise RuntimeError(
            "AZURE_OPENAI_ENDPOINT et AZURE_OPENAI_API_KEY ne sont pas "
            "renseignés — le pipeline ne peut pas appeler le modèle. "
            "(Normal en mode démo sans clé : l'écran HITL n'en a pas besoin.)")
    if _client is None:
        _client = AzureOpenAI(
            api_key=cle,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            azure_endpoint=endpoint,
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
