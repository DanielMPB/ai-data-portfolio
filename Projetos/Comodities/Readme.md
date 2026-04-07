# Commodity-analise
Este projeto Python analisa dados de importação de commodities por país, permitindo visualizar rankings, buscar informações específicas e obter recomendações de investimento baseadas no perfil do usuário.

# Funcionalidades Principais
- Carregamento de dados: Importa informações de um arquivo CSV sobre importações de commodities
- Ranking de países: Exibe os top 10 países por valor total de importações
- Busca por país: Mostra detalhes das importações de um país específico
- Lista de commodities: Apresenta categorias organizadas (alimentos, energia, químicos, etc.)
- Filtro por commodity: Lista países que importam uma commodity específica
- Recomendações: Sugere commodities baseadas no perfil de investimento (Conservador, Moderado ou Ousado)

# Como Usar
1. Execute o script Python
2. Utilize o menu interativo para:
   - Ver rankings (opção 1)
   - Buscar um país (opção 2)
   - Explorar a lista de commodities (opção 3)
   - Filtrar países por commodity (opção 4)
   - Obter recomendações (opção 5)

# Requisitos
- Python 3.x
- Arquivo CSV "value_of_imports.csv" no mesmo diretório

# Estrutura do Código
- Funções principais: carregar_dados_do_csv(), busca_dado(), menu()
- Funções auxiliares: exibir_ranking(), buscar_pais(), ver_lista_commodities(), etc.
- Sistema de perfil de investidor com recomendações personalizadas

Este projeto é útil para análise de comércio internacional e tomada de decisões de investimento em commodities.
