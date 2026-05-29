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

PALAVRAS_NAO_IMOVEL = [
    "veiculo","veículo","automóvel","caminhao","onibus","motocicleta",
    "maquinario","equipamento","sucata","semovente","animal","gado","trator"
]

PALAVRAS_TERRENO_VAZIO = [
    "terreno vazio","lote vazio","área nua","area nua","lote nu","terreno nu",
    "sem construção","sem construcao","sem edificação","sem edificacao",
    "gleba","área rural nua","area rural nua","terreno baldio","lote baldio"
]

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
        return float(str(val).replace(",",".").replace("%","").replace("R$","").replace(" ",""))
    except Exception:
        return None

def extrair_data_ordenacao(data_str):
    try:
        if data_str == "Verificar" or not data_str:
            return datetime(9999, 12, 31)
        return datetime.strptime(data_str.strip(), "%d/%m/%Y")
    except Exception:
        return datetime(9999, 12, 31)

def eh_resultado_valido(titulo, link):
    t = titulo.lower()
    l = link.lower()
    if any(p in t for p in PALAVRAS_NAO_IMOVEL):
        return False
    if any(p in t for p in PALAVRAS_TERRENO_VAZIO):
        return False
    if "leiloes-realizados" in l or "encerrado" in l:
        return False
    return True

sheet = conectar_sheets()
print("Conectado!", flush=True)

agora = datetime.now().strftime("%d/%m/%Y %H:%M")

aba   = sheet.worksheet(ABA_RESULTADOS)
dados = aba.get_all_records()
print(f"Registros brutos: {len(dados)}", flush=True)

imoveis  = []
excluidos = 0

for row in dados:
    titulo = row.get("Titulo","")
    link   = row.get("Link do Anuncio","")

    if not titulo or not link:
        continue

    if not eh_resultado_valido(titulo, link):
        excluidos += 1
        continue

    imoveis.append({
        "Titulo":    titulo,
        "Estado":    row.get("Estado",""),
        "Lance":     extrair_float(row.get("Lance Inicial (R$)")),
        "Avaliacao": extrair_float(row.get("Avaliacao (R$)")),
        "Desagio":   extrair_float(row.get("Desagio (%)")),
        "Data":      row.get("Data Leilao",""),
        "Link":      link,
    })

print(f"Imoveis validos: {len(imoveis)} | Excluidos pelo filtro: {excluidos}", flush=True)

com_lance = [x for x in imoveis if x["Lance"] is not None]
sem_lance = [x for x in imoveis if x["Lance"] is None]

try:
    aba_top = sheet.worksheet(ABA_RELATORIO)
    aba_top.clear()
except gspread.exceptions.WorksheetNotFound:
    aba_top = sheet.add_worksheet(title=ABA_RELATORIO, rows=200, cols=8)

aba_top.append_row([f"RELATORIO TOP 10 — Gerado em {agora}"])
aba_top.append_row([f"Total: {len(imoveis)} imoveis ({len(com_lance)} com lance | {len(sem_lance)} sem lance) | {excluidos} excluidos pelo filtro"])
aba_top.append_row([])

if com_lance:
    top_desagio = sorted(
        [x for x in com_lance if x["Desagio"] is not None],
        key=lambda x: x["Desagio"], reverse=True
    )[:10]

    max_lance   = max(x["Lance"] for x in com_lance)
    max_desagio = max((x["Desagio"] or 0) for x in com_lance) or 1
    for x in com_lance:
        nota_desagio = (x["Desagio"] or 0) / max_desagio
        nota_lance   = 1 - (x["Lance"] / max_lance)
        x["Score"]   = (nota_desagio * 0.6) + (nota_lance * 0.4)
    top_combinado = sorted(com_lance, key=lambda x: x.get("Score",0), reverse=True)[:10]

    aba_top.append_row(["TOP 10 — MAIOR DESAGIO"])
    aba_top.append_row(["#","Titulo","Estado","Lance (R$)","Avaliacao (R$)","Desagio (%)","Data Leilao","Link"])
    for idx, r in enumerate(top_desagio, 1):
        aba_top.append_row([idx, r["Titulo"][:100], r["Estado"], r["Lance"],
                           r["Avaliacao"] or "N/D", f"{r['Desagio']}%", r["Data"], r["Link"]])

    aba_top.append_row([])
    aba_top.append_row([])

    aba_top.append_row(["TOP 10 — MELHOR COMBINACAO (maior desagio + menor lance)"])
    aba_top.append_row(["#","Titulo","Estado","Lance (R$)","Avaliacao (R$)","Desagio (%)","Data Leilao","Link"])
    for idx, r in enumerate(top_combinado, 1):
        aba_top.append_row([idx, r["Titulo"][:100], r["Estado"], r["Lance"],
                           r["Avaliacao"] or "N/D", f"{r['Desagio']}%" if r["Desagio"] else "N/D",
                           r["Data"], r["Link"]])

    aba_top.append_row([])
    aba_top.append_row([])

top_data = sorted(imoveis, key=lambda x: extrair_data_ordenacao(x["Data"]))[:10]
aba_top.append_row(["TOP 10 — LEILOES MAIS PROXIMOS (por data)"])
aba_top.append_row(["#","Titulo","Estado","Lance (R$)","Avaliacao (R$)","Desagio (%)","Data Leilao","Link"])
for idx, r in enumerate(top_data, 1):
    aba_top.append_row([idx, r["Titulo"][:100], r["Estado"],
                       r["Lance"] or "Verificar", r["Avaliacao"] or "N/D",
                       f"{r['Desagio']}%" if r["Desagio"] else "N/D",
                       r["Data"], r["Link"]])

print("Top10 gerado!", flush=True)

# ── AUDITORIA ─────────────────────────────────────────────────────────────────
print("Gerando Auditoria...", flush=True)

try:
    aba_aud = sheet.worksheet(ABA_AUDITORIA)
    aba_aud.clear()
except gspread.exceptions.WorksheetNotFound:
    aba_aud = sheet.add_worksheet(title=ABA_AUDITORIA, rows=5000, cols=4)

aba_aud.append_row([f"AUDITORIA DE SITES — Ultima verificacao: {agora}"])
aba_aud.append_row([])
aba_aud.append_row(["Nome","URL","Classificacao","Aba"])

linhas_auditoria = []
for nome_aba in ["Leiloeiros1","Leiloeiros2","Leiloeiros3"]:
    try:
        aba_leil = sheet.worksheet(nome_aba)
        for row in aba_leil.get_all_records():
            ativo = str(row.get("Ativo","")).strip()
            if ativo.upper() in ("ENCERRADO","FORA"):
                linhas_auditoria.append([
                    row.get("Nome",""), row.get("URL",""),
                    ativo.upper(), nome_aba
                ])
    except Exception as e:
        print(f"Erro ao ler {nome_aba}: {e}", flush=True)

linhas_auditoria.sort(key=lambda x: x[2])
if linhas_auditoria:
    aba_aud.append_rows(linhas_auditoria)

print(f"Auditoria: {len(linhas_auditoria)} sites", flush=True)
print("Relatorio finalizado!", flush=True)
