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
ABA_LEILOEIROS = os.environ.get("ABA_LEILOEIROS", "Leiloeiros1")
ABA_RESULTADOS = "Resultados"
ABA_CONFIG     = "Configuracoes"
 
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}
 
PALAVRAS_IMOVEL = [
    "apartamento","casa ","terreno","sitio","sítio","chacara","chácara",
    "sobrado","cobertura","flat","studio","kitnet","fazenda","rural",
    "imóvel urbano","imovel urbano","imóvel rural","imovel rural",
    "sala comercial","loja","galpao","galpão","edificio","edifício",
    "condominio","condomínio","loteamento","lote urbano","lote rural"
]
 
PALAVRAS_NAO_IMOVEL = [
    "veiculo","veículo","automóvel","automovel","caminhao","caminhão",
    "onibus","ônibus","motocicleta","camionete","pickup",
    "maquinario","maquinário","equipamento","sucata","eletronico","eletrônico",
    "semovente","animal","gado","cavalo","trator","reboque","trailer",
    "lancha","barco","aeronave","implemento agricola","celular","notebook",
    "televisao","televisão","geladeira","fogao","fogão"
]
 
PALAVRAS_LINK_IGNORAR = [
    "edital","facebook","twitter","instagram","whatsapp",
    "javascript:","mailto:","tel:","#","linkedin","youtube"
]
 
TERMOS_BUSCA_TEMPLATE = [
    "/imoveis?estado={uf}",
    "/imoveis?uf={uf}",
    "/imoveis/{estado_lower}",
    "/imoveis/{uf_lower}",
    "/lotes?estado={uf}&categoria=imovel",
    "/lotes?categoria=imovel&estado={uf}",
    "/busca?estado={uf}&tipo=imovel",
    "/leiloes?estado={uf}&tipo=imovel",
    "/externo/lotes?estado={uf}",
    "/imoveis",
    "/leilao/imoveis",
    "/busca?busca=imovel",
    "/?s={estado_lower}+imovel",
]
 
