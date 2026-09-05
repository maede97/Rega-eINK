// base class GxEPD2_GFX can be used to pass references or pointers to the display instance as parameter, uses ~1.2k more code
// enable or disable GxEPD2_GFX base class
#define ENABLE_GxEPD2_GFX 0

#include <GxEPD2_BW.h>
#include <Fonts/FreeMonoBold9pt7b.h>

#include "HTTPClient.h"
#include "WiFiClientSecure.h"
#include "WiFi.h"
#include <ArduinoJson.h>

#include "../wifi_credentials.h"
#include "switzerland_outline.h"

// ESP32-C3 CS(SS)=7,SCL(SCK)=4,SDA(MOSI)=6,BUSY=3,RES(RST)=2,DC=1
#define CS_PIN (SS)
#define BUSY_PIN (3)
#define RES_PIN (2)
#define DC_PIN (1)

#define LAT_MIN 45.817995f
#define LAT_MAX 47.808455f
#define LON_MIN 5.956080f
#define LON_MAX 10.492030f

#define DISPLAY_ROTATION 0
#define NUM_FLIGHTS 25
#define MAX_POINTS 32

// 4.2'' EPD Module
GxEPD2_BW<GxEPD2_420_GDEY042T81, GxEPD2_420_GDEY042T81::HEIGHT> display(GxEPD2_420_GDEY042T81(/*CS=5*/ CS_PIN, /*DC=*/DC_PIN, /*RES=*/RES_PIN, /*BUSY=*/BUSY_PIN)); // 400x300, SSD1683

const uint16_t MAP_X = 0;
const uint16_t MAP_Y = 0;
const uint8_t MAP_INSET = 2;

unsigned long nextRefreshMs = 0;
const unsigned long REFRESH_INTERVAL_MS = 60000UL;

unsigned long lastDataTimestamp = 0;

struct FlightPoint
{
  float latitude;
  float longitude;
};

struct FlightTrail
{
  String callsign;
  bool active;
  uint8_t pointCount;
  FlightPoint points[MAX_POINTS];
};

FlightTrail flightTrails[NUM_FLIGHTS];

struct MapProjection
{
  float minX;
  float maxX;
  float minY;
  float maxY;
  float scale;
  float offsetX;
  float offsetY;
  bool ready;
};

MapProjection switzerlandProjection = {0.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f, false};

uint16_t canvasWidth()
{
  return display.width();
}

uint16_t canvasHeight()
{
  return display.height();
}

int16_t mapLongitudeToX(float lon)
{
  if (!switzerlandProjection.ready)
  {
    return MAP_X + MAP_INSET;
  }

  float x = (lon - LON_MIN) * 111320.0f * cosf(radians((LAT_MIN + LAT_MAX) * 0.5f));
  return (int16_t)(switzerlandProjection.offsetX + ((x - switzerlandProjection.minX) * switzerlandProjection.scale));
}

int16_t mapLatitudeToY(float lat)
{
  if (!switzerlandProjection.ready)
  {
    return MAP_Y + MAP_INSET;
  }

  float y = (lat - LAT_MIN) * 110540.0f;
  return (int16_t)(switzerlandProjection.offsetY + ((switzerlandProjection.maxY - y) * switzerlandProjection.scale));
}

bool rectanglesOverlap(int16_t leftA, int16_t topA, int16_t widthA, int16_t heightA,
                       int16_t leftB, int16_t topB, int16_t widthB, int16_t heightB)
{
  return !(leftA + widthA < leftB || leftB + widthB < leftA ||
           topA + heightA < topB || topB + heightB < topA);
}

void drawSwitzerlandMapFrameInRect(int16_t left, int16_t top, int16_t width, int16_t height)
{
  for (uint8_t w = 0; w < SWITZERLAND_WAY_COUNT; ++w)
  {
    const SwitzerlandWay &way = SWITZERLAND_WAYS[w];
    if (way.count < 2)
    {
      continue;
    }

    for (uint8_t i = 0; i + 1 < way.count; ++i)
    {
      int16_t x1 = mapLongitudeToX(way.lon[i]);
      int16_t y1 = mapLatitudeToY(way.lat[i]);
      int16_t x2 = mapLongitudeToX(way.lon[i + 1]);
      int16_t y2 = mapLatitudeToY(way.lat[i + 1]);

      int16_t segmentLeft = (x1 < x2) ? x1 : x2;
      int16_t segmentTop = (y1 < y2) ? y1 : y2;
      int16_t segmentWidth = (x1 > x2 ? x1 : x2) - segmentLeft;
      int16_t segmentHeight = (y1 > y2 ? y1 : y2) - segmentTop;

      if (rectanglesOverlap(left, top, width, height, segmentLeft, segmentTop, segmentWidth + 1, segmentHeight + 1))
      {
        display.drawLine(x1, y1, x2, y2, GxEPD_BLACK);
      }
    }
  }
}

