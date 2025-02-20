#include "Arduino.h"
#include "Arduino_GFX_Library.h"

#define GFX_DEV_DEVICE LILYGO_T_DISPLAY_S3
#define GFX_EXTRA_PRE_INIT()              \
    {                                     \
        pinMode(15 /* PWD */, OUTPUT);    \
        digitalWrite(15 /* PWD */, HIGH); \
    }
#define GFX_BL 38

Arduino_DataBus *bus = new Arduino_ESP32PAR8Q(
    7 /* DC */, 6 /* CS */, 8 /* WR */, 9 /* RD */,
    39 /* D0 */, 40 /* D1 */, 41 /* D2 */, 42 /* D3 */, 45 /* D4 */, 46 /* D5 */, 47 /* D6 */, 48 /* D7 */);
Arduino_GFX *gfx = new Arduino_ST7789(bus, 5 /* RST */, 0 /* rotation */, true /* IPS */, 170 /* width */, 320 /* height */, 35 /* col offset 1 */, 0 /* row offset 1 */, 35 /* col offset 2 */, 0 /* row offset 2 */);

#define DOOR_PIN 18

// Global variables
unsigned long startMillis;
String lastTimeStr = "";
int16_t lastXPos = 0;
int16_t lastYPos = 0;
bool firstRun = true;
uint16_t lightBlue;
bool doorOpen = false;  // Track door state
bool lastDoorState = false;  // For detecting changes

void drawDogBowl() {
    int centerX = gfx->width() / 2;
    int startY = lastYPos + 80; // Position below the timer, slightly closer
    
    // Bowl base - trapezoid shape
    int bowlWidth = 100;
    int bowlHeight = 40;
    int topWidth = bowlWidth - 20;
    
    // Draw the bowl outline
    gfx->drawLine(centerX - bowlWidth/2, startY + bowlHeight, centerX + bowlWidth/2, startY + bowlHeight, lightBlue); // bottom
    gfx->drawLine(centerX - bowlWidth/2, startY + bowlHeight, centerX - topWidth/2, startY, lightBlue); // left side
    gfx->drawLine(centerX + bowlWidth/2, startY + bowlHeight, centerX + topWidth/2, startY, lightBlue); // right side
    gfx->drawLine(centerX - topWidth/2, startY, centerX + topWidth/2, startY, lightBlue); // top

    // Draw the food mound
    int moundHeight = 15;
    for(int i = 0; i < moundHeight; i++) {
        int width = topWidth - (i * 2);
        gfx->drawLine(centerX - width/2, startY - i, centerX + width/2, startY - i, lightBlue);
    }

    // Draw the bone
    int boneWidth = 30;
    int boneHeight = 12;
    int boneY = startY + (bowlHeight/2);
    
    // Main bone line
    gfx->drawLine(centerX - boneWidth/2, boneY, centerX + boneWidth/2, boneY, lightBlue);
    
    // Left end
    gfx->drawLine(centerX - boneWidth/2, boneY - boneHeight/2, centerX - boneWidth/2, boneY + boneHeight/2, lightBlue);
    gfx->drawLine(centerX - boneWidth/2 - 3, boneY - boneHeight/2, centerX - boneWidth/2 - 3, boneY + boneHeight/2, lightBlue);
    gfx->drawLine(centerX - boneWidth/2 - 3, boneY - boneHeight/2, centerX - boneWidth/2, boneY - boneHeight/2, lightBlue);
    gfx->drawLine(centerX - boneWidth/2 - 3, boneY + boneHeight/2, centerX - boneWidth/2, boneY + boneHeight/2, lightBlue);
    
    // Right end
    gfx->drawLine(centerX + boneWidth/2, boneY - boneHeight/2, centerX + boneWidth/2, boneY + boneHeight/2, lightBlue);
    gfx->drawLine(centerX + boneWidth/2 + 3, boneY - boneHeight/2, centerX + boneWidth/2 + 3, boneY + boneHeight/2, lightBlue);
    gfx->drawLine(centerX + boneWidth/2, boneY - boneHeight/2, centerX + boneWidth/2 + 3, boneY - boneHeight/2, lightBlue);
    gfx->drawLine(centerX + boneWidth/2, boneY + boneHeight/2, centerX + boneWidth/2 + 3, boneY + boneHeight/2, lightBlue);
}

