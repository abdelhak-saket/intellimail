"""Configuration centralisée — Pydantic Settings."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Azure OpenAI
    # Valeurs par défaut vides — volontaire : l'écran HITL et la démo publique
    # doivent démarrer sans identifiants (ils ne font aucun appel LLM). Un appel
    # au pipeline sans ces variables échouera explicitement dans llm.py.
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_API_VERSION: str = "2024-08-01-preview"

    # Deployments (par agent)
    LLM_CLASSIFIER: str = "gpt-4.1-mini"
    LLM_DRAFTER: str = "gpt-4.1-mini"
    LLM_CRITIC: str = "gpt-4.1-mini"

    # Workflow
    MAX_DRAFTER_RETRIES: int = 2
    CRITIC_APPROVE_THRESHOLD: float = 0.75
    SEUIL_AUTO: float = 0.85
    SEUIL_HITL: float = 0.70

    # Règles déterministes — catégories à HITL forcé quel que soit le score
    # (appliquées en sortie de judge, avant la décision finale — voir rules.py)
    # spam  : répondre à un phishing confirme au fraudeur que l'adresse est active
    # autre : le classifieur n'a pas su décider → on n'envoie jamais
    HITL_FORCE_CATEGORIES: str = ("reclamation,resiliation,donnees_personnelles,"
                                  "spam,autre")

    # Priorités à HITL forcé — une urgence n'est jamais traitée par un robot
    HITL_FORCE_PRIORITIES: str = "haute"

    # Détection d'opérations sensibles par regex (table dans rules.py)
    SENSITIVE_RULES_ENABLED: bool = True

    # Garde-fou de SORTIE : inspecte le brouillon produit (anti-injection)
    OUTPUT_GUARDRAIL_ENABLED: bool = True

    # Entrée dégénérée : corps < N caractères utiles → HITL direct, zéro appel LLM
    DEGENERATE_MIN_CHARS: int = 15

    # Coût estimé (USD / 1M tokens) — défauts gpt-4.1-mini
    PRICE_INPUT_PER_1M: float = 0.40
    PRICE_OUTPUT_PER_1M: float = 1.60

    # Idempotence par message-id (cache en mémoire)
    IDEMPOTENCY_TTL_S: int = 3600
    IDEMPOTENCY_MAX_ENTRIES: int = 1000

    # RAG — ChromaDB (researcher). Corpus : corpus/*.md, ingéré par ingest_corpus.py
    CHROMA_DIR: str = "chroma_db"
    RAG_TOP_K: int = 3
    # Vide → embedding local par défaut de ChromaDB (all-MiniLM-L6-v2).
    # Sinon nom d'un deployment Azure OpenAI embeddings (ex. text-embedding-3-small).
    EMBEDDING_DEPLOYMENT: str = ""

    @property
    def hitl_force_set(self) -> set:
        return {c.strip().lower() for c in self.HITL_FORCE_CATEGORIES.split(",") if c.strip()}

    @property
    def hitl_force_priority_set(self) -> set:
        return {p.strip().lower() for p in self.HITL_FORCE_PRIORITIES.split(",") if p.strip()}

    # Server
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    LOG_LEVEL: str = "info"

    # Clé d'API — vide = désactivée (usage local).
    # OBLIGATOIRE dès que l'API est exposée par un tunnel (Copilot Studio,
    # Power Automate) : sans elle, l'URL publique est ouverte à tous.
    API_KEY: str = ""


settings = Settings()
