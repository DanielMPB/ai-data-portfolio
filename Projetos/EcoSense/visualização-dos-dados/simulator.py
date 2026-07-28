import time
import requests
import datetime
import urllib.parse
import os
import numpy as np
import pandas as pd
import joblib  # Para salvar/carregar o modelo (pip install joblib)
from pymongo import MongoClient
from sklearn.ensemble import RandomForestRegressor

# ==============================================================================
# 1. CONFIGURAÇÕES
# ==============================================================================

# --- CREDENCIAIS ---
MONGO_USER = "user"
MONGO_PASS = "senha"
MONGO_CLUSTER = "cluster"
MONGO_APP_NAME = "app_name"

username = urllib.parse.quote_plus(MONGO_USER)
password = urllib.parse.quote_plus(MONGO_PASS)

MONGO_URI = f"mongodb+srv://{username}:{password}@{MONGO_CLUSTER}/?retryWrites=true&w=majority&appName={MONGO_APP_NAME}"

DB_NAME = "data_base"
COLLECTION_NAME = "solection"

INTERVALO_LEITURA = 300 

GOIANIA_LAT = -16.6869
GOIANIA_LON = -49.2648

# ==============================================================================
# 2. CÉREBRO DA IA - V4 (COM CACHE DE MODELO E JITTER)
# ==============================================================================

class DigitalTwinAI:
    def __init__(self):
        print("\n🧠 [AI] Inicializando Motor V4 (Pico de Almoço Suavizado)...")
        self.model_pm25 = None
        self.model_gases = None
        self.file_pm25 = "model_pm25.pkl"
        self.file_gases = "model_gases.pkl"
        
        # Tenta carregar modelos existentes para economizar tempo
        if os.path.exists(self.file_pm25) and os.path.exists(self.file_gases):
            print("📂 [AI] Carregando modelos pré-treinados do disco...")
            self.model_pm25 = joblib.load(self.file_pm25)
            self.model_gases = joblib.load(self.file_gases)
        else:
            print("⚙️ [AI] Modelos não encontrados. Iniciando treinamento...")
            self._treinar_modelos()
            print("✅ [AI] Modelos treinados e salvos no disco.\n")

    def _gerar_dados_sinteticos(self):
        """
        Gera dados onde o almoço é um 'bump' suave, não um pico agressivo.
        """
        n_samples = 6000 
        np.random.seed(42)

        hora = np.random.randint(0, 24, n_samples)
        dia_semana = np.random.randint(0, 7, n_samples)
        temp = np.random.normal(30, 4, n_samples)
        umidade = np.random.uniform(15, 90, n_samples)
        fator_local = np.random.choice([0.8, 1.0, 1.2, 1.4], n_samples)

        # --- FÍSICA DE TRÁFEGO V4 ---
        is_fds = dia_semana >= 5
        
        # Pico Manhã (08h) - Mantém forte e concentrado
        pico_manha = np.exp(-((hora - 8)**2)/4)
        
        # Pico Almoço (12h30) - RECALIBRADO
        pico_almoco = np.exp(-((hora - 12.5)**2)/5) * 0.55 
        
        # Pico Tarde (18h) - O mais forte
        pico_tarde = np.exp(-((hora - 18)**2)/5)

        trafego_dia_util = pico_manha + pico_almoco + pico_tarde
        trafego_base = np.where(is_fds, 0.2, trafego_dia_util)
        
        # Base de ruído urbano
        trafego_base = np.clip(trafego_base + 0.15, 0.15, 1.3)

        # --- POLUIÇÃO V4 ---
        
        # 1. GASES (MQ-135)
        y_gases = (120 + (trafego_base * 320)) * fator_local
        y_gases += (temp * 3)
        y_gases += np.random.normal(0, 15, n_samples)
        y_gases = np.clip(y_gases, 40, 750) 

        # 2. PM2.5 (Poeira Fina)
        y_pm25 = (5 + (trafego_base * 32)) * fator_local
        
        # Chuva limpa
        fator_limpeza = np.where(umidade > 80, 0.6, 1.0 - (umidade / 450))
        y_pm25 = y_pm25 * fator_limpeza
        
        y_pm25 += np.random.normal(0, 1.5, n_samples)
        
        # CLIP: Teto realista para dias comuns
        y_pm25 = np.clip(y_pm25, 1, 90) 

        X = pd.DataFrame({
            'hora': hora, 'dia_semana': dia_semana, 
            'temp': temp, 'umidade': umidade, 'fator_local': fator_local
        })
        return X, y_pm25, y_gases

    def _treinar_modelos(self):
        X, y_pm25, y_gases = self._gerar_dados_sinteticos()
        
        self.model_pm25 = RandomForestRegressor(n_estimators=50, max_depth=10, random_state=42)
        self.model_gases = RandomForestRegressor(n_estimators=50, max_depth=10, random_state=42)
        
        self.model_pm25.fit(X, y_pm25)
        self.model_gases.fit(X, y_gases)
        
        # Salva os modelos para uso futuro
        joblib.dump(self.model_pm25, self.file_pm25)
        joblib.dump(self.model_gases, self.file_gases)

    def prever(self, data_hora, temp_real, hum_real, fator_local):
        entrada = pd.DataFrame([{
            'hora': data_hora.hour,
            'dia_semana': data_hora.weekday(),
            'temp': temp_real,
            'umidade': hum_real,
            'fator_local': fator_local
        }])

        # 1. Previsão Base (Padrão Matemático)
        pred_pm25 = self.model_pm25.predict(entrada)[0]
        pred_gases = self.model_gases.predict(entrada)[0]

        # 2. JITTER / RUÍDO (Simulação de Realismo)
        # Adiciona uma pequena variação aleatória para evitar dados idênticos
        # mesmo quando temperatura e hora não mudam.
        
        # Variação de +/- 2.5 no PM2.5
        ruido_pm = np.random.uniform(-2.5, 2.5)
        
        # Variação de +/- 15 nos gases
        ruido_gases = np.random.randint(-15, 15)
        
        # Aplica o ruído garantindo que não fique negativo
        val_final_pm = max(0.5, pred_pm25 + ruido_pm)
        val_final_gases = max(10, pred_gases + ruido_gases)

        return round(val_final_pm, 2), int(val_final_gases)

