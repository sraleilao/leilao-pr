"""
Robô de Leilões - Paraná
Busca imóveis no Paraná com deságio > 50%, lance até R$150k, leilão em 30 dias
"""

import requests
import gspread
from google.oauth2.service_account import Credentials
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import time
import json
import os
import re
import sys
import logging

SPREADSHEET_ID = "1NEZbf37cLnq9Asf9aA76cy4Wjtn7VTLaUQ85oE-ksr0"
ABA_LEILOEIROS = "Página1"
ABA_RESULTADOS = "Resultados"

LANCE_MAXIMO   = 150_000
DESAGIO_MINIMO = 50
DIAS_LIMITE    = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout, force=True)
log = logging.getLogger(__name__)

def conectar_sheets():
    creds_json = os.environ["GOOGLE_CREDENTIALS"]
    creds_dict = json.loads(creds_json)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)

def ler_leiloeiros(sheet):
    aba = sheet.worksheet(ABA_LEILOEIROS)
    linhas = aba.get_all_records()
    return aba, linhas

def site_ativo(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        return r.status_code < 400
    except Exception:
        return False

def extrair_data(texto):
    padrao = re.search(r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})', texto or "")
    if padrao:
        dia, mes, ano = padrao.groups()
        if len(ano) == 2:
            ano = "20" + ano
        try:
            return datetime(int(ano), int(mes), int(dia))
        except Exception:
            return None
    return None

def extrair_valor(texto):
    texto = re.sub(r'[Rr]\$\s*', '', texto or "")
    texto = re.sub(r'\.', '', texto)
    texto = re.sub(r',', '.', texto)
    numeros = re.findall(r'\d+\.?\d*', texto)
    if numeros:
        try:
            return float(numeros[0])
        except Exception:
            return None
    return None

def calcular_desagio(valor_avaliacao, lance_inicial):
    if valor_avaliacao and lance_inicial and valor_avaliacao > 0:
        return ((valor_avaliacao - lance_inicial) / valor_avaliacao) * 100
    return None

def buscar_imoveis(url_site):
    resultados = []
    termos_busca = [
        "/imoveis?estado=PR", "/imoveis?uf=PR", "/imoveis/parana",
        "/lotes?categoria=imovel&estado=PR", "/busca?tipo=imovel&estado=pr",
        "/leiloes?estado=PR&tipo=imovel", "/imoveis?localidade=parana",
        "/?s=imovel+parana", "/leilao/imoveis/parana",
    ]

    hoje = datetime.today()
    limite = hoje + timedelta(days=DIAS_LIMITE)

    for termo in termos_busca:
        try:
            url = url_site.rstrip("/") + termo
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code >= 400:
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            texto_pagina = soup.get_text().lower()
            if "paraná" not in texto_pagina and "parana" not in texto_pagina:
                continue
            if "imóvel" not in texto_pagina and "imovel" not in texto_pagina and "apartamento" not in texto_pagina and "casa" not in texto_pagina and "terreno" not in texto_pagina:
                continue

            cards = soup.select(
                ".lote, .imovel, .card, .produto, .item, article, "
                "[class*='lote'], [class*='imovel'], [class*='card'], [class*='produto']"
            )

            for card in cards[:50]:
                texto_card = card.get_text(" ", strip=True)

                if "paraná" not in texto_card.lower() and "parana" not in texto_card.lower() and "/pr" not in texto_card.lower() and "- pr" not in texto_card.lower():
                    continue

                link_tag = card.find("a", href=True)
                link = link_tag["href"] if link_tag else url
                if link.startswith("/"):
                    link = url_site.rstrip("/") + link

                valores = re.findall(r'R\$\s*[\d\.,]+', texto_card)
                lance = None
                avaliacao = None
                if len(valores) >= 1:
                    lance = extrair_valor(valores[0])
                if len(valores) >= 2:
                    avaliacao = extrair_valor(valores[1])

                if lance is None or lance > LANCE_MAXIMO:
                    continue

                desagio = calcular_desagio(avaliacao, lance)
                if desagio is not None and desagio < DESAGIO_MINIMO:
                    continue

                data_leilao = extrair_data(texto_card)
                if data_leilao:
                    if not (hoje <= data_leilao <= limite):
                        continue
                    data_str = data_leilao.strftime("%d/%m/%Y")
                else:
                    data_str = "Verificar"

                titulo_tag = card.find(["h1","h2","h3","h4","strong","b"])
                titulo = titulo_tag.get_text(strip=True) if titulo_tag else texto_card[:80]

                resultados.append({
                    "Título": titulo[:120],
                    "Lance Inicial (R$)": lance,
                    "Avaliação (R$)": avaliacao,
                    "Deságio (%)": round(desagio, 1) if desagio else "N/D",
                    "Data Leilão": data_str,
                    "Link": link,
                    "Site": url_site,
                })

            if resultados:
                break

        except Exception as e:
            log.warning(f"Erro ao buscar {url_site}{termo}: {e}")
            continue

    return resultados

