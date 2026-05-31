"""
Scrapers específicos para sites paranaenses importantes.
Cada site tem sua URL correta e seletor de card adequado.
"""

import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────────────────────────────────────
# MAPEAMENTO DE SITES ESPECÍFICOS
# Formato: url_base -> {"busca": URL de busca, "seletor": CSS selector dos cards}
# ─────────────────────────────────────────────────────────────────────────────

SITES_ESPECIFICOS = {
    # alleiloes.com.br — cards com classes Tailwind bg-site-card-bg
    "alleiloes.com.br": {
        "urls_busca": ["https://alleiloes.com.br", "https://alleiloes.com.br/pagina/2"],
        "seletor_card": "[class*='bg-site-card-bg'], [class*='card-bg']",
        "seletor_link": "a[href*='/lote/']",
        "filtro_estado": True,
    },

    # portalzuk.com.br — sistema de leilões judicial
    "portalzuk.com.br": {
        "urls_busca": [
            "https://www.portalzuk.com.br/leiloes/imoveis",
            "https://www.portalzuk.com.br/leiloes?estado=PR&tipo=imovel",
            "https://www.portalzuk.com.br",
        ],
        "seletor_card": ".leilao-card, .card, [class*='leilao'], [class*='card'], article",
        "seletor_link": "a[href*='lote'], a[href*='leilao'], a[href*='imovel']",
        "filtro_estado": True,
    },

    # vasconcelosleiloes.com.br
    "vasconcelosleiloes.com.br": {
        "urls_busca": [
            "https://vasconcelosleiloes.com.br/imoveis",
            "https://vasconcelosleiloes.com.br/leiloes",
            "https://vasconcelosleiloes.com.br",
        ],
        "seletor_card": ".lote, .card, .item, article, [class*='lote'], [class*='card']",
        "seletor_link": "a[href*='lote'], a[href*='imovel']",
        "filtro_estado": False,  # site 100% PR
    },

    # schererleiloes.com.br
    "schererleiloes.com.br": {
        "urls_busca": [
            "https://www.schererleiloes.com.br/imoveis",
            "https://www.schererleiloes.com.br/leiloes",
            "https://www.schererleiloes.com.br",
        ],
        "seletor_card": ".lote, .card, .item, article, [class*='lote'], [class*='card']",
        "seletor_link": "a[href*='lote'], a[href*='imovel']",
        "filtro_estado": False,
    },

    # medeirosleiloes.com.br
    "medeirosleiloes.com.br": {
        "urls_busca": [
            "https://www.medeirosleiloes.com.br/leiloes?estado=PR",
            "https://www.medeirosleiloes.com.br/imoveis",
            "https://www.medeirosleiloes.com.br",
        ],
        "seletor_card": ".lote, .card, .item, article, li, [class*='lote'], [class*='card']",
        "seletor_link": "a[href*='lote'], a[href*='imovel']",
        "filtro_estado": True,
    },

    # marquesleiloes.com.br
    "marquesleiloes.com.br": {
        "urls_busca": [
            "https://www.marquesleiloes.com.br/imoveis",
            "https://www.marquesleiloes.com.br/leiloes",
            "https://www.marquesleiloes.com.br",
        ],
        "seletor_card": ".lote, .card, .item, article, [class*='lote'], [class*='card']",
        "seletor_link": "a[href*='lote'], a[href*='imovel']",
        "filtro_estado": False,
    },

    # lancevip.com.br
    "lancevip.com.br": {
        "urls_busca": [
            "http://www.lancevip.com.br/imoveis?estado=PR",
            "http://www.lancevip.com.br/leiloes?estado=PR",
            "http://www.lancevip.com.br",
        ],
        "seletor_card": ".lote, .card, .item, article, [class*='lote'], [class*='card']",
        "seletor_link": "a[href*='lote'], a[href*='imovel']",
        "filtro_estado": True,
    },

    # megaleiloes.com.br — site nacional com filtro por estado
    "megaleiloes.com.br": {
        "urls_busca": [
            "https://www.megaleiloes.com.br/imoveis/apartamentos/pr",
            "https://www.megaleiloes.com.br/imoveis/casas/pr",
            "https://www.megaleiloes.com.br/imoveis/pr",
            "https://www.megaleiloes.com.br/imoveis?estado=PR",
        ],
        "seletor_card": ".property-card, .card, article, [class*='card'], li[class*='item']",
        "seletor_link": "a[href*='/imoveis/']",
        "filtro_estado": False,  # URL já filtra por PR
    },

    # frazaoleiloes.com.br
    "frazaoleiloes.com.br": {
        "urls_busca": [
            "https://www.frazaoleiloes.com.br/leiloes?estado=PR&tipo=imovel",
            "https://www.frazaoleiloes.com.br/imoveis?estado=PR",
            "https://www.frazaoleiloes.com.br",
        ],
        "seletor_card": ".lote, .card, article, [class*='lote'], [class*='card']",
        "seletor_link": "a[href*='lote'], a[href*='leilao']",
        "filtro_estado": True,
    },
}


