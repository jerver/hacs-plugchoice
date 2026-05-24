# PlugChoice Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

HACS custom integration for [PlugChoice](https://plugchoice.com) EV charge point management.

## Features

| Entity | Type | Description |
|---|---|---|
| Status | Sensor | Current OCPP status of the charger/connector |
| Total Energy | Sensor | Total kWh across all finished sessions |
| Session Energy | Sensor | kWh consumed in the current active session |
| Charging Power | Sensor | Live charging power in kW |
| Start Charging | Button | Send a remote start command |
| Stop Charging | Button | Send a remote stop command |

## Installation

### Via HACS (recommended)

1. Open HACS → **Integrations**
2. Click the three-dot menu → **Custom repositories**
3. Add `https://github.com/jeroen/hacs-plugchoice` with category **Integration**
4. Click **Download**
5. Restart Home Assistant

### Manual

Copy `custom_components/plugchoice/` into your `<config>/custom_components/` directory and restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & Services → Add Integration** and search for *PlugChoice*.
2. Enter your **Personal Access Token** (generate one at [account settings](https://app.plugchoice.com/settings/personal-access-tokens)).
3. Select the **charger** you want to monitor.
4. Enter the **default RFID token ID** used to authorise charging sessions (required to start charging remotely).

## API

This integration uses the [PlugChoice REST API v3](https://developer.plugchoice.com).

- Base URL: `https://app.plugchoice.com/api/v3`
- Auth: Bearer token (Personal Access Token)
- Poll interval: 30 seconds