void updateSwitzerlandProjection()
{
  float minX = 0.0f;
  float maxX = 0.0f;
  float minY = 0.0f;
  float maxY = 0.0f;
  bool firstPoint = true;
  const float centerLatRad = radians((LAT_MIN + LAT_MAX) * 0.5f);
  const float metersPerLon = 111320.0f * cosf(centerLatRad);
  const float metersPerLat = 110540.0f;

  for (uint8_t w = 0; w < SWITZERLAND_WAY_COUNT; ++w)
  {
    const SwitzerlandWay &way = SWITZERLAND_WAYS[w];
    for (uint8_t i = 0; i < way.count; ++i)
    {
      float x = (way.lon[i] - LON_MIN) * metersPerLon;
      float y = (way.lat[i] - LAT_MIN) * metersPerLat;
      if (firstPoint)
      {
        minX = maxX = x;
        minY = maxY = y;
        firstPoint = false;
      }
      else
      {
        if (x < minX)
          minX = x;
        if (x > maxX)
          maxX = x;
        if (y < minY)
          minY = y;
        if (y > maxY)
          maxY = y;
      }
    }
  }

  float width = maxX - minX;
  float height = maxY - minY;
  float availableWidth = (float)canvasWidth() - (float)(MAP_INSET * 2);
  float availableHeight = (float)canvasHeight() - (float)(MAP_INSET * 2);
  float scaleX = availableWidth / width;
  float scaleY = availableHeight / height;

  switzerlandProjection.minX = minX;
  switzerlandProjection.maxX = maxX;
  switzerlandProjection.minY = minY;
  switzerlandProjection.maxY = maxY;
  switzerlandProjection.scale = (scaleX < scaleY) ? scaleX : scaleY;
  switzerlandProjection.offsetX = MAP_INSET + (availableWidth - (width * switzerlandProjection.scale)) * 0.5f;
  switzerlandProjection.offsetY = MAP_INSET + (availableHeight - (height * switzerlandProjection.scale)) * 0.5f;
  switzerlandProjection.ready = true;
}

void drawSwitzerlandMapFrame()
{
  for (uint8_t w = 0; w < SWITZERLAND_WAY_COUNT; ++w)
  {
    const SwitzerlandWay &way = SWITZERLAND_WAYS[w];
    if (way.count < 2)
    {
      continue;
    }

    for (uint8_t i = 0; i + 1 < way.count; ++i)
    {
      int16_t x1 = mapLongitudeToX(way.lon[i]);
      int16_t y1 = mapLatitudeToY(way.lat[i]);
      int16_t x2 = mapLongitudeToX(way.lon[i + 1]);
      int16_t y2 = mapLatitudeToY(way.lat[i + 1]);
      display.drawLine(x1, y1, x2, y2, GxEPD_BLACK);
    }
  }
}

void prepareDisplay()
{
  display.setRotation(DISPLAY_ROTATION);
  display.setFullWindow();
  display.firstPage();
}

void finishDisplay()
{
  display.hibernate();
}

void drawText(const char *text)
{
  display.setFont(&FreeMonoBold9pt7b);
  display.setTextColor(GxEPD_BLACK);

  char buffer[128];
  strncpy(buffer, text, sizeof(buffer) - 1);
  buffer[sizeof(buffer) - 1] = '\0';

  char *lines[16];
  size_t lineCount = 0;
  lines[lineCount++] = buffer;

  for (char *p = buffer; *p != '\0' && lineCount < 16; ++p)
  {
    if (*p == '\n' || *p == '\r')
    {
      *p = '\0';
      char *next = p + 1;
      while (*next == '\n' || *next == '\r')
      {
        ++next;
      }
      if (*next != '\0' && lineCount < 16)
      {
        lines[lineCount++] = next;
      }
      if (*next == '\0')
      {
        break;
      }
      p = next - 1;
    }
  }

  int16_t lineHeights[16];
  int16_t totalHeight = 0;
  const int16_t lineGap = 4;

  for (size_t i = 0; i < lineCount; ++i)
  {
    int16_t tbx, tby;
    uint16_t tbw, tbh;
    display.getTextBounds(lines[i], 0, 0, &tbx, &tby, &tbw, &tbh);

    lineHeights[i] = (int16_t)tbh;
    totalHeight += (int16_t)tbh;
  }

  if (lineCount > 1)
  {
    totalHeight += (int16_t)(lineCount - 1) * lineGap;
  }

  int16_t cursorY = ((int16_t)canvasHeight() - totalHeight) / 2;

  for (size_t i = 0; i < lineCount; ++i)
  {
    int16_t tbx, tby;
    uint16_t tbw, tbh;
    display.getTextBounds(lines[i], 0, 0, &tbx, &tby, &tbw, &tbh);

    int16_t x = ((int16_t)canvasWidth() - (int16_t)tbw) / 2 - tbx;
    int16_t y = cursorY - tby;

    display.setCursor(x, y);
    display.print(lines[i]);

    cursorY += lineHeights[i] + lineGap;
  }
}

