from dotenv import load_dotenv
import streamlit as st
import os

# Load values from .env into environment
load_dotenv()

# Access tokens and credentials
LASAIR_TOKEN = st.secrets["LASAIR_TOKEN"]
FINK_USERNAME = st.secrets("FINK_USERNAME")
FINK_GROUP_ID = st.secrets("FINK_GROUP_ID")

DEFAULT_TIMEOUT = 30  # seconds
