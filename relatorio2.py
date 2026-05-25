import os
import json
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

print("Gerando relatorio Top 10...", flush=True)

SPREADSHEET_ID = "1NEZbf37cLnq9Asf9aA76cy4Wjtn7VTLaUQ85oE-ksr0"
ABA_RESULTADOS = "Resultados"
ABA_RELATORIO  = "Top10"

def conectar_sheets():
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)

def extrair_float(val):
    try:
        if val in (None, "", "N/D", "Verificar"):
            return None
        return float(str(val).replace(",",".").replace("%",""))
    except Exception:
        return None

sheet = conectar_sheets()
print("Conectado ao Google Sheets!", flush=True)

aba   = sheet.worksheet(ABA_RESULTADOS)
dados = aba.get_all_records()
print(f"Total de registros na aba Resultados: {len(dados)}", flush=True)

# Preparar dados
imoveis = []
for row in dados:
    lance    = extrair_float(row.get("Lance Inicial (R$)"))
    desagio  = extrair_float(row.get("Desagio (%)"))
    if not lance:
        continue
    imoveis.append({
        "Titulo":    row.get("Titulo",""),
        "Estado":    row.get("Estado",""),
        "Lance":     lance,
        "Avaliacao": extrair_float(row.get("Avaliacao (R$)")),
        "Desagio":   desagio,
        "Data":      row.get("Data Leilao",""),
        "Link":      row.get("Link do Anuncio",""),
    })

print(f"Imoveis com lance valido: {len(imoveis)}", flush=True)

if not imoveis:
    print("Nenhum imovel com lance valido encontrado!", flush=True)
    exit(0)

# Top 10 por maior deságio
top_desagio = sorted(
    [x for x in imoveis if x["Desagio"] is not None],
    key=lambda x: x["Desagio"],
    reverse=True
)[:10]

# Top 10 combinado: pontuação = 60% deságio + 40% menor lance
max_lance   = max(x["Lance"] for x in imoveis)
max_desagio = max((x["Desagio"] or 0) for x in imoveis) or 1

for x in imoveis:
    nota_desagio = (x["Desagio"] or 0) / max_desagio
    nota_lance   = 1 - (x["Lance"] / max_lance)
    x["Score"]   = (nota_desagio * 0.6) + (nota_lance * 0.4)

top_combinado = sorted(imoveis, key=lambda x: x.get("Score", 0), reverse=True)[:10]

# Gravar aba Top10
try:
    aba_top = sheet.worksheet(ABA_RELATORIO)
    aba_top.clear()
except gspread.exceptions.WorksheetNotFound:
    aba_top = sheet.add_worksheet(title=ABA_RELATORIO, rows=100, cols=8)

agora = datetime.now().strftime("%d/%m/%Y %H:%M")

# Cabeçalho geral
aba_top.append_row([f"RELATÓRIO TOP 10 DE IMÓVEIS EM LEILÃO — Gerado em {agora}"])
aba_top.append_row([f"Total de imóveis encontrados: {len(imoveis)}"])
aba_top.append_row([])

# Seção 1: Maior Deságio
aba_top.append_row(["TOP 10 — MAIOR DESÁGIO"])
aba_top.append_row(["#", "Título", "Estado", "Lance (R$)", "Avaliação (R$)", "Deságio (%)", "Data Leilão", "Link"])
for idx, r in enumerate(top_desagio, 1):
    aba_top.append_row([
        idx,
        r["Titulo"][:100],
        r["Estado"],
        r["Lance"],
        r["Avaliacao"] or "N/D",
        f"{r['Desagio']}%",
        r["Data"],
        r["Link"],
    ])

aba_top.append_row([])
aba_top.append_row([])

# Seção 2: Combinado
aba_top.append_row(["TOP 10 — MELHOR COMBINAÇÃO (maior deságio + menor lance)"])
aba_top.append_row(["#", "Título", "Estado", "Lance (R$)", "Avaliação (R$)", "Deságio (%)", "Data Leilão", "Link"])
for idx, r in enumerate(top_combinado, 1):
    aba_top.append_row([
        idx,
        r["Titulo"][:100],
        r["Estado"],
        r["Lance"],
        r["Avaliacao"] or "N/D",
        f"{r['Desagio']}%" if r["Desagio"] else "N/D",
        r["Data"],
        r["Link"],
    ])

print(f"Top 10 gerado com sucesso na aba '{ABA_RELATORIO}'!", flush=True)