void displayTime(unsigned long elapsedSeconds) {
    unsigned long hours = elapsedSeconds / 3600;
    unsigned long minutes = (elapsedSeconds % 3600) / 60;
    unsigned long seconds = elapsedSeconds % 60;
    
    char timeStr[9];
    sprintf(timeStr, "%02lu:%02lu:%02lu", hours, minutes, seconds);
    
    // Initialize screen and title on first run
    if (firstRun) {
        gfx->fillScreen(BLACK);
        
        // Draw the title
        gfx->setTextSize(2);
        gfx->setTextColor(lightBlue);
        const char* title = "Time since opened:";
        
        // Center the title
        int16_t x1, y1;
        uint16_t titleW, titleH;
        gfx->getTextBounds(title, 0, 0, &x1, &y1, &titleW, &titleH);
        int titleX = (gfx->width() - titleW) / 2;
        gfx->setCursor(titleX, 20);
        gfx->print(title);
        
        firstRun = false;
    }
    
    // Only recalculate time position and clear screen on first time display
    if (lastTimeStr.length() == 0) {
        gfx->setTextSize(6);
        
        // Calculate text position to center it, moved down to accommodate title
        int16_t x1, y1;
        uint16_t w, h;
        gfx->getTextBounds(timeStr, 0, 0, &x1, &y1, &w, &h);
        lastXPos = (gfx->width() - w) / 2;
        lastYPos = (gfx->height() - h) / 3; // Moved up higher on screen
        
        // Draw the dog bowl after we know the time position
        drawDogBowl();
    }
    
    // Only update if time string has changed
    if (lastTimeStr != timeStr) {
        // Clear previous text area with extra space on the right
        gfx->fillRect(lastXPos - 5, lastYPos - 5, 300, 70, BLACK);
        
        // Draw new time
        gfx->setTextSize(6);
        gfx->setTextColor(lightBlue);
        gfx->setCursor(lastXPos, lastYPos);
        gfx->print(timeStr);
        
        lastTimeStr = timeStr;
    }
}

void setup() {
    GFX_EXTRA_PRE_INIT();

    #ifdef GFX_BL
        pinMode(GFX_BL, OUTPUT);
        digitalWrite(GFX_BL, HIGH);
    #endif

    // Setup door pin with internal pullup
    pinMode(DOOR_PIN, INPUT_PULLUP);

    Serial.begin(115200);
    Serial.println("Hello T-Display-S3 Timer");

    gfx->begin();
    gfx->setRotation(3); // Landscape mode rotated 180 degrees
    gfx->fillScreen(BLACK);
    
    // Initialize the light blue color
    lightBlue = gfx->color565(80, 180, 255);
    
    startMillis = millis(); // Record start time
}

void displayDoorOpen() {
    gfx->fillScreen(RED);
    gfx->setTextSize(8);
    gfx->setTextColor(WHITE);
    
    const char* text = "OPEN";
    int16_t x1, y1;
    uint16_t w, h;
    gfx->getTextBounds(text, 0, 0, &x1, &y1, &w, &h);
    int xPos = (gfx->width() - w) / 2;
    int yPos = (gfx->height() - h) / 2;
    
    gfx->setCursor(xPos, yPos);
    gfx->print(text);
}

void resetDisplay() {
    firstRun = true;
    lastTimeStr = "";
    gfx->fillScreen(BLACK);
    startMillis = millis(); // Reset the timer
}

void loop() {
    // Read the door state (HIGH when open)
    bool currentDoorState = digitalRead(DOOR_PIN);
    
    // Check for state change
    if (currentDoorState != lastDoorState) {
        if (currentDoorState) {
            // Door just opened
            displayDoorOpen();
        } else {
            // Door just closed
            resetDisplay();
        }
        lastDoorState = currentDoorState;
    }
    
    // Only update the timer if door is closed
    if (!currentDoorState) {
        unsigned long currentMillis = millis();
        unsigned long elapsedSeconds = (currentMillis - startMillis) / 1000;
        displayTime(elapsedSeconds);
    }
    
    delay(100); // Small delay to prevent screen flicker
}