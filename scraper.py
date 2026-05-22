import os
import json
import sys
import requests
import gspread
from google.oauth2.service_account import Credentials

print("Iniciando robo...", flush=True)

SPREADSHEET_ID = "1NEZbf37cLnq9Asf9aA76cy4Wjtn7VTLaUQ85oE-ksr0"

creds_json = os.environ["GOOGLE_CREDENTIALS"]
creds_dict = json.loads(creds_json)
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
client = gspread.authorize(creds)

print("Conectado ao Google!", flush=True)

sheet = client.open_by_key(SPREADSHEET_ID)
aba = sheet.worksheet("Página1")
linhas = aba.get_all_records()

print(f"Leiloeiros encontrados: {len(linhas)}", flush=True)

for i, row in enumerate(linhas[:3]):
    print(f"  - {row}", flush=True)

print("Teste concluido!", flush=True)
