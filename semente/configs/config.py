import os
from pathlib import Path
from dotenv import load_dotenv

# Ollama is imported lazily inside the model properties so the framework works
# without the `ollama` package installed (it's only needed for the ollama provider).

# Sets the project base path (where the .env usually lives)
BASE_DIR = Path.cwd()

# Loads the .env file variables into the environment
load_dotenv(dotenv_path=BASE_DIR / ".env")


class BaseConfig:
    """Common settings for all environments."""
    APP_ENV: str = os.getenv("APP_ENV", "development")

    ARGO_APP_NAME: str = os.getenv("ARGO_APP_NAME", "Semente App")

    DATABASE_TYPE: str = os.getenv("DATABASE_TYPE", "sqlite")

    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", None)
    POSTGRES_PORT: str = os.getenv("POSTGRES_PORT", None)
    POSTGRES_DBNAME: str = os.getenv("POSTGRES_DBNAME", None)
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", None)
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", None)

    PGVECTOR_HOST: str = os.getenv("PGVECTOR_HOST", None)
    PGVECTOR_PORT: str = os.getenv("PGVECTOR_PORT", None)
    PGVECTOR_DBNAME: str = os.getenv("PGVECTOR_DBNAME", None)
    PGVECTOR_USER: str = os.getenv("PGVECTOR_USER", None)
    PGVECTOR_PASSWORD: str = os.getenv("PGVECTOR_PASSWORD", None)

    WHATSAPP_ACCESS_TOKEN: str = os.getenv("WHATSAPP_ACCESS_TOKEN", None)
    WHATSAPP_VERIFY_TOKEN: str = os.getenv("WHATSAPP_VERIFY_TOKEN", None)
    WHATSAPP_WEBHOOK_URL: str = os.getenv("WHATSAPP_WEBHOOK_URL", None)
    WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", None)
    WHATSAPP_APP_SECRET: str = os.getenv("WHATSAPP_APP_SECRET", None)

    # Optional geospatial (GEE) — only required by the [gee] extra / domain.
    GEE_PROJECT: str = os.getenv("GEE_PROJECT", None)
    GEE_SERVICE_ACCOUNT: str = os.getenv("GEE_SERVICE_ACCOUNT", None)
    GEE_KEY_FILE: str = os.getenv("GEE_KEY_FILE", None)

    PRIMARY_MODEL_PROVIDER: str = os.getenv("PRIMARY_MODEL_PROVIDER", "google")
    PRIMARY_MODEL_ID: str = os.getenv("PRIMARY_MODEL_ID", "gemini-3.5-flash-lite")

    FALLBACK_MODEL_PROVIDER: str = os.getenv("FALLBACK_MODEL_PROVIDER")
    FALLBACK_MODEL_ID: str = os.getenv("FALLBACK_MODEL_ID")

    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", None)

    OLLAMA_API_KEY: str = os.getenv("OLLAMA_API_KEY", None)
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", None)

    S3_ENDPOINT_URL: str = os.getenv("S3_ENDPOINT_URL", None)
    S3_ACCESS_KEY: str = os.getenv("S3_ACCESS_KEY", None)
    S3_SECRET_KEY: str = os.getenv("S3_SECRET_KEY", None)
    S3_BUCKET: str = os.getenv("S3_BUCKET", "semente")
    S3_REGION: str = os.getenv("S3_REGION", None)

    # Directory holding the app's localized/domain prompt YAML files.
    SEMENTE_PROMPTS_DIR: str = os.getenv("SEMENTE_PROMPTS_DIR", None)

    def __init__(self):
        if self.PRIMARY_MODEL_PROVIDER == "ollama":
            if self.OLLAMA_API_KEY is None:
                raise ValueError("OLLAMA_API_KEY environment variables must be set.")


class DevelopmentConfig(BaseConfig):
    """Settings specific to Development."""
    DEBUG_MODE: bool = True


class ProductionConfig(BaseConfig):
    """Settings specific to Production."""
    DEBUG_MODE: bool = False

    def __init__(self):
        super().__init__()
        if self.POSTGRES_HOST is None:
            raise ValueError("POSTGRES_HOST environment variables must be set.")
        if self.POSTGRES_PORT is None:
            raise ValueError("POSTGRES_PORT environment variables must be set.")
        if self.POSTGRES_DBNAME is None:
            raise ValueError("POSTGRES_DBNAME environment variables must be set.")
        if self.POSTGRES_USER is None:
            raise ValueError("POSTGRES_USER environment variables must be set.")
        if self.POSTGRES_PASSWORD is None:
            raise ValueError("POSTGRES_PASSWORD environment variables must be set.")

        if self.WHATSAPP_ACCESS_TOKEN is None:
            raise ValueError("WHATSAPP_ACCESS_TOKEN environment variables must be set.")
        if self.WHATSAPP_VERIFY_TOKEN is None:
            raise ValueError("WHATSAPP_VERIFY_TOKEN environment variables must be set.")
        if self.WHATSAPP_WEBHOOK_URL is None:
            raise ValueError("WHATSAPP_WEBHOOK_URL environment variables must be set.")
        if self.WHATSAPP_PHONE_NUMBER_ID is None:
            raise ValueError("WHATSAPP_PHONE_NUMBER_ID environment variables must be set.")
        if self.WHATSAPP_APP_SECRET is None:
            raise ValueError("WHATSAPP_APP_SECRET environment variables must be set.")

        if self.S3_ENDPOINT_URL is None:
            raise ValueError("S3_ENDPOINT_URL environment variables must be set.")
        if self.S3_ACCESS_KEY is None:
            raise ValueError("S3_ACCESS_KEY environment variables must be set.")
        if self.S3_SECRET_KEY is None:
            raise ValueError("S3_SECRET_KEY environment variables must be set.")


class StaggingConfig(ProductionConfig):
    """Settings specific to Staging."""
    DEBUG_MODE: bool = True


# Mapping dictionary of the environments
config_map = {
    "production": ProductionConfig,
    "development": DevelopmentConfig,
    "stagging": StaggingConfig,
}

env_app = os.getenv("APP_ENV", "development").lower()

if env_app not in ["production", "development", "stagging"]:
    raise ValueError("APP_ENV has to be 'production', 'development' or 'stagging'.")

# Instantiates the correct configuration class
config: BaseConfig = config_map[env_app]()

from semente.configs.logging_config import setup_logging  # noqa: E402

setup_logging(config)
