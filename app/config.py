from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str

    # Supabase
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str
    SUPABASE_JWT_SECRET: str  # Settings → API → JWT Secret in Supabase dashboard

    # Lumx
    LUMX_API_KEY: str
    LUMX_BASE_URL: str = "https://api-sandbox.lumx.io"
    LUMX_PARTNER_FEE_ID: str
    LUMX_WEBHOOK_SECRET: str
    LUMX_TREASURY_WALLET: str

    # App
    FRONTEND_URL: str = "http://localhost:3000"
    ENV: str = "development"

    class Config:
        env_file = ".env"


settings = Settings()
