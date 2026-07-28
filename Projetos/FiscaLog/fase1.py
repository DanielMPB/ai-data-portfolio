import cv2
import re
from datetime import datetime
from pyzbar.pyzbar import decode
from supabase import create_client
import streamlit as st
import numpy as np
from PIL import Image
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

# ============================================================
# FUNÇÃO PARA LER QR CODE (webcam ou imagem)
# ============================================================
def ler_qrcode(frame):
    """
    Detecta o QR Code em um frame da câmera.
    """
    qrs = decode(frame)
    if qrs:
        return qrs[0].data.decode("utf-8")
    return None

# ============================================================
# FUNÇÃO PARA LER QR CODE DE IMAGEM UPLOAD
# ============================================================
def ler_qrcode_imagem(uploaded_file):
    """
    Detecta e lê o QR Code de uma imagem carregada.
    """
    # Abrir a imagem usando PIL
    img = Image.open(uploaded_file)
    img = np.array(img)

    # Usando pyzbar para detectar QR Code
    qrs = decode(img)
    if qrs:
        return qrs[0].data.decode("utf-8")
    return None

# ============================================================
# EXTRAÇÃO DE URL E CHAVE DE ACESSO
# ============================================================
def extrair_dados(qr_text):
    url = qr_text.strip()  # Mantém EXATAMENTE como vem
    padrao_chave = r"[0-9]{44}"
    encontrado = re.findall(padrao_chave, url)
    chave = encontrado[0] if encontrado else None
    return {"url_cupom": url, "chave_acesso": chave}

# ============================================================
# FUNÇÃO PARA SALVAR NO SUPABASE
# ============================================================
def salvar_supabase(url, chave):
    data = {
        "url": url,
        "chave_acesso": chave,
        "data_hora_leitura": datetime.now().isoformat()
    }
    return supabase.table("notas_fiscais").insert(data).execute()

# ============================================================
# FUNÇÃO PARA EXIBIR AS CHAVES DE ACESSO CADASTRADAS
# ============================================================
def exibir_chaves_cadastradas():
    # Busca as chaves de acesso já cadastradas no Supabase
    resultado = supabase.table("notas_fiscais").select("chave_acesso").execute()

    if resultado.data:
        st.subheader("Chaves de Acesso Cadastradas:")
        with st.expander("Ver chaves cadastradas"):
            # Exibe a lista de chaves com uma altura máxima
            for i, item in enumerate(resultado.data):
                st.write(f"{i+1}. {item['chave_acesso']}")
    else:
        st.write("Nenhuma chave de acesso encontrada.")

# ============================================================
# STREAMLIT INTERFACE - ADICIONAR FUNCIONALIDADES COM MENU DE ESCOLHA
# ============================================================
def iniciar_leitura():
    st.title("📷 Leitor de QR Code de Nota Fiscal (NFC-e)")

    # Criação do menu de escolha
    opcao = st.selectbox("Escolha a funcionalidade", 
                         ["Leitura ao Vivo (Câmera)", "Fazer upload de QR Code", "Exibir Chaves Salvas"])

    if opcao == "Leitura ao Vivo (Câmera)":
        st.write("📸 A câmera será ativada automaticamente e o QR Code será lido assim que entrar no foco.")
        
        # Fonte da webcam
        fonte = 0  # Para usar a webcam
        cap = cv2.VideoCapture(fonte)  # Inicia a captura da webcam

        stframe = st.empty()  # Cria um espaço vazio para exibir o vídeo

        # Loop de captura contínua
        while True:
            ret, frame = cap.read()
            if not ret:
                st.write("Erro ao capturar vídeo.")
                break

            # Converte a imagem para RGB (Streamlit espera essa cor)
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # Exibe a imagem da câmera no Streamlit com ajuste automático de largura
            stframe.image(frame_rgb, channels="RGB", use_container_width=True)

            # Tenta ler o QR Code
            texto_qr = ler_qrcode(frame)
            if texto_qr:
                st.write(f"QR Code detectado: {texto_qr}")

                # Extrair dados do QR Code
                dados = extrair_dados(texto_qr)

                if dados["chave_acesso"]:
                    chave = dados["chave_acesso"]

                    # Verifica se o cupom já foi salvo
                    existe = supabase.table("notas_fiscais").select("chave_acesso").eq("chave_acesso", chave).execute()

                    if not existe.data:
                        # Se a chave não existe, salva no Supabase
                        salvar_supabase(url=dados["url_cupom"], chave=chave)
                        st.write("✅ Cupom salvo com sucesso!")
                        st.write(f"Chave de Acesso: {chave}")
                        st.write(f"URL: {dados['url_cupom']}")
                    else:
                        st.write("⚠️ Cupom já lido!")
                break  # Interrompe o loop após salvar a chave

        cap.release()  # Libera a câmera após terminar

    elif opcao == "Fazer upload de QR Code":
        st.write("Faça o upload de uma imagem contendo um QR Code.")
        file = st.file_uploader("Selecione uma imagem de nota fiscal (JPG, PNG)...", type=["jpg", "jpeg", "png"])

        if file:
            img = Image.open(file)
            texto_qr_imagem = ler_qrcode_imagem(file)
            if not texto_qr_imagem:
                st.warning("⚠ Não foi possível decodificar o QR Code. Tente outra imagem.")
            else:
                dados = extrair_dados(texto_qr_imagem)
                if dados["chave_acesso"]:
                    chave = dados["chave_acesso"]
                    # Verifica se a chave já existe no Supabase
                    existe = supabase.table("notas_fiscais").select("chave_acesso").eq("chave_acesso", chave).execute()
                    if not existe.data:
                        # Se a chave não existe, salva no Supabase
                        salvar_supabase(url=dados["url_cupom"], chave=chave)
                        st.success(f"✅ Chave salva: {chave}")
                    else:
                        st.info(f"⚠ Chave já existente: {chave}")
                else:
                    st.error("❌ Nenhuma chave válida (44 dígitos) foi encontrada.")

    elif opcao == "Exibir Chaves Salvas":
        st.write("🔑 Aqui estão as chaves de acesso salvas no banco de dados Supabase.")
        exibir_chaves_cadastradas()

# ============================================================
# EXECUÇÃO STREAMLIT
# ============================================================
if __name__ == "__main__":
    iniciar_leitura()