import os
import json
import re
import time
import requests
import gspread
from google.oauth2.service_account import Credentials
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

print("Iniciando robo de leiloes...", flush=True)

SPREADSHEET_ID = "1NEZbf37cLnq9Asf9aA76cy4Wjtn7VTLaUQ85oE-ksr0"
ABA_LEILOEIROS = os.environ.get("ABA_LEILOEIROS", "Pagina1")
ABA_RESULTADOS = "Resultados"
ABA_CONFIG     = "Configuracoes"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}

PALAVRAS_IMOVEL = [
    "imovel","imóvel","apartamento","casa","terreno","sitio","sítio",
    "chacara","chácara","lote","sala comercial","galpao","galpão",
    "sobrado","cobertura","flat","studio","kitnet","fazenda","rural"
]

PALAVRAS_NAO_IMOVEL = [
    "veiculo","veículo","carro","moto","caminhao","caminhão","onibus","ônibus",
    "maquina","máquina","equipamento","sucata","eletronico","eletrônico",
    "semovente","animal","gado","cavalo","trator","reboque"
]

TERMOS_BUSCA_TEMPLATE = [
    "/imoveis?estado={uf}",
    "/imoveis?uf={uf}",
    "/imoveis/{estado_lower}",
    "/imoveis/{uf_lower}",
    "/lotes?estado={uf}",
    "/lotes?categoria=imovel&estado={uf}",
    "/busca?estado={uf}&tipo=imovel",
    "/busca?uf={uf}",
    "/leiloes?estado={uf}",
    "/leiloes/{estado_lower}",
    "/?s={estado_lower}",
    "/externo/lotes?estado={uf}",
    "/busca?busca=imovel",
    "/imoveis",
    "/leilao/imoveis",
]

NOMES_ESTADOS = {
    "PR": "parana", "SP": "sao-paulo", "SC": "santa-catarina",
    "RS": "rio-grande-do-sul", "RJ": "rio-de-janeiro", "MG": "minas-gerais",
    "GO": "goias", "MT": "mato-grosso", "MS": "mato-grosso-do-sul",
    "BA": "bahia", "DF": "distrito-federal", "ES": "espirito-santo",
    "PE": "pernambuco", "CE": "ceara", "PA": "para", "AM": "amazonas",
    "MA": "maranhao", "PI": "piaui", "RN": "rio-grande-do-norte",
    "AL": "alagoas", "SE": "sergipe", "RO": "rondonia", "AC": "acre",
    "AP": "amapa", "RR": "roraima", "TO": "tocantins", "PB": "paraiba"
}

def conectar_sheets():
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)

def ler_configuracoes(sheet):
    try:
        aba = sheet.worksheet(ABA_CONFIG)
        dados = aba.get_all_records()
        config = {}
        for row in dados:
            chave = str(row.get("Configuração","") or row.get("Configuracao","")).strip()
            valor = str(row.get("Valor","")).strip()
            if chave:
                config[chave] = valor
        print(f"Configuracoes: {config}", flush=True)
        return config
    except Exception as e:
        print(f"Erro ao ler configuracoes: {e}", flush=True)
        return {
            "Estados": "PR",
            "Lance Minimo": "0",
            "Lance Maximo": "999999999",
            "Desagio Minimo": "0",
            "Dias Ate Leilao": "30",
            "Tipo": "TODOS"
        }

def url_valida(url):
    if not url:
        return False
    if "@" in url:
        return False
    if re.search(r'\(\d{2}\)\s*\d{4,5}', url):
        return False
    if re.search(r'\d{10,11}', url.replace("-","").replace(" ","")):
        return False
    if not url.startswith("http"):
        return False
    return True

def site_ativo(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        return r.status_code < 400
    except Exception:
        return False

def extrair_valor(texto):
    if not texto:
        return None
    texto = re.sub(r'[Rr]\$\s*', '', texto)
    texto = re.sub(r'\.(?=\d{3})', '', texto)
    texto = re.sub(r',', '.', texto)
    nums = re.findall(r'\d+\.?\d*', texto)
    try:
        v = float(nums[0]) if nums else None
        return v if v and 1000 <= v <= 500_000_000 else None
    except Exception:
        return None

def extrair_data(texto):
    m = re.search(r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})', texto or "")
    if m:
        d, mo, a = m.groups()
        if len(a) == 2:
            a = "20" + a
        try:
            return datetime(int(a), int(mo), int(d))
        except Exception:
            return None
    return None

