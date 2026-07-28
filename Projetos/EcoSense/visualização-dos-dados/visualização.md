# 📊 Plataforma de Monitoramento Ambiental e Gêmeo Digital (IoT)

Este diretório contém a infraestrutura de *frontend* (painel de visualização analítica) e o motor de injeção de dados baseados em Inteligência Artificial para o projeto de monitoramento da qualidade do ar na região de Goiânia.



---

## 🖥️ Módulo 1: Dashboard Analítico
**Tecnologias:** `Streamlit`, `Pandas`, `Plotly`, `PyDeck`, `PyMongo`

Este módulo atua como a interface de usuário (UI) do sistema. Ele consome dados diretamente do MongoDB Atlas e os renderiza em tempo real.
* **Mapeamento Geoespacial 3D:** Utiliza a biblioteca PyDeck para plotar cilindros colorimétricos sobre os setores monitorados em Goiânia, indicando o volume de carga poluente.
* **Filtros Temporais e Espaciais:** Permite a segmentação da base de dados por período específico (dia/hora) e bairro, otimizando o consumo de memória ao limitar as *queries* aos últimos 15.000 registros.
* **Análise de Indicadores (KPIs):** Calcula e exibe a média de Partículas Finas (PM2.5), concentração de gases (PPM) e a incidência de anomalias atmosféricas reais.
* **Comparativo de *Baseline*:** Plota a evolução temporal da poluição medida em contraste com a carga estimada pela IA.

---

## 🤖 Módulo 2: Simulador de Dados (Digital Twin)
**Tecnologias:** `Scikit-Learn`, `Numpy`, `Requests`, `Joblib`

> **⚠️ OBSERVAÇÃO TÉCNICA IMPORTANTE:** > Este arquivo (simulador.py) foi desenvolvido para operar **exclusivamente como um simulador de dados**. Ele não extrai informações de sensores físicos de hardware. Sua função é atuar como um "Gêmeo Digital", gerando telemetria sintética de alta fidelidade para popular o banco de dados. Isso viabiliza o teste de estresse da aplicação, o treinamento da interface visual e a homologação da arquitetura na ausência de sensores ativos em campo.

**Características de Operação:**
* **Treinamento e Cache de IA:** Utiliza algoritmos de *Random Forest* para modelar o comportamento de dispersão de poluentes. O modelo treinado é salvo no disco (`.pkl`) para economizar recursos computacionais em execuções futuras.
* **Condições Climáticas Reais:** O simulador não é totalmente cego; ele realiza requisições HTTPS para a API `Open-Meteo`, extraindo a temperatura e umidade reais do momento em Goiânia para condicionar os cálculos matemáticos.
* **Dinâmica de Tráfego:** Implementa funções gaussianas para simular o comportamento do trânsito humano (picos matutinos, horários de almoço suavizados e picos vespertinos), gerando variabilidade cronológica e adicionando "ruído" (*jitter*) estocástico para garantir realismo estatístico.
* **Injeção de Dados:** O laço de repetição (`loop`) é acionado a cada 300 segundos (5 minutos), enviando o vetor de informações simuladas diretamente para a coleção do MongoDB Atlas.

---

## ⚙️ Protocolo de Execução

Para iniciar a visualização e a geração de dados simultaneamente, recomenda-se a abertura de dois terminais paralelos:

**Terminal 1 (Geração de Dados):**
```bash
python simulador.py