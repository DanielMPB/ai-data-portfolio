# 📡 Nó de Aquisição de Dados Ambientais - IoT

Este diretório contém os módulos de software embarcado desenvolvidos para a leitura de métricas atmosféricas e de qualidade do ar. O sistema foi arquitetado para o microcontrolador **ESP32**, atuando como um nó de coleta (IoT) para a extração de dados brutos e conversão em métricas estruturadas.



---

## 🔌 Topologia de Hardware e Pinagem

Abaixo encontra-se o mapeamento determinístico das conexões físicas (GPIOs) entre os sensores e o ESP32:

| Sensor | Grandeza Medida | Protocolo / Interface | Pino ESP32 |
| :--- | :--- | :--- | :---: |
| **MQ-135** | Qualidade do Ar (PPM / Gases) | Analógica (ADC) | `GPIO 34` |
| **PMS5003** | Material Particulado (PM 2.5) | UART (Serial) | `RX: 16` / `TX: 17` |
| **DHT11** | Temperatura e Umidade | Digital (1-Wire) | `GPIO 26` |

*Nota de Engenharia: O pino GPIO 34 no ESP32 opera estritamente como entrada (input-only), sendo ideal para as leituras do conversor analógico-digital (ADC) exigidas pelo MQ-135.*

---

## 📦 Dependências de Software

Para a compilação adequada dos módulos na IDE Arduino ou PlatformIO, é obrigatória a instalação das seguintes bibliotecas externas:
1. `MQ135.h`: Biblioteca para processamento dos níveis de resistência e cálculo de PPM do sensor de gás.
2. `DHT.h`: Biblioteca de controle unificado para sensores de temperatura e umidade da família DHT (requer a biblioteca *Adafruit Unified Sensor* como dependência base).

---

## 📄 Detalhamento dos Módulos

### 1. Módulo `MQ_135.ino` / `.cpp`
* **Objetivo:** Quantificar a concentração de gases poluentes na atmosfera.
* **Operação:** Realiza a leitura da tensão analógica bruta (*Raw ADC*), processa a resistência base de calibração (*RZero*) e calcula a estimativa de Partes Por Milhão (PPM).
* **Taxa de Amostragem:** 1.500 milissegundos.

### 2. Módulo `PMS5003.ino` / `.cpp`
* **Objetivo:** Monitoramento de material particulado fino (PM 2.5).
* **Operação:** Estabelece comunicação serial bidirecional (*Baud Rate:* 9600). O algoritmo implementa uma rotina de *parsing* e validação de pacotes (*checksum*) que lê continuamente blocos de 32 *bytes* do sensor, isolando e extraindo exclusivamente o valor de concentração de PM 2.5 padrão atmosférico.
* **Taxa de Amostragem:** Orientada por interrupção de pacote disponível (*stream* contínuo).

### 3. Módulo `Umidade_Temperatura.ino` / `.cpp`
* **Objetivo:** Coleta das variáveis climáticas fundamentais.
* **Operação:** Inicializa o protocolo de comunicação com o DHT11 e extrai os valores de temperatura (em graus Celsius) e umidade relativa do ar (em percentual). Possui rotina de tratamento de exceção (`isnan()`) para contornar falhas de sincronia na leitura digital.
* **Taxa de Amostragem:** 2.000 milissegundos.