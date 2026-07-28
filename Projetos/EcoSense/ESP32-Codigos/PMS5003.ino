/*
  PMS5003 - Focado apenas em PM 2.5
  
  CONEXÃO FÍSICA:
  * TX Sensor -> GPIO 16 (ESP32)
  * RX Sensor -> GPIO 17 (ESP32)
*/

#define RXD2 16 
#define TXD2 17 

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  // O sensor PMS5003 envia dados a 9600 baud rate
  Serial1.begin(9600, SERIAL_8N1, RXD2, TXD2);
  
  Serial.println("\n--- LEITURA EXCLUSIVA PM 2.5 ---");
}

struct pms5003data {
  uint16_t framelen;
  uint16_t pm10_standard, pm25_standard, pm100_standard;
  uint16_t pm10_env, pm25_env, pm100_env;
  uint16_t particles_03um, particles_05um, particles_10um, particles_25um, particles_50um, particles_100um;
  uint16_t unused;
  uint16_t checksum;
};

struct pms5003data data;

void loop() {
  if (readPMSdata(&Serial1)) {
    // AQUI ESTÁ A MUDANÇA:
    // Focamos apenas na variável pm25_standard
    
    Serial.print("Qualidade do Ar (PM 2.5): ");
    Serial.print(data.pm25_standard);
    Serial.println(" ug/m3");
    
    // Pequena pausa para facilitar a leitura no monitor
    // (O sensor envia dados quase todo segundo)
    // delay(1000); 
  }
}

boolean readPMSdata(Stream *s) {
  if (! s->available()) return false;
  
  // O sensor envia 32 bytes de uma vez. Precisamos ler todos
  // para garantir que o pacote é válido (checksum), mesmo que
  // a gente só queira usar o valor do PM2.5 depois.
  
  if (s->peek() != 0x42) {
    s->read();
    return false;
  }
  
  if (s->available() < 32) return false;
    
  uint8_t buffer[32];
  uint16_t sum = 0;
  s->readBytes(buffer, 32);
  
  for (uint8_t i = 0; i < 30; i++) sum += buffer[i];
  
  uint16_t buffer_u16[15];
  for (uint8_t i = 0; i < 15; i++) {
    buffer_u16[i] = buffer[2 + i * 2 + 1];
    buffer_u16[i] += (buffer[2 + i * 2] << 8);
  }
  
  memcpy((void *)&data, (void *)buffer_u16, 30);
  
  if (sum != data.checksum) {
    return false;
  }
  
  return true;
}