void drawCallSign(const FlightPoint &point, const char *callSign)
{
  display.setFont(&FreeMonoBold9pt7b);
  display.setTextColor(GxEPD_BLACK);
  int16_t tbx, tby;
  uint16_t tbw, tbh;
  display.getTextBounds(callSign, 0, 0, &tbx, &tby, &tbw, &tbh);

  int16_t x = mapLongitudeToX(point.longitude);
  int16_t y = mapLatitudeToY(point.latitude);

  const int16_t gap = 8;
  const int16_t preferredX = x + gap - tbx;
  int16_t cursorX = preferredX;
  int16_t cursorY = y - tbh / 2 - tby - 4;

  if (cursorX + (int16_t)tbw > (int16_t)canvasWidth() - 2)
  {
    cursorX = (int16_t)canvasWidth() - (int16_t)tbw - 2;
  }

  if (cursorY < 0)
  {
    cursorY = 0;
  }
  else if (cursorY + (int16_t)tbh > (int16_t)canvasHeight() - 2)
  {
    cursorY = (int16_t)canvasHeight() - (int16_t)tbh - 2;
  }

  display.setCursor(cursorX, cursorY);
  display.print(callSign);
}

void drawFlightTrail(const FlightTrail &trail)
{
  for (size_t i = 0; i + 1 < trail.pointCount; ++i)
  {
    int16_t x1 = mapLongitudeToX(trail.points[i].longitude);
    int16_t y1 = mapLatitudeToY(trail.points[i].latitude);
    int16_t x2 = mapLongitudeToX(trail.points[i + 1].longitude);
    int16_t y2 = mapLatitudeToY(trail.points[i + 1].latitude);
    display.drawLine(x1, y1, x2, y2, GxEPD_BLACK);
  }

  if (trail.pointCount > 0)
  {
    // draw a small circle at the last point of the trail (first in array)
    int16_t x = mapLongitudeToX(trail.points[0].longitude);
    int16_t y = mapLatitudeToY(trail.points[0].latitude);
    display.drawCircle(x, y, 2, GxEPD_BLACK);

    if (trail.active)
    {
      drawCallSign(trail.points[0], trail.callsign.c_str());
    }
  }
}

void drawFlightTrails()
{
  size_t activeFlights = 0;
  for (size_t i = 0; i < NUM_FLIGHTS; ++i)
  {
    if (flightTrails[i].pointCount > 0)
    {
      drawFlightTrail(flightTrails[i]);
      ++activeFlights;
    }
  }

  if (activeFlights == 0)
  {
    drawText("No active flights");
  }
}

void convertTimestampToString(unsigned long timestamp, char *buffer, size_t bufferSize)
{
  // timestamp is a unix timestamp, i need a swiss (GMT+2) HH:MM:SS string
  time_t rawTime = (time_t)timestamp;
  struct tm *timeInfo = gmtime(&rawTime);
  timeInfo->tm_hour += 2; // GMT+2
  mktime(timeInfo);       // normalize the time structure
  snprintf(buffer, bufferSize, "%02d:%02d:%02d", timeInfo->tm_hour, timeInfo->tm_min, timeInfo->tm_sec);
}

void drawLastDataTimestamp()
{
  display.setFont(&FreeMonoBold9pt7b);
  display.setTextColor(GxEPD_BLACK);
  int16_t tbx, tby;
  uint16_t tbw, tbh;
  char buffer[32];
  convertTimestampToString(lastDataTimestamp, buffer, sizeof(buffer));
  display.getTextBounds(buffer, 0, 0, &tbx, &tby, &tbw, &tbh);

  int16_t cursorX = (int16_t)canvasWidth() - (int16_t)tbw - 2;
  int16_t cursorY = (int16_t)tbh + 2;

  display.setCursor(cursorX, cursorY);
  display.print(buffer);
}

