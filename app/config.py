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
    LUMX_PARTNER_FEE_ID: str = ""
    LUMX_WEBHOOK_SECRET: str
    LUMX_TREASURY_WALLET: str = ""
    # Optional: leave empty to use the project's default blockchain.
    LUMX_BLOCKCHAIN: str = ""   # ETHEREUM | POLYGON | BASE | TRON | STELLAR

    # App
    # Comma-separated list is allowed, e.g.
    #   https://agilepay-rosy.vercel.app,https://agilepay-git-main.vercel.app
    FRONTEND_URL: str = "http://localhost:3000"
    ENV: str = "development"

    class Config:
        env_file = ".env"

    @property
    def cors_origins(self) -> list[str]:
        """Exact browser origins allowed to call the API (no trailing slash)."""
        return [
            origin.strip().rstrip("/")
            for origin in self.FRONTEND_URL.split(",")
            if origin.strip()
        ]


settings = Settings()
