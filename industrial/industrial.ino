
#include <WiFi.h>
#include <WiFiClient.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <U8g2lib.h>

// =====================================================
// 1. USER CONFIGURATION
// =====================================================

const char* WIFI_SSID = "SENTROVA";
const char* WIFI_PASSWORD = "44444444";

// Replace with your laptop's IPv4 address from ipconfig.
// Example only: http://192.168.1.25:5000
const char* SERVER_BASE = "http://10.184.205.62:5000";

const char* DEVICE_ID = "ESP32-MPU6050-01";

// Classic ESP32 DevKit pins
constexpr uint8_t SDA_PIN = 21;
constexpr uint8_t SCL_PIN = 22;
constexpr uint8_t BUTTON_PIN = 18;

// Common SH1106 I2C address
// Change to 0x3D if your display uses that address.
constexpr uint8_t OLED_I2C_ADDRESS = 0x3C;

// Timing intervals
constexpr unsigned long SAMPLE_INTERVAL_MS = 500;
constexpr unsigned long WIFI_RETRY_MS = 5000;
constexpr unsigned long STATUS_CHECK_MS = 5000;
constexpr unsigned long BUTTON_DEBOUNCE_MS = 40;
constexpr unsigned long OLED_REFRESH_MS = 250;
constexpr unsigned long SOS_RETRY_MS = 2000;

// =====================================================
// 2. HARDWARE OBJECTS
// =====================================================

Adafruit_MPU6050 mpu;

// SH1106, 128x64, hardware I2C, full framebuffer
U8G2_SH1106_128X64_NONAME_F_HW_I2C oled(
  U8G2_R0,
  U8X8_PIN_NONE
);

// =====================================================
// 3. SYSTEM STATE
// =====================================================

bool sensorReady = false;
bool wifiWasConnected = false;
bool backendOnline = false;

bool sosActive = false;
bool sosSyncPending = false;

float ax = 0.0f;
float ay = 0.0f;
float az = 0.0f;

float gx = 0.0f;
float gy = 0.0f;
float gz = 0.0f;

float temperatureC = 0.0f;

unsigned long lastSampleMs = 0;
unsigned long lastWifiAttemptMs = 0;
unsigned long lastStatusCheckMs = 0;
unsigned long lastOledRefreshMs = 0;
unsigned long lastSosAttemptMs = 0;
unsigned long uploadedSamples = 0;

// Button uses INPUT_PULLUP: released = HIGH, pressed = LOW.
bool lastRawButton = HIGH;
bool stableButton = HIGH;
unsigned long lastButtonChangeMs = 0;

// =====================================================
// 4. URL HELPER
// =====================================================

String endpoint(const char* path) {
  return String(SERVER_BASE) + path;
}

// =====================================================
// 5. WI-FI CONNECTION AND RECONNECTION
// =====================================================

void serviceWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    if (!wifiWasConnected) {
      Serial.println("Wi-Fi connected.");
      Serial.print("ESP32 IP address: ");
      Serial.println(WiFi.localIP());

      wifiWasConnected = true;
    }
    return;
  }

  if (wifiWasConnected) {
    Serial.println("Wi-Fi disconnected.");
    wifiWasConnected = false;
    backendOnline = false;
  }

  unsigned long now = millis();

  if (now - lastWifiAttemptMs >= WIFI_RETRY_MS) {
    lastWifiAttemptMs = now;

    Serial.print("Connecting to Wi-Fi: ");
    Serial.println(WIFI_SSID);

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  }
}

// =====================================================
// 6. READ MPU6050
// =====================================================

bool readMPU6050() {
  if (!sensorReady) {
    return false;
  }

  sensors_event_t acceleration;
  sensors_event_t gyro;
  sensors_event_t temperature;

  mpu.getEvent(
    &acceleration,
    &gyro,
    &temperature
  );

  // Adafruit library:
  // Acceleration = m/s^2
  // Gyroscope = rad/s
  // Convert gyroscope values to degrees/second.
  constexpr float RAD_TO_DEG_VALUE = 57.2957795f;

  ax = acceleration.acceleration.x;
  ay = acceleration.acceleration.y;
  az = acceleration.acceleration.z;

  gx = gyro.gyro.x * RAD_TO_DEG_VALUE;
  gy = gyro.gyro.y * RAD_TO_DEG_VALUE;
  gz = gyro.gyro.z * RAD_TO_DEG_VALUE;

  temperatureC = temperature.temperature;

  return true;
}

