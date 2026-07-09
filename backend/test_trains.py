import asyncio
from dotenv import load_dotenv
load_dotenv()  # must run BEFORE importing the service so it sees RAPIDAPI_KEY

from services.irctc_train_service import irctc_train_service