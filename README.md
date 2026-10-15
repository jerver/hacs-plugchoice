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
| Charging Schedule | Haalbaarheid, energie-totalen en uurdata van het opgeslagen laadschema |

### Binaire sensoren

| Entiteit | Beschrijving |
|---|---|
| Active | `aan` wanneer er een actieve laadsessie loopt |

### Knoppen

| Entiteit | Beschrijving |
|---|---|
| Start Charging | Stuur een remote-start opdracht |
| Stop Charging | Stuur een remote-stop opdracht |
| Create Charging Plan | Bereken en plan een laadschema |
| Cancel Charging Plan | Annuleer het opgeslagen schema en geplande acties |

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
2. Klik op het driepuntenmenu → **Aangepaste repositories**
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
| Gewenste afstand | Verplicht | Benodigde rijafstand in km |
| Verbruik auto | 6,6 km/kWh | Efficiëntie van de auto |
| Deadline | Verplicht | Uiterste laadtijd, geïnterpreteerd in Europe/Amsterdam |
| Direct laden | Uit | Laaduren chronologisch vullen op 16 A |
| Minimale zonneproductie | 0,3 kWh/uur | Ondergrens voor zonne-uren in fase 1 |
| Testmodus | Uit | Blokkeert alle PlugChoice API-verzoeken zolang deze is ingeschakeld |

De schakelaar **Test Mode** is ook als entiteit beschikbaar. In deze modus worden geen PlugChoice-verzoeken gedaan: ook initialisatie, polling, handmatige laadknoppen en geplande start-/stopacties blijven lokaal. Bij het inschakelen wordt de integratie opnieuw geladen. Als de modus bij een herstart al aanstaat, wordt ook de initiële API-validatie overgeslagen.

### Laadschema

De integratie leest `detailedHourly` van de Solcast-entiteiten `sensor.solcast_pv_forecast_voorspelling_vandaag`, `sensor.solcast_pv_forecast_voorspelling_morgen` en `sensor.solcast_pv_forecast_voorspelling_dag_3`. Na het instellen van de opties maakt **Create Charging Plan** een schema en slaat dit op. Een haalbaar schema wordt automatisch uitgevoerd; **Cancel Charging Plan** annuleert de geplande acties.

De sensor **Charging Schedule** bevat de haalbaarheid, energie-totalen en `hourly_energy`-attributen met zonne- en netenergie per uur. Druk na configuratie op **Create Charging Plan** om het schema te genereren. Bij onvoldoende capaciteit geeft de sensor de maximale beschikbare energie en foutmelding terug. De integratie stelt voor nieuwe entiteiten `sensor.charging_schedule` voor, maar Home Assistant kan een bestaande of conflicterende entity-id behouden. Controleer daarom de entity-id van **Charging Schedule** onder **Instellingen → Apparaten & Diensten → PlugChoice → apparaat** en gebruik die in beide kaarten.

`hourly_energy` bevat één datapunt per uur vanaf nu tot de deadline, met de ruwe Solcast-prognose (`pv_forecast_kwh`) en de geplande zonne-/netenergie. Uren zonder gepland laden hebben voor de laadenergie waarde `0`. In fase 1 worden uren boven de drempel op aflopende Solcast-productie gerangschikt en eerst geselecteerd. De tekstuele planning staat in het attribuut `schedule_text` en kan met een Markdown-kaart worden getoond:

```yaml
type: markdown
title: Laadschema in tekst
content: >
  {{ state_attr('sensor.charging_schedule', 'schedule_text')
     or 'Nog geen laadschema beschikbaar.' }}
```

De berekende ampères zijn advies: de huidige PlugChoice API-integratie kan de laadstroom niet instellen. Automatische uitvoering verstuurt daarom alleen de bestaande remote-start- en remote-stopopdrachten op de geplande tijden. De werkelijke energie kan afwijken als de laadpaal of auto met een andere stroom laadt.

Voor een staafgrafiek is de communitykaart [ApexCharts Card](https://github.com/RomRider/apexcharts-card) nodig. Voeg na installatie deze kaart toe aan een dashboard en vervang zo nodig de sensor-entiteit:

```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Laadschema
graph_span: 72h
span:
  start: hour
update_delay: 3s
apex_config:
  chart:
    stacked: true
  xaxis:
    type: datetime
  plotOptions:
    bar:
      columnWidth: 70%
  stroke:
    width: 3
series:
  - entity: sensor.solcast_pv_forecast_voorspelling_vandaag
    name: Solcast vandaag
    type: line
    color: "#FFF0A6"
    data_generator: |
      const hours = entity?.attributes?.detailedHourly ?? [];
      return hours.map((hour) => [
        new Date(hour.period_start).getTime(), Number(hour.pv_estimate)
      ]).filter(([timestamp, value]) => Number.isFinite(timestamp) && Number.isFinite(value));
  - entity: sensor.solcast_pv_forecast_voorspelling_morgen
    name: Solcast morgen
    type: line
    color: "#FFF0A6"
    data_generator: |
      const hours = entity?.attributes?.detailedHourly ?? [];
      return hours.map((hour) => [
        new Date(hour.period_start).getTime(), Number(hour.pv_estimate)
      ]).filter(([timestamp, value]) => Number.isFinite(timestamp) && Number.isFinite(value));
  - entity: sensor.solcast_pv_forecast_voorspelling_dag_3
    name: Solcast dag 3
    type: line
    color: "#FFF0A6"
    data_generator: |
      const hours = entity?.attributes?.detailedHourly ?? [];
      return hours.map((hour) => [
        new Date(hour.period_start).getTime(), Number(hour.pv_estimate)
      ]).filter(([timestamp, value]) => Number.isFinite(timestamp) && Number.isFinite(value));
  - entity: sensor.charging_schedule
    name: Zonne-energie
    type: column
    data_generator: |
      const hours = entity?.attributes?.hourly_energy ?? [];
      return hours.map((hour) => [
        new Date(hour.period_start).getTime(), hour.solar_kwh
      ]);
  - entity: sensor.charging_schedule
    name: Netstroom
    type: column
    data_generator: |
      const hours = entity?.attributes?.hourly_energy ?? [];
      return hours.map((hour) => [
        new Date(hour.period_start).getTime(), hour.grid_kwh
      ]);
```

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