bool ensureWiFi()
{
  if (WiFi.status() == WL_CONNECTED)
  {
    return true;
  }

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  for (uint16_t attempts = 0; attempts < 60; ++attempts)
  {
    if (WiFi.status() == WL_CONNECTED)
    {
      return true;
    }
    delay(500);
  }

  return false;
}

bool fetchFlights()
{
  // curl -H "Authorization: Bearer 53991a01-1ae0-448a-b5b4-7bc8f7c395b8" https://rega.hueppis.com/flights
  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient https;
  if (!https.begin(client, "https://rega.hueppis.com/flights"))
  {
    return false;
  }

  https.addHeader("Authorization", "Bearer " BEARER);
  int httpCode = https.GET();
  if (httpCode != HTTP_CODE_OK)
  {
    https.end();
    return false;
  }
  String payload = https.getString();
  https.end();
  DynamicJsonDocument doc(2048);

  DeserializationError error = deserializeJson(doc, payload);
  if (error)
  {
    return false;
  }

  size_t count = doc["count"];

  JsonArray flights = doc["flights"];

  // clear flight trails
  for (size_t i = 0; i < NUM_FLIGHTS; ++i)
  {
    flightTrails[i].pointCount = 0;
  }

  if (count == 0)
  {
    return true;
  }

  for (JsonObject flight : flights)
  {
    const char *callsign = flight["callsign"];
    float latitude = flight["latitude"];
    float longitude = flight["longitude"];
    bool active = flight["active"];
    unsigned long timestamp = flight["timestamp"];

    // update last timestamp
    if (timestamp > lastDataTimestamp)
    {
      lastDataTimestamp = timestamp;
    }

    // find existing flight trail
    FlightTrail *trail = nullptr;
    for (size_t i = 0; i < NUM_FLIGHTS; ++i)
    {
      if (flightTrails[i].pointCount > 0 && strcmp(flightTrails[i].callsign.c_str(), callsign) == 0)
      {
        trail = &flightTrails[i];
        break;
      }
    }

    // if not found, find empty slot
    if (!trail)
    {
      for (size_t i = 0; i < NUM_FLIGHTS; ++i)
      {
        if (flightTrails[i].pointCount == 0)
        {
          trail = &flightTrails[i];
          trail->callsign = callsign;
          trail->active = false; // mark as inactive initially
          break;
        }
      }
    }

    // add point to trail
    if (trail && trail->pointCount < MAX_POINTS)
    {
      trail->points[trail->pointCount].latitude = latitude;
      trail->points[trail->pointCount].longitude = longitude;
      ++trail->pointCount;
      if (active)
      {
        // mark trail as active as soon as one active point is found.
        trail->active = true;
      }
    }
  }
  return true;
}

void setup()
{
  pinMode(8, OUTPUT);
  digitalWrite(8, HIGH);

  Serial.begin(19200);

  display.init(115200, true, 50, false);
  display.setRotation(DISPLAY_ROTATION);
  updateSwitzerlandProjection();

  drawSwitzerlandMapFrame();
  display.setFullWindow();
  display.firstPage();
  do
  {
    drawSwitzerlandMapFrame();
    drawText("REGA Tracker\nBy maede97");
  } while (display.nextPage());
  display.hibernate();

  nextRefreshMs = millis() + 3000UL; // first start faster
}

void loop()
{
  if (millis() >= nextRefreshMs)
  {
    nextRefreshMs = millis() + REFRESH_INTERVAL_MS;

    if (!ensureWiFi())
    {
      prepareDisplay();
      do
      {
        drawSwitzerlandMapFrame();
        drawText("WiFi not connected");
      } while (display.nextPage());
      finishDisplay();

      return;
    }
    else
    {
      prepareDisplay();

      // fetch flight data
      if (!fetchFlights())
      {
        // failed to fetch flight data
        display.setPartialWindow(0, 0, display.width(), display.height());
        display.firstPage();
        do
        {
          drawSwitzerlandMapFrame();
          drawText("Failed to fetch flight data");
        } while (display.nextPage());
        finishDisplay();
        return;
      }
      display.setPartialWindow(0, 0, display.width(), display.height());
      display.firstPage();
      do
      {
        drawSwitzerlandMapFrame();
        drawFlightTrails();
        drawLastDataTimestamp();
      } while (display.nextPage());
      finishDisplay();
    }
  }
}
