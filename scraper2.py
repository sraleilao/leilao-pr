import os
import json
import re
import time
import requests
import gspread
from google.oauth2.service_account import Credentials
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

print("Iniciando robo de leiloes (paralelo)...", flush=True)

SPREADSHEET_ID = "1NEZbf37cLnq9Asf9aA76cy4Wjtn7VTLaUQ85oE-ksr0"
ABA_LEILOEIROS = os.environ.get("ABA_LEILOEIROS", "Leiloeiros1")
ABA_RESULTADOS = "Resultados"
ABA_CONFIG     = "Configuracoes"
ABA_SISTEMA    = "Sistema"
WORKERS        = 5

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
    "javascript:","mailto:","tel:","#","linkedin","youtube",
    "leiloes-realizados","leilão-realizado","encerrado"
]

# Palavras que indicam TERRENO VAZIO (sem construção) — exclui
PALAVRAS_TERRENO_VAZIO = [
    "terreno vazio","lote vazio","área nua","area nua","lote nu","terreno nu",
    "sem construção","sem construcao","sem edificação","sem edificacao",
    "gleba","área rural nua","area rural nua","campo aberto",
    "terreno baldio","lote baldio","sem benfeitorias"
]

# Palavras que CONFIRMAM construção — garante que é imóvel construído
PALAVRAS_CONSTRUCAO = [
    "apartamento","casa ","casa,","sobrado","cobertura","flat","studio","kitnet",
    "sala comercial","loja","galpao","galpão","edificio","edifício",
    "condominio","condomínio","construção","construcao","edificação","edificacao",
    "m² construído","m2 construído","m² edificado","m2 edificado",
    "imóvel construído","imovel construido","residência","residencia",
    "prédio","predio","chalé","chale","bangalô","bangalo"
]