def atualizar_status(aba_leiloeiros, linha_idx, status):
    try:
        aba_leiloeiros.update_cell(linha_idx, 4, status)
    except Exception as e:
        log.warning(f"Erro ao atualizar status linha {linha_idx}: {e}")

def gravar_resultados(sheet, todos_resultados):
    try:
        try:
            aba = sheet.worksheet(ABA_RESULTADOS)
            aba.clear()
        except gspread.exceptions.WorksheetNotFound:
            aba = sheet.add_worksheet(title=ABA_RESULTADOS, rows=5000, cols=10)

        cabecalho = ["Título", "Lance Inicial (R$)", "Avaliação (R$)",
                     "Deságio (%)", "Data Leilão", "Link", "Site",
                     "Atualizado em"]
        aba.append_row(cabecalho)

        ordenados = sorted(
            todos_resultados,
            key=lambda x: x.get("Lance Inicial (R$)") or 999_999_999
        )

        agora = datetime.now().strftime("%d/%m/%Y %H:%M")
        linhas = []
        for item in ordenados:
            linhas.append([
                item.get("Título", ""),
                item.get("Lance Inicial (R$)", ""),
                item.get("Avaliação (R$)", ""),
                item.get("Deságio (%)", ""),
                item.get("Data Leilão", ""),
                item.get("Link", ""),
                item.get("Site", ""),
                agora,
            ])

        if linhas:
            aba.append_rows(linhas)

        log.info(f"✅ {len(linhas)} imóveis gravados na aba '{ABA_RESULTADOS}'")
    except Exception as e:
        log.error(f"Erro ao gravar resultados: {e}")

def main():
    log.info("🤖 Iniciando robô de leilões...")
    sheet = conectar_sheets()
    aba_leiloeiros, leiloeiros = ler_leiloeiros(sheet)

    todos_resultados = []
    total = len(leiloeiros)

    for i, row in enumerate(leiloeiros, start=2):
        nome = row.get("Nome", "").strip()
        url  = row.get("URL", "").strip()

        if not url:
            continue

        if not url.startswith("http"):
            url = "https://" + url

        log.info(f"[{i-1}/{total}] Verificando: {nome} ({url})")

        if not site_ativo(url):
            log.info(f"  ❌ Site fora do ar")
            atualizar_status(aba_leiloeiros, i, "NÃO")
            time.sleep(0.5)
            continue

        resultados = buscar_imoveis(url)

        if not resultados:
            log.info(f"  ⚪ Sem imóveis no PR com os critérios")
            atualizar_status(aba_leiloeiros, i, "NÃO")
        else:
            log.info(f"  ✅ {len(resultados)} imóvel(is) encontrado(s)")
            atualizar_status(aba_leiloeiros, i, "SIM")
            todos_resultados.extend(resultados)

        time.sleep(1)

    log.info(f"Total encontrado: {len(todos_resultados)} imoveis")
