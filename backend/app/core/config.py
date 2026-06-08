from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PROJECT_NAME: str = "SmartCar API"
    API_PREFIX: str = "/api"

    DATABASE_URL: str = "postgresql+psycopg://smartcar:smartcar_pw@db:5432/smartcar"
    BACKEND_CORS_ORIGINS: str = "http://localhost:8080,http://localhost:5173"

    # 地理編碼 provider:'nominatim' | 'map8'
    GEOCODER_PROVIDER: str = "nominatim"
    GEOCODE_BATCH_LIMIT: int = 50     # 單次批次地理編碼最多處理的訂單數

    # Nominatim(OpenStreetMap,免費;台灣門牌覆蓋有限)
    NOMINATIM_URL: str = "https://nominatim.openstreetmap.org/search"
    GEOCODER_USER_AGENT: str = "SmartCar/0.1 (fleet dispatch)"
    GEOCODE_RATE_SLEEP: float = 1.1   # 每次實查後等待秒數,遵守 Nominatim 速率限制

    # 圖霸 Map8(台灣本土,門牌級;需金鑰)
    MAP8_API_KEY: str = ""
    MAP8_BASE_URL: str = "https://api.map8.zone"

    # 距離矩陣 provider:'osrm'(自架,免費) | 'map8' | 'haversine'(直線,備援)
    MATRIX_PROVIDER: str = "osrm"
    OSRM_URL: str = "http://osrm:5000"

    # 認證(JWT)
    SECRET_KEY: str = "change-me-in-production-please"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin123"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.BACKEND_CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
