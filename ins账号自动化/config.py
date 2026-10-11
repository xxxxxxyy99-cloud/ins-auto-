"""Configuration — loads .env and exports constants."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

PACKAGE_DIR = Path(__file__).resolve().parent

# Load .env from: project data/, project root, or package data/
for p in [BASE_DIR / "data" / ".env", BASE_DIR / ".env", PACKAGE_DIR / "data" / ".env"]:
    if p.exists():
        load_dotenv(p)
        break

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "your-openrouter-api-key-here")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
IG_USERNAME = os.getenv("IG_USERNAME", "your-instagram-username")
IG_PASSWORD = os.getenv("IG_PASSWORD", "your-instagram-password")
