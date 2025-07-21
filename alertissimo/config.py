from dotenv import load_dotenv
import streamlit as st
import os

# Load values from .env into environment
load_dotenv()

# Access tokens and credentials
LASAIR_TOKEN = st.secrets["LASAIR_TOKEN"]
FINK_USER = st.secrets("FINK_USER")
FINK_PASS = st.secrets("FINK_PASS")

DEFAULT_TIMEOUT = 30  # seconds