NOMES_ESTADOS = {
    "PR":"parana","SP":"sao-paulo","SC":"santa-catarina","RS":"rio-grande-do-sul",
    "RJ":"rio-de-janeiro","MG":"minas-gerais","GO":"goias","MT":"mato-grosso",
    "MS":"mato-grosso-do-sul","BA":"bahia","DF":"distrito-federal","ES":"espirito-santo",
    "PE":"pernambuco","CE":"ceara","PA":"para","AM":"amazonas","MA":"maranhao",
    "PI":"piaui","RN":"rio-grande-do-norte","AL":"alagoas","SE":"sergipe",
    "RO":"rondonia","AC":"acre","AP":"amapa","RR":"roraima","TO":"tocantins","PB":"paraiba"
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
        print(f"Erro config: {e}", flush=True)
        return {"Estados":"PR","Lance Minimo":"0","Lance Maximo":"300000","Desagio Minimo":"0","Dias ate o leilao":"30","Tipo":"TODOS"}
 
def get_config_dias(config):
    """Tenta varias grafias para Dias ate o leilao"""
    for chave in ["Dias ate o leilao","Dias Ate Leilao","Dias Ate o Leilao","dias ate o leilao"]:
        if chave in config:
            try:
                return int(config[chave])
            except:
                pass
    return 30
 
def normalizar_link(link):
    link = re.sub(r'\?utm_.*', '', link or "")
    link = re.sub(r'&utm_[^&]*', '', link)
    return link.strip("/").lower()
 
def carregar_links_ja_gravados(sheet):
    try:
        aba = sheet.worksheet(ABA_RESULTADOS)
        todos = aba.get_all_values()
        links = set()
        for row in todos[1:]:
            if len(row) >= 7:
                link = row[6]
                if link:
                    links.add(normalizar_link(link))
        print(f"Links ja gravados: {len(links)}", flush=True)
        return links
    except Exception:
        return set()
 
def url_valida(url):
    if not url or "@" in url:
        return False
    if re.search(r'\(\d{2}\)\s*\d{4,5}', url):
        return False
    if not url.startswith("http"):
        return False
    # Ignorar URLs que são claramente não-sites
    dominios_ignorar = ["facebook.com","instagram.com","twitter.com","whatsapp.com","youtube.com"]
    if any(d in url.lower() for d in dominios_ignorar):
        return False
    return True
 
def link_valido(link):
    if not link or not link.startswith("http"):
        return False
    if any(p in link.lower() for p in PALAVRAS_LINK_IGNORAR):
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
    t = texto.lower()
    if any(p in t for p in PALAVRAS_NAO_IMOVEL):
        return False
    if any(p in t for p in PALAVRAS_IMOVEL):
        return True
    return False
 
def buscar_imoveis(url_site, estados, config):
    resultados = []
    lance_min   = float(config.get("Lance Minimo", 0) or 0)
    lance_max   = float(config.get("Lance Maximo", 300000) or 300000)
    desagio_min = float(config.get("Desagio Minimo", 0) or 0)
    dias_limite = get_config_dias(config)
    tipo_config = config.get("Tipo", "TODOS").upper().strip()
 
    hoje   = datetime.today()
    limite = hoje + timedelta(days=dias_limite)
 
    for uf in estados:
        estado_lower = NOMES_ESTADOS.get(uf, uf.lower())
        termos = [t.format(uf=uf, uf_lower=uf.lower(), estado_lower=estado_lower) for t in TERMOS_BUSCA_TEMPLATE]
 
        for termo in termos:
            try:
                url = url_site.rstrip("/") + termo
                r = requests.get(url, headers=HEADERS, timeout=15)
                if r.status_code >= 400:
                    continue
 
                soup = BeautifulSoup(r.text, "html.parser")
                texto_pagina = soup.get_text().lower()
 
                if estado_lower not in texto_pagina and uf.lower() not in texto_pagina:
                    continue
                if not any(p in texto_pagina for p in PALAVRAS_IMOVEL):
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
 
                    # Filtrar por tipo
                    if tipo_config == "JUDICIAL":
                        if not any(x in texto_lower for x in ["judicial","vara","comarca","penhora"]):
                            continue
                    elif tipo_config == "EXTRAJUDICIAL":
                        if any(x in texto_lower for x in ["judicial","vara","comarca"]):
                            continue
 
                    # Extrair link
                    link_tag = card.find("a", href=True)
                    link = link_tag["href"] if link_tag else None
                    if not link:
                        continue
                    if link.startswith("/"):
                        link = url_site.rstrip("/") + link
                    if not link_valido(link):
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
                    if len(titulo) < 8:
                        titulo = texto[:120].strip()
 
                    resultados.append({
                        "Titulo":    titulo[:150],
                        "Estado":    uf,
                        "Lance":     lance,
                        "Avaliacao": avaliacao,
                        "Desagio":   round(desagio, 1) if desagio else None,
                        "Data":      data_str,
                        "Link":      link,
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
        if ABA_LEILOEIROS == "Leiloeiros1":
            print("Limpando Resultados para nova rodada...", flush=True)
            aba.clear()
            aba.append_row(["Titulo","Estado","Lance Inicial (R$)","Avaliacao (R$)","Desagio (%)","Data Leilao","Link do Anuncio","Atualizado em"])
        return aba
    except gspread.exceptions.WorksheetNotFound:
        aba = sheet.add_worksheet(title=ABA_RESULTADOS, rows=10000, cols=8)
        aba.append_row(["Titulo","Estado","Lance Inicial (R$)","Avaliacao (R$)","Desagio (%)","Data Leilao","Link do Anuncio","Atualizado em"])
        return aba
 
def gravar_linha(aba_resultados, resultado):
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    try:
        aba_resultados.append_row([
            resultado["Titulo"],
            resultado["Estado"],
            resultado["Lance"] or "Verificar",
            resultado["Avaliacao"] or "N/D",
            resultado["Desagio"] or "N/D",
            resultado["Data"],
            resultado["Link"],
            agora,
        ])
    except Exception as e:
        print(f"  Erro ao gravar: {e}", flush=True)
 
# ── MAIN ──────────────────────────────────────────────────────────────────────
sheet = conectar_sheets()
print("Conectado ao Google Sheets!", flush=True)
 
config  = ler_configuracoes(sheet)
estados = [e.strip().upper() for e in config.get("Estados","PR").split(",") if e.strip()]
print(f"Estados: {estados}", flush=True)
 
aba_resultados = garantir_aba_resultados(sheet)
links_vistos   = carregar_links_ja_gravados(sheet)
 
aba_leiloeiros = sheet.worksheet(ABA_LEILOEIROS)
leiloeiros     = aba_leiloeiros.get_all_records()
print(f"Processando '{ABA_LEILOEIROS}' — {len(leiloeiros)} leiloeiros...", flush=True)
 
total_encontrado = 0
 
for i, row in enumerate(leiloeiros, start=2):
    nome = str(row.get("Nome","")).strip()
    url  = str(row.get("URL","")).strip()
 
    if not url_valida(url):
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
 
    novos = []
    for r in resultados:
        chave = normalizar_link(r["Link"])
        if chave not in links_vistos:
            links_vistos.add(chave)
            novos.append(r)
 
    if novos:
        print(f"  {len(novos)} imovel(is)!", flush=True)
        aba_leiloeiros.update_cell(i, 4, "SIM")
        for r in novos:
            gravar_linha(aba_resultados, r)
        total_encontrado += len(novos)
    else:
        print(f"  Sem imoveis", flush=True)
        aba_leiloeiros.update_cell(i, 4, "NAO")
 
    time.sleep(1)
 
print(f"Total: {total_encontrado} imoveis", flush=True)
print("Robo finalizado!", flush=True)
 