def eh_imovel(texto):
    texto = texto.lower()
    if any(p in texto for p in PALAVRAS_NAO_IMOVEL):
        return False
    if any(p in texto for p in PALAVRAS_IMOVEL):
        return True
    return False

def eh_tipo_valido(texto, tipo_config):
    if tipo_config == "TODOS":
        return True
    texto = texto.lower()
    if tipo_config == "JUDICIAL":
        return any(x in texto for x in ["judicial","juiz","vara","comarca","penhora","execucao","execução"])
    if tipo_config == "EXTRAJUDICIAL":
        return not any(x in texto for x in ["judicial","juiz","vara","comarca"])
    return True

def buscar_imoveis(url_site, estados, config):
    resultados = []
    lance_min  = float(config.get("Lance Minimo", 0) or 0)
    lance_max  = float(config.get("Lance Maximo", 999999999) or 999999999)
    desagio_min = float(config.get("Desagio Minimo", 0) or 0)
    dias_limite = int(config.get("Dias Ate Leilao", 30) or 30)
    tipo_config = config.get("Tipo", "TODOS").upper()

    hoje  = datetime.today()
    limite = hoje + timedelta(days=dias_limite)

    for uf in estados:
        estado_lower = NOMES_ESTADOS.get(uf, uf.lower())
        termos = [
            t.format(uf=uf, uf_lower=uf.lower(), estado_lower=estado_lower)
            for t in TERMOS_BUSCA_TEMPLATE
        ]

        for termo in termos:
            try:
                url = url_site.rstrip("/") + termo
                r = requests.get(url, headers=HEADERS, timeout=15)
                if r.status_code >= 400:
                    continue

                soup = BeautifulSoup(r.text, "html.parser")
                texto_pagina = soup.get_text().lower()

                tem_estado = (
                    estado_lower in texto_pagina or
                    uf.lower() in texto_pagina or
                    f"/{uf.lower()}" in texto_pagina or
                    f"- {uf.lower()}" in texto_pagina or
                    f"({uf.lower()})" in texto_pagina
                )
                if not tem_estado:
                    continue

                tem_imovel = any(p in texto_pagina for p in PALAVRAS_IMOVEL)
                if not tem_imovel:
                    continue

                cards = soup.select(
                    ".lote,.imovel,.card,.produto,.item,article,"
                    "[class*='lote'],[class*='imovel'],[class*='card'],"
                    "[class*='produto'],[class*='result'],[class*='oferta']"
                )
                if not cards:
                    cards = soup.find_all(["article","li"], limit=100)

                for card in cards[:100]:
                    texto = card.get_text(" ", strip=True)
                    texto_lower = texto.lower()

                    # Filtrar só imóveis
                    if not eh_imovel(texto_lower):
                        continue

                    # Filtrar por estado
                    tem_uf = (
                        estado_lower in texto_lower or
                        f" {uf.lower()} " in texto_lower or
                        f"/{uf.lower()}" in texto_lower or
                        f"- {uf.lower()}" in texto_lower or
                        f"({uf.lower()})" in texto_lower
                    )
                    if not tem_uf:
                        continue

                    # Filtrar por tipo judicial/extrajudicial
                    if not eh_tipo_valido(texto_lower, tipo_config):
                        continue

                    # Extrair link
                    link_tag = card.find("a", href=True)
                    link = link_tag["href"] if link_tag else url
                    if link.startswith("/"):
                        link = url_site.rstrip("/") + link
                    if not link.startswith("http"):
                        continue

                    # Extrair valores
                    valores = re.findall(r'R\$\s*[\d\.,]+', texto)
                    lance     = extrair_valor(valores[0]) if len(valores) >= 1 else None
                    avaliacao = extrair_valor(valores[1]) if len(valores) >= 2 else None

                    # Filtrar por lance
                    if lance and (lance < lance_min or lance > lance_max):
                        continue

                    # Calcular deságio
                    desagio = None
                    if avaliacao and lance and avaliacao > 0:
                        desagio = ((avaliacao - lance) / avaliacao) * 100
                    if desagio is not None and desagio < desagio_min:
                        continue

                    # Filtrar por data
                    data_leilao = extrair_data(texto)
                    if data_leilao:
                        if data_leilao < hoje or data_leilao > limite:
                            continue
                        data_str = data_leilao.strftime("%d/%m/%Y")
                    else:
                        data_str = "Verificar"

                    # Extrair título
                    titulo_tag = card.find(["h1","h2","h3","h4","strong","b"])
                    titulo = titulo_tag.get_text(strip=True) if titulo_tag else texto[:80]
                    titulo = titulo.strip()

                    # Ignorar títulos ruins
                    if len(titulo) < 5 or titulo.lower() in ["data:","pesquisar","resultado","imóveis","imoveis","50%","40%","30%"]:
                        titulo = texto[:100].strip()

                    resultados.append({
                        "Titulo": titulo[:150],
                        "Estado": uf,
                        "Lance": lance,
                        "Avaliacao": avaliacao,
                        "Desagio": round(desagio, 1) if desagio else "N/D",
                        "Data": data_str,
                        "Link": link,
                        "Site": url_site,
                    })

                if resultados:
                    break

            except Exception as e:
                print(f"  Erro: {e}", flush=True)
                continue

        if resultados:
            break

    return resultados

