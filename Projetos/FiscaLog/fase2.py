import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from supabase import create_client
from tabulate import tabulate
from datetime import datetime
import re
import configparser

# Crie um objeto ConfigParser
config = configparser.ConfigParser()

# Leia o arquivo de configuração
config.read('config.ini')

# Verifique se a seção 'SUPABASE' existe
if 'SUPABASE' in config:
    SUPABASE_URL = config['SUPABASE']['SUPABASE_URL']
    SUPABASE_KEY = config['SUPABASE']['SUPABASE_KEY']
else:
    print("Erro: Seção 'SUPABASE' não encontrada no arquivo de configuração.")
    exit(1)  # Encerra o programa se não encontrar a seção

# Cria o cliente do Supabase com as variáveis carregadas
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
# ===============================================
# CONFIGURAÇÃO DE LOGGING (sem logs no terminal)
# ===============================================
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

def obter_urls_nfce():
    """Busca todas as URLs de NFC-e salvas no Supabase."""
    try:
        response = supabase.table("notas_fiscais").select("url").execute()
        return [item["url"] for item in response.data]
    except Exception as e:
        logging.error(f"Erro ao obter URLs de NFC-e: {e}")
        return []

def obter_chave_acesso(url):
    """Busca a chave de acesso da URL existente na tabela 'notas_fiscais'."""
    try:
        response = supabase.table("notas_fiscais").select("chave_acesso").eq("url", url).execute()
        if response.data:
            return response.data[0]["chave_acesso"]
        else:
            logging.warning(f"Chave de acesso não encontrada para a URL: {url}")
            return None
    except Exception as e:
        logging.error(f"Erro ao obter chave de acesso para a URL {url}: {e}")
        return None

def verificar_dados_existentes(chave_acesso):
    """Verifica se os dados para a chave de acesso já existem na tabela 'notas_detalhes'."""
    try:
        response = supabase.table("notas_detalhes").select("chave_acesso").eq("chave_acesso", chave_acesso).execute()
        return len(response.data) > 0
    except Exception as e:
        logging.error(f"Erro ao verificar dados existentes para a chave de acesso {chave_acesso}: {e}")
        return False

def salvar_nfc_e_no_supabase(dados):
    """Salva os dados da NFC-e no Supabase."""
    chave_acesso = obter_chave_acesso(dados["url"])
    if not chave_acesso:
        logging.error("Chave de acesso não encontrada. Não foi possível salvar os dados.")
        return

    if verificar_dados_existentes(chave_acesso):
        logging.info(f"Dados já existentes para a chave de acesso {chave_acesso}. Pulando...")
        return

    try:
        dados["total_venda"] = float(dados["total_venda"].replace(",", ".")) if dados["total_venda"] else None
        if dados["data_hora_venda"]:
            dados["data_hora_venda"] = datetime.strptime(dados["data_hora_venda"], "%d/%m/%Y %H:%M:%S").isoformat()

        supabase.table("notas_detalhes").upsert([{
            "chave_acesso": chave_acesso,
            "data_hora_venda": dados["data_hora_venda"],
            "forma_pagamento": dados["forma_pagamento"],
            "total_venda": dados["total_venda"]
        }]).execute()

        for produto in dados["produtos"]:
            produto["quantidade"] = float(produto["quantidade"].replace("Qtde.:", "").replace(",", ".")) if produto["quantidade"] else None
            produto["preco_unitario"] = float(produto["preco_unitario"].replace("Vl. Unit.:", "").replace(",", ".")) if produto["preco_unitario"] else None
            produto["valor_total"] = float(produto["valor_total"].replace(",", ".").strip()) if produto["valor_total"] else None

            supabase.table("itens_nota").upsert([{
                "chave_acesso": chave_acesso,
                "produto": produto["produto"],
                "quantidade": produto["quantidade"],
                "preco_unitario": produto["preco_unitario"],
                "total_item": produto["valor_total"]
            }]).execute()

        logging.info("Dados salvos no Supabase com sucesso!")
    except Exception as e:
        logging.error(f"Erro ao salvar dados no Supabase: {e}")

# ===============================================
# INICIAR DRIVER
# ===============================================
def iniciar_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--allow-insecure-localhost")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    return driver

