# Daelim Smart Home Integration for Home Assistant

Home Assistant 커스텀 컴포넌트 for 대림 e편한세상 스마트홈 시스템.

## Features

This integration supports the following devices from the Daelim Smart Home system:

| Device Type | Platform | Features |
|-------------|----------|----------|
| **조명 (Lights)** | `light` | On/Off, Dimming (3-level for supported lights) |
| **난방 (Heating)** | `climate` | On/Off, Temperature control |
| **가스 밸브 (Gas Valve)** | `switch` | On/Off (safety lock) |
| **환기 (Ventilation/Fan)** | `fan` | On/Off, Speed control (3 levels), Auto mode |
| **대기전력 콘센트 (Standby Power Outlet)** | `switch` | On/Off |
| **방범모드 (Security/Guard Mode)** | `alarm_control_panel` | Away mode On/Off |
| **엘리베이터 호출 (Elevator Call)** | `button` | Press to call |
| **일괄차단 (All Off)** | `switch` | Turn off all devices |

## Installation

### HACS (Recommended)

1. Make sure [HACS](https://hacs.xyz/) is installed
2. Add this repository as a custom repository in HACS
3. Search for "Daelim Smart Home" and install
4. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/daelim_smarthome` folder to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

### Guided Setup (Recommended)

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for "Daelim Smart Home"
3. **Step 1 - Select Apartment**: 
   - The integration automatically fetches all 160+ e편한세상 apartment complexes
   - Select your apartment from the dropdown
4. **Step 2 - Select Building**:
   - Select your building (동) from the available options
5. **Step 3 - Enter Credentials**:
   - **Username**: Your e편한세상 app login ID
   - **Password**: Your e편한세상 app password
   - **Unit (호)**: Your unit number (e.g., `1204`)

That's it! The integration automatically discovers:
- Your apartment's server IP address
- The complex directory name
- All available building numbers

### Manual Fallback

If the apartment list cannot be fetched, you can enter values manually:
- **Host**: Usually `smarthome.daelim.co.kr`
- **Apartment ID**: e.g., `224` for e편한세상 대전법동
- **Building (동)**: e.g., `104`
- **Unit (호)**: e.g., `1204`

### Finding Your Configuration Values (Manual Mode)

If you need to enter values manually:

1. **Using the Apartment List Page**:
   - The integration fetches from `https://smarthome.daelim.co.kr/main/choice_1.do`
   - This page contains all apartment IDs, names, server IPs, and available buildings

2. **Using the Mobile App Network Capture**:
   - Use a network proxy tool (like Proxyman, Charles, mitmproxy)
   - Log into the e편한세상 mobile app
   - Look for the POST request to `loginProc.do` for values:
     - `user_id` → Username
     - `dong` → Building number
     - `ho` → Unit number

### Example Apartment Data

From the apartment list, here's an example for "e편한세상 대전법동":
```javascript
{
    apartId: "224",
    name: "e편한세상 대전법동",
    danjiDirectoryName: "beopdong",
    ip: "210.219.229.70",
    danjiDongInfo: "101,102,103,104,105,106,107,108,109,110,111,112"
}
```

This shows:
- Apartment ID is `224`
- Server IP is `210.219.229.70` (publicly accessible!)
- Available buildings are 101-112동

## Supported Devices

### Lights (조명)
- Individual light control with on/off
- Dimming support for lights with `dimming: "y"` configuration
- "All Lights" entity to control all lights at once

### Climate/Heating (난방)
- Individual room/zone thermostat control
- Set target temperature
- View current temperature
- Heat mode on/off

### Gas Valve (가스)
- Safety lock control
- Note: Opening gas valve remotely may be restricted for safety

### Ventilation/Fan (환기)
- On/Off control
- 3 speed levels: Low (약), Medium (중), High (강)
- Auto mode support

### Standby Power Outlets (대기전력 콘센트)
- Individual outlet control
- Cut standby power when off

### Security/Guard Mode (방범모드)
- Away mode (외출모드) arm/disarm
- Password support if required

### Elevator Call (엘리베이터 호출)
- Button to call elevator to your floor

### All Off (일괄차단)
- Master switch to turn off all devices at once

## Example Automations

### Turn off all lights when leaving home
```yaml
automation:
  - alias: "Turn off lights when leaving"
    trigger:
      - platform: state
        entity_id: person.your_name
        from: "home"
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.daelim_all_off
```

### Call elevator when you're almost home
```yaml
automation:
  - alias: "Call elevator when arriving"
    trigger:
      - platform: zone
        entity_id: person.your_name
        zone: zone.near_home
        event: enter
    action:
      - service: button.press
        target:
          entity_id: button.daelim_elevator_call
```

### Arm security when going to sleep
```yaml
automation:
  - alias: "Arm security at night"
    trigger:
      - platform: time
        at: "23:00:00"
    action:
      - service: alarm_control_panel.alarm_arm_away
        target:
          entity_id: alarm_control_panel.daelim_security
```

## Troubleshooting

### Cannot Connect
- Verify your credentials work in the official e편한세상 mobile app
- Check that you have the correct apartment ID and complex name
- Ensure your Home Assistant can reach the Daelim server

### Devices Not Showing
- Some devices may not be available in all apartment complexes
- Check the logs for any error messages
- Verify the device is visible in the official app

### Authentication Issues
- The integration uses the same authentication as the mobile app
- If you change your password, reconfigure the integration

## ⚠️ Architecture and How It Works

### System Architecture

The Daelim e편한세상 system uses a **hybrid architecture**:

1. **HTTP APIs** (`smarthome.daelim.co.kr`):
   - Authentication, apartment info, event logging
   - Returns the apartment server's **PUBLIC IP** via `selectApartInfoCheck.do`

2. **TCP Protocol** (Apartment Server - PUBLIC IP):
   - All device control uses a JSON-over-TCP protocol on port 25301
   - The server IP (e.g., `210.219.229.70`) is **publicly accessible**
   - **NO VPN or apartment network access required!**

### Auto-Discovery

When you configure the integration:
1. It calls `selectApartInfoCheck.do` with your apartment ID
2. The response includes `ipAddress` - the public IP of your apartment's server
3. The integration automatically connects to this IP for device control

Example response:
```json
{
  "item": [{
    "danjiName": "e편한세상 대전법동",
    "danjiDirectoryName": "beopdong",
    "ipAddress": "210.219.229.70"
  }]
}
```

## Known Limitations

- Gas valve opening is restricted for safety reasons (turn off only)
- Some apartment complexes may have different server configurations
- Protocol is reverse-engineered and may change with app updates

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## Disclaimer

This integration is not affiliated with or endorsed by Daelim Corporation (대림건설). Use at your own risk.

## License

MIT License
