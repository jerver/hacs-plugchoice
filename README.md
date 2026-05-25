# PlugChoice Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

HACS custom integration voor [PlugChoice](https://plugchoice.com) EV-laadpaalbeheer.

## Entiteiten

### Sensoren

| Entiteit | Beschrijving |
|---|---|
| Connection Status | Verbindingsstatus van de lader (online/offline) |
| Charger Error | Foutcode op laadpaal-niveau |
| Status | OCPP-status van de geselecteerde connector |
| Connector Error | Foutcode op connector-niveau |
| Total Energy | Totaal verbruikte kWh volgens de energiemeter van de lader (Energy.Active.Import.Register) |
| Session Energy | kWh verbruikt in de huidige actieve sessie (uit lopende transactie) |
| Charging Power | Actueel laadvermogen in kW (real-time meting) |
| Last Session Start Time | Starttijdstip van de laatste laadsessie |
| Last Session End Time | Eindtijdstip van de laatste laadsessie |
| Last Session Stop Reason | Reden waarom de laatste sessie is gestopt |

### Binaire sensoren

| Entiteit | Beschrijving |
|---|---|
| Active | `aan` wanneer er een actieve laadsessie loopt |

### Knoppen

| Entiteit | Beschrijving |
|---|---|
| Start Charging | Stuur een remote-start opdracht |
| Stop Charging | Stuur een remote-stop opdracht |

### Schakelaars

| Entiteit | Beschrijving |
|---|---|
| Uitgesteld laden actief | Schakel uitgesteld laden in of uit |

### Tijdinstellingen

| Entiteit | Standaard | Beschrijving |
|---|---|---|
| Starttijd uitgesteld laden | 22:00 | Tijdstip waarop het laden automatisch mag starten |

> De schakelaar en starttijd worden lokaal opgeslagen en hersteld na een herstart van Home Assistant. Gebruik ze in een automatisering om op een gewenst tijdstip de knop **Start Charging** te activeren.

## Installatie

### Via HACS (aanbevolen)

1. Open HACS → **Integraties**
2. Klik op het driepuntenmenu → **Aangepaste opslagplaatsen**
3. Voeg `https://github.com/jerver/hacs-plugchoice` toe met categorie **Integratie**
4. Klik op **Downloaden**
5. Herstart Home Assistant

### Handmatig

Kopieer de map `custom_components/plugchoice/` naar `<config>/custom_components/` en herstart Home Assistant.

## Configuratie

1. Ga naar **Instellingen → Apparaten & Diensten → Integratie toevoegen** en zoek op *PlugChoice*.
2. Voer je **Personal Access Token** in (aanmaken via [accountinstellingen](https://app.plugchoice.com/settings/personal-access-tokens)).
3. Selecteer de **laadpaal** die je wilt monitoren.
4. Voer de **standaard RFID-token ID** in voor het autoriseren van laadsessies (vereist voor remote starten).

### Opties (via Configureren)

Na de eerste installatie zijn aanvullende opties beschikbaar via **Configureren**:

| Optie | Standaard | Omschrijving |
|---|---|---|
| Polling interval | 30 s | Hoe vaak de API wordt geraadpleegd (10–3600 s) |
| Connector ID | 1 | OCPP connector-nummer waarvan status en fout worden getoond |

## Voorbeeldautomatisering: uitgesteld laden

```yaml
alias: "PlugChoice – start laden op ingestelde tijd"
trigger:
  - platform: time
    at: sensor.plugchoice_starttijd_uitgesteld_laden
condition:
  - condition: state
    entity_id: switch.plugchoice_uitgesteld_laden_actief
    state: "on"
action:
  - action: button.press
    target:
      entity_id: button.plugchoice_start_charging
```

## API

Deze integratie gebruikt de [PlugChoice REST API v3](https://developer.plugchoice.com).

- Basis-URL: `https://app.plugchoice.com/api/v3`
- Authenticatie: Bearer token (Personal Access Token)