# ==============================================================================
# 3. DADOS GEOGRÁFICOS
# ==============================================================================

SETORES = {
    "Setor Central":             {"coords": {"lat": -16.6799, "lon": -49.2550}, "fator": 1.5,  "temp_offset": 2.2}, # Aumentado fator e calor (Centro denso)
    "Setor Bueno":               {"coords": {"lat": -16.7050, "lon": -49.2680}, "fator": 1.3,  "temp_offset": 1.5},
    "Setor Jaó":                 {"coords": {"lat": -16.6420, "lon": -49.2150}, "fator": 0.8,  "temp_offset": -1.0},
    "Jardim Goiás":              {"coords": {"lat": -16.7000, "lon": -49.2400}, "fator": 1.0,  "temp_offset": -0.5},
    "Setor Norte Ferroviário":   {"coords": {"lat": -16.6650, "lon": -49.2600}, "fator": 1.25, "temp_offset": 1.0}  # Reduzido levemente para diferenciar do Centro
}

def get_clima_real():
    url = f"https://api.open-meteo.com/v1/forecast?latitude={GOIANIA_LAT}&longitude={GOIANIA_LON}&current=temperature_2m,relative_humidity_2m,weather_code&timezone=America%2FSao_Paulo"
    
    # Tenta 3 vezes antes de desistir (Robustez)
    for tentativa in range(3):
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()['current']
            
            codigos_chuva = [51, 53, 55, 61, 63, 65, 80, 81, 82]
            condicao = "Chuva" if data['weather_code'] in codigos_chuva else "Estável"
            
            return {
                "temp_base": data['temperature_2m'],
                "hum_base": data['relative_humidity_2m'],
                "condicao": condicao
            }
        except Exception as e:
            if tentativa < 2:
                time.sleep(2) # Espera 2s antes de tentar de novo
            else:
                print(f"⚠️ Erro ao obter clima (Tentativa {tentativa+1}): {e}")
                
    # Fallback se todas as tentativas falharem
    return {"temp_base": 30.0, "hum_base": 45.0, "condicao": "Simulado"}

# ==============================================================================
# 4. EXECUÇÃO
# ==============================================================================

def main():
    print(f"--- Sistema IoT: Goiânia (Powered by AI V4 - Com Jitter) ---")
    
    try:
        client = MongoClient(MONGO_URI)
        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]
        client.admin.command('ping')
        print("✅ MongoDB Atlas: CONECTADO")
    except Exception as e:
        print(f"❌ Erro Crítico MongoDB: {e}")
        return

    ai_engine = DigitalTwinAI()

    try:
        while True:
            timestamp_now = datetime.datetime.now()
            print(f"\n[{timestamp_now.strftime('%H:%M:%S')}] Coletando dados ambientais...")
            
            clima = get_clima_real()
            print(f"☁️  Clima Real: {clima['temp_base']}°C | Umidade: {clima['hum_base']}%")

            novos_dados = []
            
            for nome_setor, dados_setor in SETORES.items():
                temp_local = clima['temp_base'] + dados_setor['temp_offset']
                
                pm25_ia, gases_ia = ai_engine.prever(
                    data_hora=timestamp_now,
                    temp_real=temp_local,
                    hum_real=clima['hum_base'],
                    fator_local=dados_setor['fator']
                )

                payload = {
                    "timestamp": timestamp_now,
                    "localizacao": nome_setor,
                    "temperatura": round(temp_local, 2),
                    "humidade": clima['hum_base'],
                    "gases_ppm": gases_ia,
                    "pm25": pm25_ia,
                    "latitude": dados_setor['coords']['lat'],
                    "longitude": dados_setor['coords']['lon'],
                    "origem_dado": "AI_RandomForest_V4"
                }
                
                novos_dados.append(payload)
                
                # Visualização de Debug (Escala US EPA)
                if pm25_ia < 12: estado = "🟢 BOM"
                elif pm25_ia < 35: estado = "🟡 MODERADO"
                elif pm25_ia < 55: estado = "🟠 RUIM (Sensíveis)"
                else: estado = "🔴 RUIM (Todos)"

                print(f"   > {nome_setor:<25} | PM2.5: {pm25_ia:>5.1f} | {estado}")

            if novos_dados:
                collection.insert_many(novos_dados)
                print("💾 Dados salvos.")

            print(f"⏳ Aguardando...")
            time.sleep(INTERVALO_LEITURA)

    except KeyboardInterrupt:
        print("\n🛑 Fim.")

if __name__ == "__main__":
    main()