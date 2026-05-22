import os
import json
import re
import time
import requests
import gspread
from google.oauth2.service_account import Credentials
from bs4 import BeautifulSoup
from datetime import datetime

print("Iniciando robo de leiloes...", flush=True)

SPREADSHEET_ID = "1NEZbf37cLnq9Asf9aA76cy4Wjtn7VTLaUQ85oE-ksr0"
ABA_LEILOEIROS = "Pagina1"
ABA_RESULTADOS = "Resultados"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}

TERMOS_BUSCA = [
    "/imoveis?estado=PR",
    "/imoveis?uf=PR",
    "/imoveis/parana",
    "/imoveis/pr",
    "/lotes?estado=PR",
    "/busca?estado=PR",
    "/leiloes?estado=PR",
    "/?s=parana",
    "/parana",
    "/pr",
]

PALAVRAS_IMOVEL = ["imovel","imóvel","apartamento","casa","terreno","sitio","sítio","chacara","chácara","lote","sala","galpao","galpão"]
PALAVRAS_PR = ["paraná","parana"," pr ","(pr)","- pr","/pr"]

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
    except Exception:
        return False

def extrair_valor(texto):
    texto = re.sub(r'[Rr]\$\s*', '', texto or "")
    texto = re.sub(r'\.', '', texto)
    texto = re.sub(r',', '.', texto)
    nums = re.findall(r'\d+\.?\d*', texto)
    try:
        v = float(nums[0]) if nums else None
        if v and v > 1000:
            return v
        return None
    except Exception:
        return None

def extrair_data(texto):
    m = re.search(r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})', texto or "")
    if m:
        d, mo, a = m.groups()
        if len(a) == 2:
            a = "20" + a
        try:
            return datetime(int(a), int(mo), int(d)).strftime("%d/%m/%Y")
        except Exception:
            return "Verificar"
    return "Verificar"

def buscar_imoveis(url_site):
    resultados = []

    for termo in TERMOS_BUSCA:
        try:
            url = url_site.rstrip("/") + termo
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code >= 400:
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            texto_pagina = soup.get_text().lower()

            tem_pr = any(p in texto_pagina for p in PALAVRAS_PR)
            tem_imovel = any(p in texto_pagina for p in PALAVRAS_IMOVEL)

            if not tem_pr or not tem_imovel:
                continue

            cards = soup.select(
                ".lote, .imovel, .card, .produto, .item, article, "
                "[class*='lote'], [class*='imovel'], [class*='card'], [class*='produto'], "
                "[class*='item'], [class*='result']"
            )

            if not cards:
                cards = soup.find_all(["article", "li", "div"], limit=100)

            for card in cards[:100]:
                texto = card.get_text(" ", strip=True).lower()

                tem_pr_card = any(p in texto for p in PALAVRAS_PR)
                tem_imovel_card = any(p in texto for p in PALAVRAS_IMOVEL)

                if not tem_pr_card or not tem_imovel_card:
                    continue

                link_tag = card.find("a", href=True)
                link = link_tag["href"] if link_tag else url
                if link.startswith("/"):
                    link = url_site.rstrip("/") + link

                valores = re.findall(r'R\$\s*[\d\.,]+', card.get_text())
                lance = extrair_valor(valores[0]) if valores else None

                titulo_tag = card.find(["h1","h2","h3","h4","strong","b"])
                titulo = titulo_tag.get_text(strip=True) if titulo_tag else card.get_text(" ", strip=True)[:80]

                data_str = extrair_data(card.get_text())

                resultados.append({
                    "Titulo": titulo[:120],
                    "Lance": lance,
                    "Data": data_str,
                    "Link": link,
                    "Site": url_site,
                })

            if resultados:
                break

        except Exception as e:
            print(f"  Erro: {e}", flush=True)
            continue

    return resultados

def gravar_resultados(sheet, todos):
    try:
        try:
            aba = sheet.worksheet(ABA_RESULTADOS)
            aba.clear()
        except gspread.exceptions.WorksheetNotFound:
            aba = sheet.add_worksheet(title=ABA_RESULTADOS, rows=10000, cols=8)

        cabecalho = ["Titulo", "Lance Inicial (R$)", "Data Leilao", "Link", "Site", "Atualizado em"]
        aba.append_row(cabecalho)

        ordenados = sorted(todos, key=lambda x: x.get("Lance") or 999999999)

        agora = datetime.now().strftime("%d/%m/%Y %H:%M")
        linhas = [
            [i["Titulo"], i["Lance"] or "Verificar", i["Data"], i["Link"], i["Site"], agora]
            for i in ordenados
        ]

        if linhas:
            aba.append_rows(linhas)

        print(f"{len(linhas)} imoveis gravados na aba Resultados!", flush=True)
    except Exception as e:
        print(f"Erro ao gravar: {e}", flush=True)

# MAIN
sheet = conectar_sheets()
print("Conectado ao Google Sheets!", flush=True)

aba_leiloeiros = sheet.worksheet(ABA_LEILOEIROS)
leiloeiros = aba_leiloeiros.get_all_records()
print(f"Total de leiloeiros: {len(leiloeiros)}", flush=True)

todos_resultados = []

for i, row in enumerate(leiloeiros, start=2):
    nome = str(row.get("Nome","")).strip()
    url  = str(row.get("URL","")).strip()

    if not url:
        continue
    if not url.startswith("http"):
        url = "https://" + url

    print(f"[{i-1}/{len(leiloeiros)}] {nome}", flush=True)

    if not site_ativo(url):
        print(f"  Fora do ar", flush=True)
        aba_leiloeiros.update_cell(i, 4, "NAO")
        time.sleep(0.5)
        continue

    resultados = buscar_imoveis(url)

    if resultados:
        print(f"  {len(resultados)} imovel(is) encontrado(s)!", flush=True)
        aba_leiloeiros.update_cell(i, 4, "SIM")
        todos_resultados.extend(resultados)
    else:
        print(f"  Sem imoveis no PR", flush=True)
        aba_leiloeiros.update_cell(i, 4, "NAO")

    time.sleep(1)

print(f"Total encontrado: {len(todos_resultados)} imoveis", flush=True)
gravar_resultados(sheet, todos_resultados)
print("Robo finalizado!", flush=True)
