from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://synthiq:synthiq_dev@localhost:5432/synthiq"
    database_url_sync: str = "postgresql://synthiq:synthiq_dev@localhost:5432/synthiq"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Clerk
    clerk_secret_key: str = ""
    clerk_publishable_key: str = ""

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"
    voice_analysis_model: str = "claude-sonnet-4-6"

    # Voyage AI (embeddings)
    voyage_api_key: str = ""
    voyage_model: str = "voyage-3"
    voyage_dimensions: int = 1024

    # Pinecone
    pinecone_api_key: str = ""
    pinecone_index_name: str = "synthiq-chunks"
    pinecone_environment: str = "us-east-1"

    # AWS S3
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_s3_bucket: str = "synthiq-sources"
    aws_region: str = "us-east-1"

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_professional: str = ""   # Stripe Price ID for Professional plan
    stripe_price_team: str = ""           # Stripe Price ID for Team plan

    # App
    environment: str = "development"
    api_url: str = "http://localhost:8000"

    # Ingestion pipeline
    chunk_target_chars: int = 2000   # ~512 tokens
    chunk_overlap_chars: int = 200
    entity_batch_size: int = 10      # chunks per Claude Haiku call
    embed_batch_size: int = 96       # texts per Voyage AI call
    pinecone_upsert_batch: int = 100 # vectors per Pinecone batch

    # Plan limits
    free_project_limit: int = 3
    free_sources_per_project: int = 10
    pro_sources_per_project: int = 50
    team_sources_per_project: int = 100


settings = Settings()
