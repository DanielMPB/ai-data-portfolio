#include "DHT.h"

#define DHTPIN 26     // pino conectado ao DATA do DHT11
#define DHTTYPE DHT11 // tipo do sensor

DHT dht(DHTPIN, DHTTYPE);

void setup() {
  Serial.begin(115200);
  Serial.println("TESTE DHT11 ESP32");

  dht.begin();
  delay(60000); // tempo necessário para o sensor estabilizar
}

void loop() {
  float h = dht.readHumidity();      // leitura da umidade
  float t = dht.readTemperature();   // leitura da temperatura em °C

  if (isnan(h) || isnan(t)) {
    Serial.println("Falha ao ler o sensor DHT11!");
  } else {
    Serial.print("Temperatura: ");
    Serial.print(t);
    Serial.print(" °C, Umidade: ");
    Serial.print(h);
    Serial.println(" %");
  }

  delay(2000); // intervalo de leitura
}
