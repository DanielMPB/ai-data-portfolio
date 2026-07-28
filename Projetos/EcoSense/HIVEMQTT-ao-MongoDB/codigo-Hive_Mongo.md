# ☁️ Backend de Ingestão de Dados IoT e Integração NoSQL

Este diretório contém os microsserviços desenvolvidos em Python responsáveis pela recepção, validação e persistência dos dados telemétricos gerados pelos nós sensores (ex: ESP32). A arquitetura suporta tanto fluxos de dados assíncronos (Publish/Subscribe) quanto requisições síncronas (Cliente/Servidor).



---

## 🏗️ Visão Geral da Arquitetura

O sistema de retaguarda (*backend*) foi projetado sob uma abordagem híbrida de ingestão, centralizando o armazenamento em um banco de dados orientado a documentos (MongoDB).

| Módulo | Protocolo | Natureza da Comunicação | Função Principal |
| :--- | :--- | :--- | :--- |
| **Integração HiveMQ** | MQTT (TLS) | Assíncrona | Escuta contínua de tópicos de telemetria em nuvem. |
| **API REST Flask** | HTTP (POST) | Síncrona | Recepção direta de pacotes estruturados via rede local/web. |
| **Database Driver** | NoSQL / BSON | Armazenamento | Persistência dos dados brutos com injeção de *timestamp*. |

---

## 📦 Dependências de Software

Para a execução adequada dos *scripts* em ambiente local ou conteinerizado, é necessária a instalação dos seguintes pacotes Python (recomenda-se o uso de ambiente virtual `venv`):

* `paho-mqtt`: Cliente MQTT para subscrição e processamento de mensagens.
* `pymongo`: *Driver* oficial para comunicação com instâncias do MongoDB e MongoDB Atlas.
* `Flask`: *Microframework* para o roteamento e exposição dos *endpoints* da API.

---

## 📄 Detalhamento dos Microsserviços

### 1. Ingestor MQTT (`Hive_principal.py` / `MQTT.py`)
* **Objetivo:** Estabelecer um canal seguro de recepção de dados via HiveMQ Cloud.
* **Mecanismos de Segurança:** Implementa criptografia de transporte via `ssl.PROTOCOL_TLS` e autenticação por usuário/senha.
* **Operação:** O *script* roda em um *loop* infinito (`loop_forever()`) com tratamento de exceções para reconexão automática em caso de queda de rede. Ao receber um *payload* válido no tópico inscrito (ex: `sensores/ar`), o sistema decodifica o JSON, anexa uma estampa de tempo UTC (`received_at`) e insere o documento na coleção especificada no MongoDB Atlas.

### 2. API de Ingestão Síncrona (`MongoDB.py`)
* **Objetivo:** Prover uma interface HTTP programável para envio direto de dados estruturados.
* **Endpoint de Coleta:** `/api/colecao` (Método: `POST`).
* **Validação de Payload:** A rota implementa uma barreira de integridade que rejeita requisições (Erro 400 *Bad Request*) caso o corpo do JSON não contenha as chaves estritas: `"temperatura"`, `"umidade_ar"` e `"umidade_solo"`.
* **Operação:** Após a validação, injeta a estampa de tempo local (`dataRegistro`), executa a persistência no MongoDB e retorna uma resposta JSON (Status 201 *Created*) contendo o `_id` do documento gerado.