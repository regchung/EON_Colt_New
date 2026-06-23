from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PROJECT_NAME: str = "EON COLT API"
    API_PREFIX: str = "/api"

    DATABASE_URL: str = "postgresql+psycopg://eon_colt:eon_colt_pw@db:5432/eon_colt"
    BACKEND_CORS_ORIGINS: str = "http://localhost:8080,http://localhost:5173"

    # 地理編碼 provider:'nominatim' | 'map8'
    GEOCODER_PROVIDER: str = "nominatim"
    GEOCODE_BATCH_LIMIT: int = 50     # 單次批次地理編碼最多處理的訂單數

    # Nominatim(OpenStreetMap,免費;台灣門牌覆蓋有限)
    NOMINATIM_URL: str = "https://nominatim.openstreetmap.org/search"
    GEOCODER_USER_AGENT: str = "EON-COLT/0.1 (fleet dispatch)"
    GEOCODE_RATE_SLEEP: float = 1.1   # 每次實查後等待秒數,遵守 Nominatim 速率限制

    # 圖霸 Map8(台灣本土,門牌級;需金鑰)
    MAP8_API_KEY: str = ""
    MAP8_BASE_URL: str = "https://api.map8.zone"

    # 距離矩陣 provider:'osrm'(自架,免費) | 'map8' | 'haversine'(直線,備援)
    MATRIX_PROVIDER: str = "osrm"
    OSRM_URL: str = "http://osrm:5000"

    # 文件抽取器:'native'(輕量原生 pypdf/docx/openpyxl,預設)
    #   | 'docling'(本地版面/表格抽取,PII 不出機房;需另裝 docling,見 docs/eval-docling-tenancy-timefold.md)
    EXTRACTOR: str = "native"

    # AI 派遣(Claude API)
    ANTHROPIC_API_KEY: str = ""
    AI_DISPATCH_MODEL: str = "claude-haiku-4-5-20251001"   # 快速、低成本

    # 區域親和(Zone Affinity)派遣偏好 — 同區新單優先給已在該區的司機
    ZONE_AFFINITY_ENABLED: bool = True
    ZONE_MIN_JOBS_N: int = 2          # 司機在該區達 N 筆才觸發「優先」
    ZONE_MAX_JOBS_PER_ZONE: int = 6   # 每車每區上限,避免過載失衡

    # 認證(JWT)
    SECRET_KEY: str = "change-me-in-production-please"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin123"

    # Web Push(VAPID)— 司機端推播;金鑰只放 .env
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_SUBJECT: str = "mailto:admin@eon-colt.local"

    @property
    def push_enabled(self) -> bool:
        return bool(self.VAPID_PUBLIC_KEY and self.VAPID_PRIVATE_KEY)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.BACKEND_CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
