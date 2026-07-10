# ScentAir Home Assistant Integration

A custom component for [Home Assistant](https://www.home-assistant.io/) to control **ScentAir Whisper HOME** devices.

**Requirement**: This integration controls ScentAir devices via the Cloud API.
> [!IMPORTANT]
> Your device must be visible and controllable on the [ScentAir Connect Web Portal](https://scentconnect.com/) to work with this integration. Devices that only appear in the mobile app (via Bluetooth or local caching) are **not supported**.

## Device Setup
Before installing this component, ensure your device is connected to the ScentAir Cloud (ScentConnect):

1.  **Wi-Fi Provisioning**:
    *   Download the official **ScentAir** app.
    *   Click **"Sign into Your Account"**.
    *   On the login screen, scroll down to **"Enterprise Wi-Fi Setup"**.
    *   Follow the steps to connect your device to Wi-Fi.

2.  **Claim Device**:
    *   If the device is currently on your personal account, you must **release** it first.
    *   **Claim** the device on [ScentConnect.com](https://scentconnect.com/).

3.  **Verify**: Log in to [ScentConnect.com](https://scentconnect.com/) and verify you can control your device (Fan Speed / Lights).

## Features
Each device gets the following entities:
- **Fan**: Turn the diffuser On/Off and set intensity (1-100%).
- **Fan Speed** (number): Set the raw fan speed (0-10) directly.
- **Logo Light**: Toggle the device LED backlight.
- **Accent Light**: RGB accent light with color selection.
- **Accent Color** (select): Pick the accent color by name.
- **Online** (binary sensor): Cloud connectivity status of the device.

Other capabilities:
- **Multi-Device**: Automatically discovers all devices on your ScentAir account, including devices added after setup.
- **Reauthentication**: If your ScentConnect password changes, Home Assistant prompts you to reauthenticate instead of failing silently.

## Installation

### Via HACS (Recommended)
1. Ensure [HACS](https://hacs.xyz/) is installed.
2. Add this repository [![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/simplytoast1/ScentAirHABridge)
   - Category: `Integration`
3. Search for "ScentAir" and install.
4. Restart Home Assistant.

### Manual Installation
1. Copy the `custom_components/scentair` folder to your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.

## Configuration
1. Go to **Settings > Devices & Services**.
2. Click **+ Add Integration**.
3. Search for **ScentAir**.
4. Log in with your ScentConnect email and password.

## Disclaimer
This integration is not affiliated with, associated with, or endorsed by ScentAir. It uses an unofficial API which may change at any time. Use at your own risk.