def get_config_site(url_site):
    """Retorna configuração específica do site se existir"""
    for dominio, config in SITES_ESPECIFICOS.items():
        if dominio in url_site:
            return config
    return None


def buscar_imoveis_especifico(page, url_site, estados, config):
    """
    Busca imóveis em site com configuração específica.
    Usa seletores e URLs adequados para cada site.
    Retorna lista de resultados ou None se site não reconhecido.
    """
    site_config = get_config_site(url_site)
    if not site_config:
        return None  # Usa busca genérica

    resultados = []
    lance_min   = float(config.get("Lance Minimo", 0) or 0)
    lance_max   = float(config.get("Lance Maximo", 300000) or 300000)
    hoje        = datetime.today()
    limite      = hoje + timedelta(days=int(config.get("Dias ate o leilao", 30) or 30))

    for url in site_config["urls_busca"]:
        try:
            page.goto(url, timeout=20000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            # Esperar carregamento dinâmico
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

            texto_pagina = page.inner_text("body").lower()

            # Verificar bloqueio
            if any(x in texto_pagina for x in ["403 forbidden", "access denied", "just a moment", "cloudflare"]):
                continue

            # Busca por links de lotes/imóveis
            seletor_link = site_config["seletor_link"]
            links_encontrados = page.eval_on_selector_all(
                seletor_link,
                "els => els.map(el => ({href: el.href, texto: el.closest('[class]')?.innerText || el.innerText}))"
            )

            # Filtra por estado se necessário
            for item in links_encontrados[:50]:
                href = item.get("href", "")
                texto = item.get("texto", "")
                texto_lower = texto.lower()

                # Filtro de estado
                if site_config["filtro_estado"]:
                    tem_pr = (
                        "parana" in texto_lower or
                        " pr" in texto_lower or
                        "/pr" in texto_lower or
                        "- pr" in texto_lower or
                        "(pr)" in texto_lower or
                        ", pr" in texto_lower
                    )
                    if not tem_pr:
                        continue

                # Filtro de tipo (imóvel)
                palavras_imovel = ["apartamento", "casa ", "terreno", "sobrado",
                                   "kitnet", "flat", "galpao", "galpão", "sala",
                                   "loja", "imóvel", "imovel", "lote urb", "edificio"]
                palavras_veiculo = ["veiculo", "veículo", "caminhão", "onibus",
                                    "motocicleta", "caminhonete", "sucata", "automóvel"]
                palavras_terreno_vazio = ["gleba", "terreno vazio", "lote nu", "área nua", "sem construção"]

                if any(p in texto_lower for p in palavras_veiculo):
                    continue
                if any(p in texto_lower for p in palavras_terreno_vazio):
                    continue
                if not any(p in texto_lower for p in palavras_imovel):
                    # Tenta pelo link
                    if not any(p in href.lower() for p in ["imovel", "imov", "casa", "apart"]):
                        continue

                if not href or not href.startswith("http"):
                    continue

                # Extrair valores
                valores = re.findall(r'R\$\s*[\d\.,]+', texto)
                lance = None
                avaliacao = None
                if valores:
                    try:
                        v = valores[0].replace("R$", "").replace(".", "").replace(",", ".").strip()
                        lance = float(v)
                        if not (1000 <= lance <= 500_000_000):
                            lance = None
                    except Exception:
                        pass
                if len(valores) >= 2:
                    try:
                        v = valores[1].replace("R$", "").replace(".", "").replace(",", ".").strip()
                        avaliacao = float(v)
                        if not (1000 <= avaliacao <= 500_000_000):
                            avaliacao = None
                    except Exception:
                        pass

                if lance and (lance < lance_min or lance > lance_max):
                    continue

                desagio = None
                if avaliacao and lance and avaliacao > 0:
                    desagio = round(((avaliacao - lance) / avaliacao) * 100, 1)

                # Extrair data
                m = re.search(r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2,4})', texto)
                data_str = "Verificar"
                if m:
                    try:
                        d, mo, a = m.groups()
                        if len(a) == 2:
                            a = "20" + a
                        dt = datetime(int(a), int(mo), int(d))
                        if hoje <= dt <= limite:
                            data_str = dt.strftime("%d/%m/%Y")
                        elif dt < hoje:
                            continue  # leilão encerrado
                    except Exception:
                        pass

                titulo = texto.strip()[:150] if texto.strip() else href.split("/")[-1]

                resultados.append({
                    "Titulo": titulo,
                    "Estado": "PR",
                    "Lance": lance,
                    "Avaliacao": avaliacao,
                    "Desagio": desagio,
                    "Data": data_str,
                    "Link": href,
                })

            if resultados:
                break

        except Exception as e:
            if "ERR_NAME_NOT_RESOLVED" in str(e):
                return None
            continue

    return resultados