def garantir_aba_resultados(sheet):
    try:
        aba = sheet.worksheet(ABA_RESULTADOS)
        # Se for primeira aba do lote (Pagina1), limpa e recria cabeçalho
        if ABA_LEILOEIROS == "Pagina1":
            aba.clear()
            cabecalho = ["Titulo","Estado","Lance Inicial (R$)","Avaliacao (R$)","Desagio (%)","Data Leilao","Link","Site","Atualizado em"]
            aba.append_row(cabecalho)
        return aba
    except gspread.exceptions.WorksheetNotFound:
        aba = sheet.add_worksheet(title=ABA_RESULTADOS, rows=10000, cols=9)
        cabecalho = ["Titulo","Estado","Lance Inicial (R$)","Avaliacao (R$)","Desagio (%)","Data Leilao","Link","Site","Atualizado em"]
        aba.append_row(cabecalho)
        return aba

def gravar_linha(aba_resultados, resultado):
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    try:
        aba_resultados.append_row([
            resultado["Titulo"],
            resultado["Estado"],
            resultado["Lance"] or "Verificar",
            resultado["Avaliacao"] or "N/D",
            resultado["Desagio"],
            resultado["Data"],
            resultado["Link"],
            resultado["Site"],
            agora,
        ])
    except Exception as e:
        print(f"  Erro ao gravar: {e}", flush=True)

# ── MAIN ──────────────────────────────────────────────────────────────────────
sheet = conectar_sheets()
print("Conectado ao Google Sheets!", flush=True)

config = ler_configuracoes(sheet)
estados = [e.strip().upper() for e in config.get("Estados","PR").split(",") if e.strip()]
print(f"Buscando estados: {estados}", flush=True)

aba_resultados  = garantir_aba_resultados(sheet)
aba_leiloeiros  = sheet.worksheet(ABA_LEILOEIROS)
leiloeiros      = aba_leiloeiros.get_all_records()
print(f"Processando '{ABA_LEILOEIROS}' com {len(leiloeiros)} leiloeiros...", flush=True)

links_ja_vistos = set()
total_encontrado = 0

for i, row in enumerate(leiloeiros, start=2):
    nome = str(row.get("Nome","")).strip()
    url  = str(row.get("URL","")).strip()

    # Validar URL
    if not url_valida(url):
        print(f"[{i-1}] PULANDO (URL invalida): {url}", flush=True)
        aba_leiloeiros.update_cell(i, 4, "INVALIDO")
        time.sleep(0.3)
        continue

    print(f"[{i-1}/{len(leiloeiros)}] {nome}", flush=True)

    if not site_ativo(url):
        print(f"  Fora do ar", flush=True)
        aba_leiloeiros.update_cell(i, 4, "NAO")
        time.sleep(0.5)
        continue

    resultados = buscar_imoveis(url, estados, config)

    # Remover duplicatas por link
    novos = []
    for r in resultados:
        if r["Link"] not in links_ja_vistos:
            links_ja_vistos.add(r["Link"])
            novos.append(r)

    if novos:
        print(f"  {len(novos)} imovel(is) encontrado(s)!", flush=True)
        aba_leiloeiros.update_cell(i, 4, "SIM")
        for r in novos:
            gravar_linha(aba_resultados, r)
        total_encontrado += len(novos)
    else:
        print(f"  Sem imoveis", flush=True)
        aba_leiloeiros.update_cell(i, 4, "NAO")

    time.sleep(1)

print(f"Total encontrado: {total_encontrado} imoveis", flush=True)
print("Robo finalizado!", flush=True)