// =====================================================
// 7. HTTP POST HELPER
// =====================================================

bool postJson(const char* path, const String& payload) {
  if (WiFi.status() != WL_CONNECTED) {
    return false;
  }

  WiFiClient client;
  HTTPClient http;

  http.setConnectTimeout(1500);
  http.setTimeout(2000);

  String url = endpoint(path);

  if (!http.begin(client, url)) {
    Serial.println("ERROR: Could not initialize HTTP.");
    return false;
  }

  http.addHeader("Content-Type", "application/json");

  int httpCode = http.POST(payload);
  bool success = (httpCode >= 200 && httpCode < 300);

  if (success) {
    Serial.printf(
      "POST %s successful (HTTP %d)\n",
      path,
      httpCode
    );
  } else if (httpCode < 0) {
    Serial.printf(
      "POST %s failed: %s\n",
      path,
      HTTPClient::errorToString(httpCode).c_str()
    );
  } else {
    Serial.printf(
      "POST %s returned HTTP %d\n",
      path,
      httpCode
    );
  }

  http.end();
  return success;
}

// =====================================================
// 8. UPLOAD SENSOR DATA TO FLASK
// =====================================================

void uploadSensorData() {
  if (!sensorReady || WiFi.status() != WL_CONNECTED) {
    return;
  }

  String payload;
  payload.reserve(240);

  payload = "{";
  payload += "\"device_id\":\"";
  payload += DEVICE_ID;
  payload += "\",\"ax\":";
  payload += String(ax, 4);
  payload += ",\"ay\":";
  payload += String(ay, 4);
  payload += ",\"az\":";
  payload += String(az, 4);
  payload += ",\"gx\":";
  payload += String(gx, 4);
  payload += ",\"gy\":";
  payload += String(gy, 4);
  payload += ",\"gz\":";
  payload += String(gz, 4);
  payload += "}";

  if (postJson("/sensor", payload)) {
    uploadedSamples++;

    Serial.printf(
      "Sensor sample #%lu uploaded.\n",
      uploadedSamples
    );
  }
}

// =====================================================
// 9. CHECK FLASK BACKEND HEALTH
// =====================================================

void checkBackend() {
  if (WiFi.status() != WL_CONNECTED) {
    backendOnline = false;
    return;
  }

  WiFiClient client;
  HTTPClient http;

  http.setConnectTimeout(1500);
  http.setTimeout(2000);

  if (!http.begin(client, endpoint("/api/health"))) {
    backendOnline = false;
    return;
  }

  int httpCode = http.GET();
  backendOnline = (httpCode >= 200 && httpCode < 300);

  if (!backendOnline) {
    Serial.printf(
      "Backend health check failed: HTTP %d\n",
      httpCode
    );
  }

  http.end();
}

// =====================================================
// 10. SYNCHRONIZE SOS STATE WITH BACKEND
// =====================================================

void syncSOS() {
  if (!sosSyncPending || WiFi.status() != WL_CONNECTED) {
    return;
  }

  unsigned long now = millis();

  // Limit retries when the backend is unreachable.
  if (now - lastSosAttemptMs < SOS_RETRY_MS) {
    return;
  }

  lastSosAttemptMs = now;

  String payload = String("{\"active\":") +
                   (sosActive ? "true" : "false") +
                   "}";

  if (postJson("/api/sos", payload)) {
    sosSyncPending = false;

    Serial.println(
      sosActive
        ? "SOS activation synchronized."
        : "SOS clear synchronized."
    );
  }
}

// =====================================================
// 11. DEBOUNCED PUSH BUTTON
// Press once: SOS ON
// Press again: SOS OFF
// =====================================================

void serviceButton() {
  bool rawButton = digitalRead(BUTTON_PIN);
  unsigned long now = millis();

  if (rawButton != lastRawButton) {
    lastRawButton = rawButton;
    lastButtonChangeMs = now;
  }

  if (
    rawButton != stableButton &&
    now - lastButtonChangeMs >= BUTTON_DEBOUNCE_MS
  ) {
    stableButton = rawButton;

    // Only trigger on the press transition.
    if (stableButton == LOW) {
      sosActive = !sosActive;
      sosSyncPending = true;

      Serial.println(
        sosActive
          ? "!!! SOS ACTIVATED !!!"
          : "SOS CLEARED."
      );

      // Attempt immediate synchronization.
      // Failed requests are retried later.
      syncSOS();
    }
  }
}

