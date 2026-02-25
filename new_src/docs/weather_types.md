# Weather Condition Taxonomy

The weather API returns one literal `condition` string per weather object.
That string must be one of the canonical snake_case values below.

## Canonical Conditions

| condition | Use when | Source SVG |
|---|---|---|
| `sunny` | Daytime and mostly clear. | `wi-day-sunny.svg` |
| `cloudy_light` | Slight cloud cover, still mostly bright. | `wi-day-sunny-overcast.svg` |
| `cloudy_thin` | Cloud cover with some brightness still visible. | `wi-day-cloudy-high.svg` |
| `cloudy_thick` | Heavy cloud cover / overcast feel. | `wi-day-cloudy.svg` |
| `rain` | Rain without notable wind signal. | `wi-day-rain.svg` |
| `sunny_rain` | Sun visible while raining. | `wi-day-rain-mix.svg` |
| `windy` | Wind-dominant conditions without rain. | `wi-strong-wind.svg` |
| `windy_rain` | Wind + rain together. | `wi-day-rain-wind.svg` |
| `snow` | Snowfall without storm-level severity. | `wi-day-snow.svg` |
| `severe_weather` | Any severe weather state where a warning-style icon is appropriate. | `wi-storm-warning.svg` |
| `night` | Nighttime and mostly clear. | `wi-night-clear.svg` |
| `night_rain` | Nighttime rain. | `wi-night-rain.svg` |
| `night_snow` | Nighttime snow. | `wi-night-snow.svg` |
| `snow_storm` | Snow + strong wind / blizzard-like conditions. | `wi-snow-wind.svg` |

## Notes

- Combined conditions are explicit by design (for example `windy_rain`), not
  modifier-based.
- This list is the source of truth for both `weather_now.condition` and
  `weather_1h.condition`.
- Unknown conditions should fall back to the placeholder icon in the renderer.