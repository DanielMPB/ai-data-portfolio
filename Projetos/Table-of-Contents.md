# 📂 Portfólio de Projetos - Inteligência Artificial e Engenharia de Dados

Este repositório consolida implementações práticas e arquiteturas de software focadas na extração de valor a partir de dados. Cada diretório listado abaixo contém uma solução pontual para problemas reais de análise, automação e estruturação de informações.

---

## 🗂️ Índice Central de Projetos

| Projeto | Domínio de Aplicação | Tecnologias Empregadas | Status | Acesso Direto |
| :--- | :--- | :--- | :---: | :---: |
| **[1. Comodities](#1-Comodities)** | Ciência de Dados / Finanças | `Python` `Pandas` | ✅ Concluído | [📁 Acessar Pasta](./Comodities) |
| **[2. EcoSense](#2-EcoSense)** | IoT / Monitoramento Ambiental | `Python` `C++` `MongoDB` `MQTT` | ✅ Concluído | [📁 Acessar Pasta](./EcoSense) |
| **[3. FiscaLog](#3-FiscaLog)** | Engenharia de Dados / Fiscal | `Python` `ETL` `XML` | ✅ Concluído | [📁 Acessar Pasta](./FiscaLog) |

---

## 📄 Resumo Executivo dos Projetos

### 1. Comodities
Sistema de análise de dados globais de importação de *Comodities*. Transforma conjuntos de dados brutos em inteligência financeira estruturada, oferecendo ranqueamento de países, filtragem cruzada de ativos e um motor de recomendação de investimentos baseado no perfil de risco do usuário.
👉 **[Consulte o diretório do projeto](./Comodities) para visualizar a interface de análise e as instruções de execução.**

### 2. EcoSense
Plataforma IoT ponta a ponta para monitoramento da qualidade do ar (particulados e gases tóxicos) e de variáveis climáticas. A arquitetura integra nós sensores físicos (ESP32), ingestão de telemetria em tempo real (via MQTT e REST), persistência em banco de dados NoSQL (MongoDB) e um painel analítico interativo. O ecossistema inclui também um "Gêmeo Digital", que utiliza modelagem preditiva de Inteligência Artificial para gerar cenários sintéticos de poluição baseados no tráfego urbano e clima.
👉 **[Consulte o diretório do projeto](./EcoSense) para acessar o código-fonte de hardware e as dependências do software.**

### 3. FiscaLog
*Pipeline* de processamento (ETL) dedicado à engenharia de dados fiscais. O sistema atua em três camadas determinísticas para ingerir, extrair e transformar documentos XML não estruturados (Notas Fiscais Eletrônicas) em *datasets* tabulares prontos para visualização e aplicação de regras de negócio.
👉 **[Consulte o diretório do projeto](./FiscaLog) para analisar o diagrama da arquitetura e o fluxo metodológico das fases de processamento.**

---

**Nota Técnica:** O aprofundamento algorítmico, as lógicas de negócio e as orientações para replicação local dos ambientes virtuais encontram-se documentados no arquivo `README.md` interno de cada respectiva pasta.