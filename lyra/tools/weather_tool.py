"""
Phase 5 — weather tool.

Uses Open-Meteo (https://open-meteo.com), a free weather API that needs
no API key and no signup — consistent with the rest of this project
running on free-tier services (see README's STT note for the same
reasoning). Two calls per lookup:
  1. Open-Meteo's geocoding API turns a place name into lat/lon.
  2. Open-Meteo's forecast API returns current conditions for that
     lat/lon.

Network errors are the one thing every tool in this framework should
raise as RuntimeError rather than let escape, per tools/base.py's
ToolSpec.func contract — handled the same way llm_client.py/providers/
handle their own SDK exceptions.

The `requests` import is deliberately lazy (inside get_weather(), not at
module top) — same reasoning as websearch_tool.py's lazy `ddgs` import:
tools/__init__.py auto-imports every module in this package at app
startup, so a top-level import here would mean a missing dependency
crashes the whole app instead of just this one tool call.
"""

from .base import ToolSpec
from .registry import register_tool

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT = 10  # seconds

# WMO weather codes -> plain description. Open-Meteo returns the numeric
# code as-is; this is the standard short mapping from Open-Meteo's docs.
_WEATHER_CODES = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snow fall",
    73: "moderate snow fall",
    75: "heavy snow fall",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


def get_weather(location: str, unit: str = "celsius") -> str:
    """Look up current weather for `location` (a city/place name). `unit`
    is 'celsius' or 'fahrenheit'."""
    try:
        import requests
    except ImportError as e:
        raise RuntimeError(
            "The 'requests' package isn't installed. Run "
            "'pip install requests' (see requirements.txt) to enable weather lookups."
        ) from e

    unit = unit.strip().lower()
    if unit not in ("celsius", "fahrenheit"):
        unit = "celsius"

    try:
        geo_resp = requests.get(
            _GEOCODE_URL,
            params={"name": location, "count": 1},
            timeout=_TIMEOUT,
        )
        geo_resp.raise_for_status()
        geo_data = geo_resp.json()
    except Exception as e:
        raise RuntimeError(f"Could not look up location '{location}': {e}") from e

    results = geo_data.get("results") or []
    if not results:
        raise RuntimeError(f"No location found matching '{location}'.")

    place = results[0]
    lat, lon = place["latitude"], place["longitude"]
    place_label = ", ".join(
        part
        for part in (place.get("name"), place.get("admin1"), place.get("country"))
        if part
    )

    try:
        forecast_resp = requests.get(
            _FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "temperature_unit": unit,
                "wind_speed_unit": "mph" if unit == "fahrenheit" else "kmh",
            },
            timeout=_TIMEOUT,
        )
        forecast_resp.raise_for_status()
        forecast_data = forecast_resp.json()
    except Exception as e:
        raise RuntimeError(f"Could not fetch weather for {place_label}: {e}") from e

    current = forecast_data.get("current")
    if not current:
        raise RuntimeError(f"Weather service returned no current conditions for {place_label}.")

    temp = current.get("temperature_2m")
    humidity = current.get("relative_humidity_2m")
    wind = current.get("wind_speed_10m")
    code = current.get("weather_code")
    condition = _WEATHER_CODES.get(code, "unknown conditions")

    deg = "°F" if unit == "fahrenheit" else "°C"
    wind_unit = "mph" if unit == "fahrenheit" else "km/h"

    return (
        f"{place_label}: {condition}, {temp}{deg}, "
        f"humidity {humidity}%, wind {wind} {wind_unit}."
    )


register_tool(
    ToolSpec(
        name="get_weather",
        description=(
            "Get current weather conditions for a city or place. Use this "
            "whenever the user asks about the weather, temperature, or "
            "conditions somewhere, instead of guessing."
        ),
        parameters={
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City or place name, e.g. 'Jaipur' or 'Paris, France'.",
                },
                "unit": {
                    "type": "string",
                    "description": "Temperature unit: 'celsius' or 'fahrenheit'. Defaults to celsius.",
                },
            },
            "required": ["location"],
        },
        func=get_weather,
    )
)
