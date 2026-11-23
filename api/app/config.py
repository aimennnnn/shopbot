"""All settings come from environment variables (see .env.example)."""
import os

DATABASE_URL = os.getenv("DATABASE_URL", "")
MODEL = os.getenv("MODEL", "claude-haiku-5-5")
SHOP_NAME = os.getenv("SHOP_NAME", "Dastkari")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

# Cost controls
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "300"))
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "20"))
MAX_MESSAGE_CHARS = 1500
MAX_AGENT_STEPS = 12  # LangGraph recursion limit per turn