// =====================================================
// 12. OLED DISPLAY
// =====================================================

void drawOLED() {
  oled.clearBuffer();

  oled.setFont(u8g2_font_6x10_tf);
  oled.drawStr(0, 10, "WORKER MONITOR");
  oled.drawHLine(0, 13, 128);

  // Wi-Fi status
  oled.setCursor(0, 25);
  oled.print("WiFi: ");
  oled.print(
    WiFi.status() == WL_CONNECTED
      ? "CONNECTED"
      : "OFFLINE"
  );

  // Backend status
  oled.setCursor(0, 36);
  oled.print("API:  ");
  oled.print(backendOnline ? "ONLINE" : "OFFLINE");

  // Sensor acceleration
  oled.setCursor(0, 47);

  if (sensorReady) {
    oled.print("A ");
    oled.print(ax, 1);
    oled.print(" ");
    oled.print(ay, 1);
    oled.print(" ");
    oled.print(az, 1);
  } else {
    oled.print("MPU6050 NOT FOUND");
  }

  // Sensor gyroscope
  oled.setCursor(0, 58);

  if (sensorReady) {
    oled.print("G ");
    oled.print(gx, 0);
    oled.print(" ");
    oled.print(gy, 0);
    oled.print(" ");
    oled.print(gz, 0);
  }

  // SOS banner takes priority over sensor values.
  if (sosActive) {
    oled.drawBox(0, 48, 128, 16);

    oled.setDrawColor(0);
    oled.setFont(u8g2_font_6x10_tf);
    oled.drawStr(4, 59, "!!! SOS ACTIVE !!!");
    oled.setDrawColor(1);
  }

  oled.sendBuffer();
}

// =====================================================
// 13. SETUP
// =====================================================

void setup() {
  Serial.begin(115200);
  delay(500);

  pinMode(BUTTON_PIN, INPUT_PULLUP);

  // Shared I2C bus for MPU6050 and OLED.
  Wire.begin(SDA_PIN, SCL_PIN);

  // Initialize SH1106 OLED.
  oled.setI2CAddress(OLED_I2C_ADDRESS * 2);
  oled.begin();

  oled.clearBuffer();
  oled.setFont(u8g2_font_6x10_tf);
  oled.drawStr(0, 18, "WORKER MONITOR");
  oled.drawStr(0, 34, "Starting...");
  oled.sendBuffer();

  Serial.println();
  Serial.println("Industrial Worker Monitoring System");
  Serial.println("------------------------------------");

  // Initialize MPU6050.
  Serial.println("Initializing MPU6050...");

  if (mpu.begin(0x68, &Wire)) {
    sensorReady = true;

    mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
    mpu.setGyroRange(MPU6050_RANGE_500_DEG);
    mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);

    Serial.println("MPU6050 initialized successfully.");
  } else {
    sensorReady = false;

    Serial.println("ERROR: MPU6050 not found at 0x68.");
    Serial.println("Check VCC, GND, SDA and SCL.");
  }

  // Start Wi-Fi and allow an immediate first attempt.
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);

  lastWifiAttemptMs = millis() - WIFI_RETRY_MS;
  serviceWiFi();

  Serial.println("Setup complete.");
}

// =====================================================
// 14. MAIN LOOP
// =====================================================

void loop() {
  unsigned long now = millis();

  // Keep Wi-Fi and button responsive.
  serviceWiFi();
  serviceButton();

  // Read and upload sensor measurements.
  if (now - lastSampleMs >= SAMPLE_INTERVAL_MS) {
    lastSampleMs = now;

    if (readMPU6050()) {
      Serial.printf(
        "A [m/s2]: %.2f, %.2f, %.2f | "
        "G [deg/s]: %.2f, %.2f, %.2f | "
        "Temp: %.1f C\n",
        ax, ay, az,
        gx, gy, gz,
        temperatureC
      );

      uploadSensorData();
    }
  }

  // Periodic backend health check.
  if (now - lastStatusCheckMs >= STATUS_CHECK_MS) {
    lastStatusCheckMs = now;
    checkBackend();
  }

  // Retry pending SOS changes.
  syncSOS();

  // Refresh display.
  if (now - lastOledRefreshMs >= OLED_REFRESH_MS) {
    lastOledRefreshMs = now;
    drawOLED();
  }

  delay(2);
}
