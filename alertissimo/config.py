from dotenv import load_dotenv
import os

# Load values from .env into environment
load_dotenv()

# Access tokens and credentials
LASAIR_TOKEN = os.getenv("LASAIR_TOKEN")
FINK_USER = os.getenv("FINK_USER")
FINK_PASS = os.getenv("FINK_PASS")

DEFAULT_TIMEOUT = 30  # seconds
