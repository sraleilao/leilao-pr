import os
import json
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

print("Gerando relatorio...", flush=True)

SPREADSHEET_ID = "1NEZbf37cLnq9Asf9aA76cy4Wjtn7VTLaUQ85oE-ksr0"
ABA_RESULTADOS = "Resultados"
ABA_RELATORIO  = "Top10"
ABA_AUDITORIA  = "Auditoria"

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
print("Conectado!", flush=True)

agora = datetime.now().strftime("%d/%m/%Y %H:%M")

# ── TOP 10 ────────────────────────────────────────────────────────────────────
aba   = sheet.worksheet(ABA_RESULTADOS)
dados = aba.get_all_records()
print(f"Registros: {len(dados)}", flush=True)

imoveis = []
for row in dados:
    lance   = extrair_float(row.get("Lance Inicial (R$)"))
    desagio = extrair_float(row.get("Desagio (%)"))
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

print(f"Imoveis com lance: {len(imoveis)}", flush=True)

try:
    aba_top = sheet.worksheet(ABA_RELATORIO)
    aba_top.clear()
except gspread.exceptions.WorksheetNotFound:
    aba_top = sheet.add_worksheet(title=ABA_RELATORIO, rows=100, cols=8)

if imoveis:
    top_desagio = sorted(
        [x for x in imoveis if x["Desagio"] is not None],
        key=lambda x: x["Desagio"], reverse=True
    )[:10]

    max_lance   = max(x["Lance"] for x in imoveis)
    max_desagio = max((x["Desagio"] or 0) for x in imoveis) or 1
    for x in imoveis:
        nota_desagio = (x["Desagio"] or 0) / max_desagio
        nota_lance   = 1 - (x["Lance"] / max_lance)
        x["Score"]   = (nota_desagio * 0.6) + (nota_lance * 0.4)
    top_combinado = sorted(imoveis, key=lambda x: x.get("Score",0), reverse=True)[:10]

    aba_top.append_row([f"RELATORIO TOP 10 — Gerado em {agora}"])
    aba_top.append_row([f"Total de imoveis encontrados: {len(imoveis)}"])
    aba_top.append_row([])
    aba_top.append_row(["TOP 10 — MAIOR DESAGIO"])
    aba_top.append_row(["#","Titulo","Estado","Lance (R$)","Avaliacao (R$)","Desagio (%)","Data Leilao","Link"])
    for idx, r in enumerate(top_desagio, 1):
        aba_top.append_row([idx, r["Titulo"][:100], r["Estado"], r["Lance"], r["Avaliacao"] or "N/D", f"{r['Desagio']}%", r["Data"], r["Link"]])

    aba_top.append_row([])
    aba_top.append_row([])
    aba_top.append_row(["TOP 10 — MELHOR COMBINACAO (maior desagio + menor lance)"])
    aba_top.append_row(["#","Titulo","Estado","Lance (R$)","Avaliacao (R$)","Desagio (%)","Data Leilao","Link"])
    for idx, r in enumerate(top_combinado, 1):
        aba_top.append_row([idx, r["Titulo"][:100], r["Estado"], r["Lance"], r["Avaliacao"] or "N/D", f"{r['Desagio']}%" if r["Desagio"] else "N/D", r["Data"], r["Link"]])

    print("Top10 gerado!", flush=True)
else:
    aba_top.append_row([f"RELATORIO — Gerado em {agora}"])
    aba_top.append_row(["Nenhum imovel com lance valido encontrado."])

# ── AUDITORIA ─────────────────────────────────────────────────────────────────
print("Gerando aba Auditoria...", flush=True)

try:
    aba_aud = sheet.worksheet(ABA_AUDITORIA)
    aba_aud.clear()
except gspread.exceptions.WorksheetNotFound:
    aba_aud = sheet.add_worksheet(title=ABA_AUDITORIA, rows=5000, cols=4)

aba_aud.append_row([f"AUDITORIA DE SITES — Ultima verificacao: {agora}"])
aba_aud.append_row([])
aba_aud.append_row(["Nome","URL","Classificacao","Aba"])

abas_nomes = ["Leiloeiros1","Leiloeiros2","Leiloeiros3"]
linhas_auditoria = []

for nome_aba in abas_nomes:
    try:
        aba_leil = sheet.worksheet(nome_aba)
        leiloeiros = aba_leil.get_all_records()
        for row in leiloeiros:
            ativo = str(row.get("Ativo","")).strip()
            if ativo.upper() in ("ENCERRADO","FORA"):
                linhas_auditoria.append([
                    row.get("Nome",""),
                    row.get("URL",""),
                    ativo.upper(),
                    nome_aba
                ])
    except Exception as e:
        print(f"Erro ao ler {nome_aba}: {e}", flush=True)

# Ordenar por classificação
linhas_auditoria.sort(key=lambda x: x[2])

if linhas_auditoria:
    aba_aud.append_rows(linhas_auditoria)

print(f"Auditoria: {len(linhas_auditoria)} sites classificados como ENCERRADO ou FORA", flush=True)
print("Relatorio finalizado!", flush=True)
