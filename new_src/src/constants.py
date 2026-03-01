from micropython import const
import bluetooth

WHITE = 1
BLACK = 0

MENU_PIN = const(26)
BACK_PIN = const(25)
UP_PIN = const(32)
DOWN_PIN = const(4)

RTC_SDA_PIN = const(21)
RTC_SCL_PIN = const(22)
RTC_INT_PIN = const(27)

VIBRATE_MOTOR_PIN = const(13)

BATT_ADC_PIN = const(33)

# Display dimensions
DISPLAY_W = const(200)
DISPLAY_H = const(200)

# Zone geometry — keep in sync with display-layout.md
TOP_STRIP_H = const(23)    # separator line sits at y=23
CLOCK_ZONE_TOP = const(24)
WEATHER_X = const(100)     # x where weather zone starts / clock|weather divider
MEETINGS_Y = const(128)    # y where meetings zone starts

# Ring clock geometry — keep in sync with new_src/build/generate_arcs.py
RING_CENTER_X = const(50)
RING_CENTER_Y = const(75)
RING_OUTER_R = const(46)
RING_INNER_R_THICK = const(39)  # 7 px ring width
RING_INNER_R_THIN = const(43)   # 3 px ring width

# Meetings zone geometry — keep in sync with display-layout.md
MEETINGS_ROW_H    = const(20)   # 16 px font + 4 px between rows
MEETINGS_MAX_ROWS = const(3)

# Gap bar: checkerboard strip shown when next event is >= threshold away
GAP_BAR_H             = const(7)   # height of the strip in pixels
GAP_BAR_THRESHOLD_MIN = const(60)  # minutes gap that triggers the bar

# Meetings column x-positions (tunable after hardware evaluation)
# Row order: duration, start time, type glyph, title.
MEETINGS_COL_DUR   = const(4)    # duration glyph(s), up to 2 chars wide
MEETINGS_COL_TIME  = const(42)   # shifted right to leave room for 2-glyph durations
MEETINGS_COL_TYPE  = const(88)   # keep spacing after wider time placement
MEETINGS_COL_TITLE = const(108)  # event title

# Battery voltage thresholds (LiPo: 4.2 V full, 3.0 V empty)
BATT_MAX_V = 4.2
BATT_MIN_V = 3.0
BATT_BAR_W = const(30)
BATT_BAR_H = const(6)

# ---------------------------------------------------------------------------
# BLE
# ---------------------------------------------------------------------------

# Custom 128-bit UUIDs for the Watchy sync service.
# The laptop peripheral advertises BLE_SERVICE_UUID.
# TX = watch writes requests to this characteristic (write-with-response).
# RX = laptop sends responses via notifications on this characteristic.
BLE_SERVICE_UUID = bluetooth.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
BLE_TX_CHAR_UUID = bluetooth.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567891")
BLE_RX_CHAR_UUID = bluetooth.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567892")

BLE_SCAN_TIMEOUT_MS    = const(8000)
BLE_CONNECT_TIMEOUT_MS = const(30000)  # Higher for intermittent laptop responsiveness
BLE_SYNC_TIMEOUT_MS    = const(10000)
BLE_PAIRING_TIMEOUT_MS = const(30000)

# Set True to use mock data without BLE (for REPL / dev convenience).
DUMMY_DATA = False