INDICADORES_JS = [
    "react","angular","vue","next.js","nuxt","loading...","carregando",
    "please wait","aguarde","app-root","ng-app","__next","__nuxt",
    "window.__","data-reactroot","data-v-","ember","backbone"
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

DIAS_REVERIFICAR = 7
lock = threading.Lock()

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

def config_para_chave(config):
    return f"{config.get('Estados','PR')}|{config.get('Lance Minimo','0')}|{config.get('Lance Maximo','300000')}|{config.get('Desagio Minimo','0')}|{config.get('Tipo','TODOS')}"

def ler_config_anterior(sheet):
    try:
        aba = sheet.worksheet(ABA_SISTEMA)
        for row in aba.get_all_records():
            if row.get("Chave") == "ultima_config":
                return row.get("Valor","")
        return ""
    except Exception:
        return ""

def salvar_config_atual(sheet, chave_config):
    try:
        try:
            aba = sheet.worksheet(ABA_SISTEMA)
        except gspread.exceptions.WorksheetNotFound:
            aba = sheet.add_worksheet(title=ABA_SISTEMA, rows=20, cols=2)
            aba.append_row(["Chave","Valor"])
        for i, row in enumerate(aba.get_all_records(), start=2):
            if row.get("Chave") == "ultima_config":
                aba.update_cell(i, 2, chave_config)
                return
        aba.append_row(["ultima_config", chave_config])
    except Exception as e:
        print(f"Erro ao salvar config: {e}", flush=True)

def limpar_coluna_ativo(sheet, abas):
    print("Configuracao mudou! Limpando Ativo...", flush=True)
    for nome_aba in abas:
        try:
            aba = sheet.worksheet(nome_aba)
            vals = aba.get_all_values()
            updates = [gspread.Cell(i, 4, "") for i in range(2, len(vals)+1)]
            if updates:
                aba.update_cells(updates)
            print(f"  '{nome_aba}' limpa!", flush=True)
        except Exception as e:
            print(f"  Erro ao limpar '{nome_aba}': {e}", flush=True)

def deve_pular(ativo):
    if not ativo or ativo.strip() == "":
        return False
    v = ativo.strip().upper()
    if v == "SIM":
        return False
    if v in ("INVALIDO", "ENCERRADO"):
        return True
    if v in ("FORA", "JS"):
        return False
    try:
        data = datetime.strptime(ativo.strip(), "%d/%m/%Y")
        return (datetime.today() - data).days < DIAS_REVERIFICAR
    except Exception:
        return False

def detectar_js(html, texto):
    html_lower = html.lower()
    for indicador in INDICADORES_JS:
        if indicador in html_lower:
            return True
    if len(html) > 5000 and len(texto) < 200:
        return True
    return False

def testar_site(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code < 400:
            return "OK", r.text
        return "FORA", ""
    except requests.exceptions.ConnectionError as e:
        msg = str(e)
        if any(x in msg for x in ["Name or service not known","Temporary failure","ERR_NAME_NOT_RESOLVED"]):
            return "ENCERRADO", ""
        return "FORA", ""
    except Exception:
        return "FORA", ""

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
            if len(row) >= 7 and row[6]:
                links.add(normalizar_link(row[6]))
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
    if any(d in url.lower() for d in ["facebook.com","instagram.com","twitter.com","whatsapp.com","youtube.com"]):
        return False
    return True

def link_valido(link):
    if not link or not link.startswith("http"):
        return False
    return not any(p in link.lower() for p in PALAVRAS_LINK_IGNORAR)

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

def get_config_dias(config):
    for chave in ["Dias ate o leilao","Dias Ate Leilao","Dias Ate o Leilao"]:
        if chave in config:
            try:
                return int(config[chave])
            except:
                pass
    return 30

def eh_imovel(texto):
    t = texto.lower()

    # Excluir bens móveis
    if any(p in t for p in PALAVRAS_NAO_IMOVEL):
        return False

    # Excluir terrenos claramente vazios
    if any(p in t for p in PALAVRAS_TERRENO_VAZIO):
        return False

    # Verificar se tem palavra de imóvel
    if not any(p in t for p in PALAVRAS_IMOVEL):
        return False

    # Se tem confirmação de construção, aceita
    if any(p in t for p in PALAVRAS_CONSTRUCAO):
        return True

    # Se tem só "terreno" ou "lote" sem confirmação de construção,
    # mantém por precaução (pode ser imóvel com terreno)
    if "terreno" in t or "lote" in t or "sitio" in t or "sítio" in t or "chacara" in t or "chácara" in t:
        return True

    return True

def buscar_lance_no_anuncio(link):
    """Acessa a página do anúncio individual para buscar o valor do lance"""
    try:
        r = requests.get(link, headers=HEADERS, timeout=10)
        if r.status_code >= 400:
            return None, None
        soup = BeautifulSoup(r.text, "html.parser")
        texto = soup.get_text()
        valores = re.findall(r'R\$\s*[\d\.,]+', texto)
        lance     = extrair_valor(valores[0]) if len(valores) >= 1 else None
        avaliacao = extrair_valor(valores[1]) if len(valores) >= 2 else None
        return lance, avaliacao
    except Exception:
        return None, None

def buscar_imoveis(url_site, estados, config):
    resultados = []
    lance_min   = float(config.get("Lance Minimo", 0) or 0)
    lance_max   = float(config.get("Lance Maximo", 300000) or 300000)
    desagio_min = float(config.get("Desagio Minimo", 0) or 0)
    dias_limite = get_config_dias(config)
    tipo_config = config.get("Tipo", "TODOS").upper().strip()
    hoje        = datetime.today()
    limite      = hoje + timedelta(days=dias_limite)

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

                    if not eh_imovel(texto_lower):
                        continue

                    # Filtro de estado rigoroso
                    # Verifica presença do estado E ausência de outros estados no mesmo card
                    tem_uf = (
                        estado_lower in texto_lower or
                        f" {uf.lower()} " in texto_lower or
                        f"/{uf.lower()}" in texto_lower or
                        f"- {uf.lower()}" in texto_lower or
                        f"({uf.lower()})" in texto_lower or
                        f", {uf.lower()}" in texto_lower
                    )
                    if not tem_uf:
                        continue

                    # Se tem outro estado explicitamente mencionado, pula
                    # Ex: card tem "Sumaré/SP" → rejeita mesmo que URL seja ?estado=PR
                    outros_estados = [s for s in NOMES_ESTADOS.keys() if s != uf]
                    tem_outro_estado = any(
                        f"/{s.lower()}" in texto_lower or
                        f"- {s.lower()}" in texto_lower or
                        f"({s.lower()})" in texto_lower or
                        f", {s.lower()}" in texto_lower or
                        f" {s.lower()} " in texto_lower
                        for s in outros_estados
                    )
                    if tem_outro_estado:
                        continue

                    if tipo_config == "JUDICIAL":
                        if not any(x in texto_lower for x in ["judicial","vara","comarca","penhora"]):
                            continue
                    elif tipo_config == "EXTRAJUDICIAL":
                        if any(x in texto_lower for x in ["judicial","vara","comarca"]):
                            continue

                    link_tag = card.find("a", href=True)
                    link = link_tag["href"] if link_tag else None
                    if not link:
                        continue
                    if link.startswith("/"):
                        link = url_site.rstrip("/") + link
                    if not link_valido(link):
                        continue

                    # Extrair valores da listagem
                    valores = re.findall(r'R\$\s*[\d\.,]+', texto)
                    lance     = extrair_valor(valores[0]) if len(valores) >= 1 else None
                    avaliacao = extrair_valor(valores[1]) if len(valores) >= 2 else None

                    # Se não achou lance na listagem, busca no anúncio individual
                    if lance is None:
                        lance, avaliacao = buscar_lance_no_anuncio(link)

                    # Filtrar por lance apenas se tiver valor
                    if lance and (lance < lance_min or lance > lance_max):
                        continue

                    desagio = None
                    if avaliacao and lance and avaliacao > 0:
                        desagio = ((avaliacao - lance) / avaliacao) * 100
                    if desagio is not None and desagio < desagio_min:
                        continue

                    data_leilao = extrair_data(texto)
                    if data_leilao:
                        if data_leilao < hoje or data_leilao > limite:
                            continue
                        data_str = data_leilao.strftime("%d/%m/%Y")
                    else:
                        data_str = "Verificar"

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

            except Exception:
                continue

        if resultados:
            break

    return resultados

def processar_site(args):
    i, row, estados, config, hoje_str = args
    nome  = str(row.get("Nome","")).strip()
    url   = str(row.get("URL","")).strip()
    ativo = str(row.get("Ativo","")).strip()

    if not url_valida(url):
        return i, nome, "INVALIDO", [], False

    if deve_pular(ativo):
        return i, nome, "PULAR", [], False

    status, html = testar_site(url)

    if status == "ENCERRADO":
        return i, nome, "ENCERRADO", [], False
    elif status == "FORA":
        return i, nome, "FORA", [], False

    soup = BeautifulSoup(html, "html.parser")
    texto_visivel = soup.get_text()
    eh_js = detectar_js(html, texto_visivel)

    if eh_js:
        return i, nome, "JS", [], True

    resultados = buscar_imoveis(url, estados, config)
    if resultados:
        return i, nome, "SIM", resultados, False
    else:
        return i, nome, hoje_str, [], False

def garantir_aba_resultados(sheet):
    try:
        aba = sheet.worksheet(ABA_RESULTADOS)
        if ABA_LEILOEIROS == "Leiloeiros1":
            print("Limpando Resultados...", flush=True)
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

config      = ler_configuracoes(sheet)
estados     = [e.strip().upper() for e in config.get("Estados","PR").split(",") if e.strip()]
chave_atual = config_para_chave(config)
print(f"Estados: {estados}", flush=True)

if ABA_LEILOEIROS == "Leiloeiros1":
    chave_anterior = ler_config_anterior(sheet)
    if chave_anterior != chave_atual:
        print("Configuracao mudou! Limpando Ativo...", flush=True)
        limpar_coluna_ativo(sheet, ["Leiloeiros1","Leiloeiros2","Leiloeiros3"])
        salvar_config_atual(sheet, chave_atual)
    else:
        print("Configuracao igual — usando cache.", flush=True)

aba_resultados = garantir_aba_resultados(sheet)
links_vistos   = carregar_links_ja_gravados(sheet)
aba_leiloeiros = sheet.worksheet(ABA_LEILOEIROS)
leiloeiros     = aba_leiloeiros.get_all_records()
print(f"Processando '{ABA_LEILOEIROS}' — {len(leiloeiros)} leiloeiros com {WORKERS} workers...", flush=True)

hoje_str         = datetime.today().strftime("%d/%m/%Y")
total_encontrado = 0
total_pulados    = 0
total_js         = 0

args_list = [(i, row, estados, config, hoje_str) for i, row in enumerate(leiloeiros, start=2)]

batch_size = WORKERS
for batch_start in range(0, len(args_list), batch_size):
    batch = args_list[batch_start:batch_start + batch_size]

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(processar_site, args): args for args in batch}

        for future in as_completed(futures):
            try:
                i, nome, status, resultados, precisa_js = future.result()

                if status == "PULAR":
                    total_pulados += 1
                    continue

                print(f"[{i-1}/{len(leiloeiros)}] {nome} → {status}", flush=True)

                with lock:
                    try:
                        aba_leiloeiros.update_cell(i, 4, status)
                    except Exception:
                        pass

                if precisa_js:
                    total_js += 1

                if resultados:
                    novos = []
                    with lock:
                        for r in resultados:
                            chave = normalizar_link(r["Link"])
                            if chave not in links_vistos:
                                links_vistos.add(chave)
                                novos.append(r)

                    for r in novos:
                        gravar_linha(aba_resultados, r)
                        total_encontrado += 1

            except Exception as e:
                print(f"  Erro no future: {e}", flush=True)

print(f"\nTotal: {total_encontrado} imoveis | Pulados: {total_pulados} | JS: {total_js}", flush=True)
print("Robo finalizado!", flush=True)
