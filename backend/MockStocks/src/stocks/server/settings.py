import os

SERVER_PORT: int = int(os.getenv("STOCKS_PORT", "8090"))
JWT_SECRET: str  = os.getenv("JWT_SECRET", "")
