# Watchy - python

<img src="./assets/watchy-new-face.JPG" width="300" />

This project takes a Watchy device and builds a watch, weather, and meeting calendar from it.

Forked and based heavily off [hueyy's watchy_py](https://github.com/hueyy/watchy_py)

## General idea

I didn't want to use the watchy as a literal wristwatch, but rather as a very tiny status display screen near my desk. I wanted it to show me the weather, the time (roughly), and what meetings I have coming up, so that's all it does.

### Time

This is the part I'm most proud of. I thought it would be inefficient to refresh every minute, but obviously I want to know the time at a glance.

I realized usually I don't care if it's, say, 9:07 vs 9:08, but do care if it's 9:28 vs 9:30.

So I display the hour and then a circle draws around the hour representing progression of time. 9:00 - 9:13 (just 2 min before something important) is a light arc, then 9:13-9:15 is a heavy arc. So at-a-glance you'll know "It's between 9 and 9:15 but not quite 9:15 yet" or "It will be 9:15 within 2 minutes, better get a move on if I have something that has to happen at 9:15". 

### Weather

I also realized there are some weather conditions I care about and some I don't. They are outlined in [weather_types](new_src/docs/weather_types.md). 

The watch displays the weather from the type list and the temperature this hour and the same info for the next hour

### Meetings

I also care what meetings I have this day at-a-glance.

Meetings are shown in chronological order with start time, and small description text. There's also an icon for what kind of meeting it is, and then filled circles for the duration of the meeting (1 circle = 1 hour)

### Server with bluetooth

Rather than the watch processing data itself, we have a server running that sends updates via bluetooth. This is much more energy efficient than using wifi, and also lets us do arbitrarily complex things (like auth with microsoft outlook or processing complex weather logic) and pushing out something simple back to the watch. This works because the watch will be largely stationary and close to a bluetooth laptop when used as a tiny display.

This was heavily inspired by the model [TRMNL](https://trmnl.com) uses (the display is dumb, the server is smart and just pushes display items)

As this project changes, I'll adhere to this principle.

## Getting started

I moved hueyy's original README to [README-old.md](README-old.md) and all of it still holds.

In general though, you have to:
1. figure out where your watchy is located
2. erase whatever's there with `esptool.py`
3. flash the latest micropython
4. connect to the device with `rshell`
5. do a `rsync` of the `new_src/src` directory into `/pyboard` (or `rsync` the `old_src` directory if you want hueyy's original version)

## Prerequisites and quirks

### Timekeeping hardware
First, the watchy I have is a knockoff watchy, so instead of using DS3231 (with reasonable real time timekeeping), this uses a BM8563 (which is around 10x worse at timekeeping). 

If you have a real watchy or just better hardware, you will want to use the [ds3231.py driver](old_src/lib/ds3231.py) instead.

### Secrets files

There's a [secrets example](new_src/src/secrets.example.py) in the watch firmware and a [secrets example](new_src/ble_server/secrets.example.py)

These are needed for the various functionality to work

The `AUTH_TOKEN` is the shared secret between the client and server. Keep this secret as this is what is used to encrypt the data between the device and server!

Yes, I know bluetooth has its own encryption but getting it to work right with Linux and MacOS simultaniously proved too difficult, so I introduced application-level encryption instead.

### MS calendar integration

As of this writing, there's only MS calendar integration, and setting that up is a bit complex.

1. Create an app registration in [Azure Portal](https://portal.azure.com) → Entra ID → App registrations. Note the **Application (client) ID** and **Directory (tenant) ID**.
2. Add API permissions: Microsoft Graph → Delegated → `User.Read`, `Calendars.Read`. Admin consent may be required for work accounts.
3. Copy `ble_server/secrets.example.py` to `ble_server/secrets.py` and set `MS_TENANT_ID` and `MS_CLIENT_ID`.
4. Run `cd new_src && python -m ble_server.sign_in` — it prints a URL and code; open the URL in a browser, sign in, and enter the code. The token is cached for the server to use.

## Regular usage

### Server
Regularly, you have the server running via `cd new_src; python -m ble_server`. It will fetch weather and put it in ble_server/cache/weather.json every 45 minutes. 

It will fetch meetings every 20 minutes and cache in ble_server/cache/calendar.json

Whenever the watch asks, it will serve whatever is in the cache (the watch can't request live info as the edge cases there become silly).

### Watch

#### Bluetooth refresh
When you press and hold the TOP LEFT button on the watch, this causes the watch to ask for a bluetooth update. It will try to get data from anything broadcasting the right UUID but the payload will be encrypted using the shared AUTH_TOKEN

#### Pairing
When you press and hold the TOP LEFT and BOTTOM LEFT buttons together, you get 'pairing mode' which will also change the message on the screen to say 'pairing mode'. In practice, this just clears the remembered server address. It doesn't really pair... it did for a while but, again, getting bluetooth to work right with Mac and Linux at once proved too challenging.

#### Debug mode
The default mode is that the watch is mostly in deep sleep. Its real-time clock wakes up at certain times to refresh the screen, fetch info, etc then it goes back to deep sleep.

This makes it very hard to debug, even if you're plugged in to it... it won't stay awake long enough.

If you hold down the BOTTOM LEFT button for a while though, you'll get a message saying 'debug mode on'. This prevents it from going to deep sleep so you can debug.

Theoretically the watch just keeps working like normal... if you go to `repl` and hit `ctrl+c` you should get a python shell.

Note that if you're stuck in this `repl` state the watch might stop updating until you get out. In order to do that, inside `repl` just type in `import exit_debug`

## Font Previews

It was really important for me to find a nice font, so I vibe-coded an app in [font_previews](font_previews/app.py).  

It renders the screen and lets you play around with potential fonts.

### Font notes
Apparently, converting a font essentially means rendering out every single character and creating a bitmap of it(!!) So naturally you shouldn't have a lot of fonts or else you will run out of memory really quickly. The giant font here only has the watch face.

## Weather icons
Weather icons from [https://github.com/erikflowers/weather-icons/]

## Fonts
Characters from google fonts, notably FiraSans and zendots

## A note on AI

I'm a python guy but not a hardware guy... much of this code was AI-assisted, but that just means I was able to execute on my vision much faster than I would have been able to do on my own.

