import os
import json
import sys
import re
import time
import requests
import gspread
from google.oauth2.service_account import Credentials
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

print("Iniciando robo de leiloes...", flush=True)

SPREADSHEET_ID = "1NEZbf37cLnq9Asf9aA76cy4Wjtn7VTLaUQ85oE-ksr0"
ABA_LEILOEIROS = "Página1"
ABA_RESULTADOS = "Resultados"
LANCE_MAXIMO   = 150000
DESAGIO_MINIMO = 50
DIAS_LIMITE    = 30

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}

def conectar_sheets():
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)

def site_ativo(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        return r.status_code < 400
    except:
        return False

def extrair_valor(texto):
    texto = re.sub(r'[Rr]\$\s*', '', texto or "")
    texto = re.sub(r'\.', '', texto)
    texto = re.sub(r',', '.', texto)
    nums = re.findall(r'\d+\.?\d*', texto)
    try:
        return float(nums[0]) if nums else None
    except:
        return None

def extrair_data(texto):
    m = re.search(r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})', texto or "")
    if m:
        d, mo, a = m.groups()
        if len(a) == 2: a = "20" + a
        try:
            return datetime(int(a), int(mo), int(d))
        except:
            return None
    return None

def buscar_imoveis(url_site):
    resultados = []
    termos = [
        "/imoveis?estado=PR", "/imoveis?uf=PR", "/imoveis/parana",
        "/lotes?categoria=imovel&estado=PR", "/busca?tipo=imovel&estado=pr",
        "/leiloes?estado=PR&tipo=imovel", "/?s=imovel+parana",
    ]
    hoje = datetime.today()
    limite = hoje + timedelta(days=DIAS_LIMITE)

    for termo in termos:
        try:
            url = url_site.rstrip("/") + termo
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code >= 400:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            texto_pagina = soup.get_text().lower()
            if "parana" not in texto_pagina and "paraná" not in texto_pagina:
                continue
            if not any(x in texto_pagina for x in ["imovel","imóvel","apartamento","casa","terreno"]):
                continue
            cards = soup.select(".lote,.imovel,.card,.produto,.item,article,[class*='lote'],[class*='imovel'],[class*='card']")
            for card in cards[:50]:
                texto = card.get_text(" ", strip=True)
                if not any(x in texto.lower() for x in ["paraná","parana","/pr","- pr"]):
                    continue
                link_tag = card.find("a", href=True)
                link = link_tag["href"] if link_tag else url
                if link.startswith("/"):
                    link = url_site.rstrip("/") + link
                valores = re.findall(r'R\$\s*[\d\.,]+', texto)
                lance = extrair_valor(valores[0]) if len(valores) >= 1 else None
                avaliacao = extrair_valor(valores[1]) if len(valores) >= 2 else None
                if lance is None or lance > LANCE_MAXIMO:
                    continue
                desagio = ((avaliacao - lance) / avaliacao * 100) if avaliacao and avaliacao > 0 else None
                if desagio is not None and desagio < DESAGIO_MINIMO:
                    continue
                data_leilao = extrair_data(texto)
                if data_leilao:
                    if not (hoje <= data_leilao <= limite):
                        continue
                    data_str = data_leilao.strftime("%d/%m/%Y")
                else:
                    data_str = "Verificar"
                titulo_tag = card.find(["h1","h2","h3","h4","strong","b"])
                titulo = titulo_tag.get_text(strip=True) if titulo_tag else texto[:80]
                resultados.append({
                    "Titulo": titulo[:120],
                    "Lance": lance,
                    "Avaliacao": avalia
