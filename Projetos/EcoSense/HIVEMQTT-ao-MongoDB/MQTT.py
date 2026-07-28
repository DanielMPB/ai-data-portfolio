import json
import paho.mqtt.client as mqtt
from pymongo import MongoClient
from datetime import datetime
import ssl
import time

#============================
#CONFIGURAÇÕES DO MONGODB ATLAS
#============================
MONGO_URI = "mongodb+srv://seu_user:<1234>@dadosiot.qn7fslz.mongodb.net/?appName=DadosIoT"
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["seu Data Base"]
collection = db["sua collection"]  # nome da coleção para dados crus

#============================
#CONFIGURAÇÕES DO MQTT (HIVEMQ CLOUD)
#============================
MQTT_BROKER = "broker.eu.hivemq.cloud"   # exemplo: xxxxx.s1.eu.hivemq.cloud
MQTT_PORT = 0000 #sua porta                  # TLS
MQTT_USER = "seu_user"
MQTT_PASS = "senha"

MQTT_TOPIC = "sensores/ar"         # troque pelo tópico que seu ESP32 usa


#============================
#CALLBACK: quando conecta
#============================
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[OK] Conectado ao HiveMQ!")
        client.subscribe(MQTT_TOPIC)
        print(f"[OK] Inscrito no tópico: {MQTT_TOPIC}")
    else:
        print(f"[ERRO] Falha ao conectar. Código: {rc}")


#============================
#CALLBACK: quando recebe mensagem
#============================
def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode()
        data = json.loads(payload)

        # Adiciona timestamp do recebimento
        data["received_at"] = datetime.utcnow()

        # Salva no MongoDB Atlas
        collection.insert_one(data)

        print(f"[MongoDB] Inserido: {data}")

    except json.JSONDecodeError:
        print("[ERRO] Mensagem recebida NÃO é JSON válido:")
        print(msg.payload.decode())

    except Exception as e:
        print("[ERRO] Falha ao salvar no Mongo ou processar mensagem:", e)


#============================
#CRIA O CLIENTE MQTT
#============================
client = mqtt.Client()

client.username_pw_set(MQTT_USER, MQTT_PASS)
client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS)

client.on_connect = on_connect
client.on_message = on_message


#============================
#LOOP DE CONEXÃO COM RECONEXÃO
#============================
while True:
    try:
        print("[INFO] Conectando ao HiveMQ...")
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_forever()

    except Exception as e:
        print("[ERRO] Conexão perdida. Tentando reconectar em 5 segundos...")
        print("Detalhes:", e)
        time.sleep(5)