# ===============================================
# CONSULTA DE NFC-e COM REINTENTOS EM CASO DE ERRO
# ===============================================
def consultar_nfce(url, tentativas=3):
    tentativa = 1
    chave_acesso = obter_chave_acesso(url)
    
    # Verificar se os dados já foram salvos no Supabase
    if chave_acesso and verificar_dados_existentes(chave_acesso):
        print(f"\nDados já lidos para a URL {url}.\n")
        return None

    while tentativa <= tentativas:
        try:
            logging.info(f"Acessando NFC-e: {url}")
            driver = iniciar_driver()
            wait = WebDriverWait(driver, 15)
            driver.get(url)

            iframe_element = wait.until(EC.presence_of_element_located((By.XPATH, '//iframe[contains(@src, "danfeNFCe")]')))
            driver.switch_to.frame(iframe_element)

            dados = {   
                "url": url,
                "produtos": []
            }

            # Extrair Data/Hora da Venda
            emissao = wait.until(EC.presence_of_element_located((By.XPATH, '/html/body/div[1]/div[4]/div/div[2]/div[2]/div[1]/div/ul/li'))).text
            match = re.search(r"Emissão:\s*(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})", emissao)
            if match:
                dados["data_hora_venda"] = match.group(1)
            else:
                dados["data_hora_venda"] = None

            # Extrair Produtos
            produtos = []
            linhas = wait.until(EC.presence_of_all_elements_located((By.XPATH, '/html/body/div[1]/div[4]/div/div[2]/div[1]/table/tbody/tr')))
            for linha in linhas:
                nome = linha.find_element(By.XPATH, './/td[1]/span[1]').text
                quantidade = linha.find_element(By.XPATH, './/td[1]/span[3]').text
                preco_unitario = linha.find_element(By.XPATH, './/td[1]/span[5]').text
                total_item = linha.find_element(By.XPATH, './/td[2]/span').text

                produtos.append({
                    "produto": nome,
                    "quantidade": quantidade,
                    "preco_unitario": preco_unitario,
                    "valor_total": total_item
                })
            dados["produtos"] = produtos

            # Extrair Total e Forma de Pagamento
            total = wait.until(EC.presence_of_element_located((By.XPATH, '/html/body/div[1]/div[4]/div/div[2]/div[1]/div[3]/div[2]/span'))).text
            dados["total_venda"] = total

            forma_pg = wait.until(EC.presence_of_element_located((By.XPATH, '/html/body/div[1]/div[4]/div/div[2]/div[1]/div[3]/div[4]/label'))).text
            dados["forma_pagamento"] = forma_pg

            driver.quit()
            salvar_nfc_e_no_supabase(dados)
            print_dados(dados)
            return dados  # Retornar dados após salvar com sucesso
        except Exception as e:
            logging.error(f"Erro na tentativa {tentativa} ao consultar a NFC-e: {e}")
            tentativa += 1
            if tentativa > tentativas:
                logging.error(f"Falha ao tentar acessar {url} após {tentativas} tentativas.")
                driver.quit()
                return None  # Retorna None após várias falhas

# ===============================================
# EXIBIÇÃO DOS DADOS EXTRAÍDOS
# ===============================================
def print_dados(dados):
    print("\n" + "="*40)
    print(f"Data e Hora da Venda: {dados['data_hora_venda']}")
    if dados["produtos"]:
        print("\nProdutos:")
        tabela_produtos = []
        for produto in dados["produtos"]:
            tabela_produtos.append([produto["produto"], produto["quantidade"], produto["preco_unitario"], produto["valor_total"]])
        headers = ["Produto", "Quantidade", "Preço Unitário", "Valor Total"]
        print(tabulate(tabela_produtos, headers, tablefmt="fancy_grid", numalign="right"))
    else:
        print("Nenhum produto encontrado.")
    print(f"\nTotal da Venda: {dados['total_venda']}")
    print(f"Forma de Pagamento: {dados['forma_pagamento']}")
    print("\nDados salvos no Supabase")
    print("="*40 + "\n")

# EXECUTAR
urls = obter_urls_nfce()
for url in urls:
    consultar_nfce(url)