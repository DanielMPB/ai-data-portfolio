import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from supabase import create_client
from datetime import datetime
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

# Função para obter os dados filtrados do Supabase
def obter_dados_vendas(data_inicio, data_fim, forma_pagamento):
    # Alterado para consultar a tabela "notas_detalhes" para pegar a "data_hora_venda"
    query = supabase.table("notas_detalhes").select("*").gte("data_hora_venda", data_inicio).lte("data_hora_venda", data_fim)

    if forma_pagamento != "Todas":
        query = query.eq("forma_pagamento", forma_pagamento)

    return query.execute().data

# Função para calcular e exibir métricas
def calcular_metricas(dados):
    total_vendas = sum([item['total_venda'] for item in dados])
    num_transacoes = len(dados)
    valor_medio_venda = total_vendas / num_transacoes if num_transacoes > 0 else 0
    return total_vendas, num_transacoes, valor_medio_venda

# Função para gerar os gráficos
def gerar_graficos(dados):
    # Convertendo os dados para DataFrame
    df = pd.DataFrame(dados)

    # Verificando se a coluna 'forma_pagamento' existe
    if 'forma_pagamento' not in df.columns:
        st.error("A coluna 'forma_pagamento' não foi encontrada nos dados.")
        return

    # Filtrando os dados: remover linha onde 'forma_pagamento' está vazio ou igual a 'Valor a Pagar'
    df = df[df['forma_pagamento'] != '']
    df = df[df['forma_pagamento'] != 'Valor a Pagar']

    # Substituindo 'Valor a Pagar' por 'Não Especificado'
    df['forma_pagamento'] = df['forma_pagamento'].replace('Valor a pagar R$:', 'Não Especificado')

    # Convertendo 'data_hora_venda' para datetime
    df['data_hora_venda'] = pd.to_datetime(df['data_hora_venda'])

    # Adicionando colunas de agrupamento por dia, semana e mês
    df['dia'] = df['data_hora_venda'].dt.date
    df['semana'] = df['data_hora_venda'].dt.isocalendar().week
    df['mes'] = df['data_hora_venda'].dt.month

    # Total de vendas por dia, semana e mês
    vendas_diarias = df.groupby('dia')['total_venda'].sum()
    vendas_semanal = df.groupby('semana')['total_venda'].sum()
    vendas_mensal = df.groupby('mes')['total_venda'].sum()

    # Gráfico: Total de vendas por dia
    plt.figure(figsize=(10, 6))
    vendas_diarias.plot(kind='bar', color='skyblue')
    plt.title("Total de Vendas por Dia")
    plt.ylabel("Vendas (R$)")
    st.pyplot(plt)

    # Gráfico: Total de vendas por semana
    plt.figure(figsize=(10, 6))
    vendas_semanal.plot(kind='bar', color='lightgreen')
    plt.title("Total de Vendas por Semana")
    plt.ylabel("Vendas (R$)")
    st.pyplot(plt)

    # Gráfico: Total de vendas por mês
    plt.figure(figsize=(10, 6))
    vendas_mensal.plot(kind='bar', color='salmon')
    plt.title("Total de Vendas por Mês")
    plt.ylabel("Vendas (R$)")
    st.pyplot(plt)

    # Comparativo entre formas de pagamento
    pagamento_comparativo = df.groupby('forma_pagamento')['total_venda'].sum()
    
    # Gráfico: Comparativo de Vendas por Forma de Pagamento
    plt.figure(figsize=(10, 6))
    pagamento_comparativo.plot(kind='bar', color='purple')
    plt.title("Comparativo de Vendas por Forma de Pagamento")
    plt.ylabel("Vendas (R$)")
    st.pyplot(plt)



# Streamlit Interface
def dashboard():
    st.title("📊 Análise Fiscal BI: Coleta e Visualização Automatizada")

    # Filtros
    st.subheader("Filtros de Dados")
    data_inicio = st.date_input("Data de Início", value=datetime(2024, 3, 1))
    data_fim = st.date_input("Data de Fim", value=datetime(2025, 11, 21))
    
    # Alterando as opções de forma de pagamento para incluir Cartão de Crédito e Cartão de Débito
    forma_pagamento = st.selectbox("Forma de Pagamento", ["Todas", "Cartão de Crédito", "Cartão de Débito", "Dinheiro", "Vale Alimentação"])

    # Obtendo os dados
    dados = obter_dados_vendas(data_inicio.strftime('%Y-%m-%d'), data_fim.strftime('%Y-%m-%d'), forma_pagamento)

    if dados:
        # Calcular e exibir métricas
        total_vendas, num_transacoes, valor_medio_venda = calcular_metricas(dados)
        st.metric("Total de Vendas (R$)", f"R$ {total_vendas:.2f}")
        st.metric("Valor Médio por Venda (R$)", f"R$ {valor_medio_venda:.2f}")

        # Exibir gráficos
        gerar_graficos(dados)
    else:
        st.warning("Nenhum dado encontrado para os filtros selecionados.")



if __name__ == "__main__":
    dashboard()