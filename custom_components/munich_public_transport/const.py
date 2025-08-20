DOMAIN = "munich_public_transport"
DEFAULT_SCAN_INTERVAL = 1
DEFAULT_DEPARTURE_COUNT = 5

# Rate limiting constants
MAX_RETRIES = 3
BASE_RETRY_DELAY = 2  # seconds
MAX_RETRY_DELAY = 300  # 5 minutes
RATE_LIMIT_CACHE_DURATION = 900  # 15 minutes