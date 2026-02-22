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

    # App
    environment: str = "development"
    api_url: str = "http://localhost:8000"

    # Plan limits
    free_project_limit: int = 3
    free_sources_per_project: int = 10
    pro_sources_per_project: int = 50
    team_sources_per_project: int = 100


settings = Settings()
