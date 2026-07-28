#include "MQ135.h"

#define PIN_MQ135 34   // ESP32: GPIO34 (somente entrada analógica)
// Para Arduino UNO use: A0
// Para ESP8266 use: A0

MQ135 mq135_sensor(PIN_MQ135);

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println("Iniciando leitura do MQ-135...");
}

void loop() {
  float raw_adc = analogRead(PIN_MQ135);  
  float rzero = mq135_sensor.getRZero();  
  float ppm = mq135_sensor.getPPM();      

  Serial.println("-------------------------------");
  Serial.print("ADC bruto: ");
  Serial.println(raw_adc);

  Serial.print("RZero: ");
  Serial.println(rzero);

  Serial.print("PPM estimado: ");
  Serial.println(ppm);

  delay(1500);
}