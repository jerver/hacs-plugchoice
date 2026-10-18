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
| Geplande laadenergie | Totaal aantal geplande kWh |
| Geplande zonne-energie | Gepland aantal kWh uit zonne-energie |
| Geplande netenergie | Gepland aantal kWh uit het net |

### Binaire sensoren

| Entiteit | Beschrijving |
|---|---|
| Active | `aan` wanneer er een actieve laadsessie loopt |

### Knoppen

| Entiteit | Beschrijving |
|---|---|
| Direct laden | Stelt het standaard laadprofiel in op de gekozen stroom (6–16 A) en start |
| Stop Charging | Stuur een remote-stop opdracht |
| Bereken laadschema | Bereken en bewaar het laadplan zonder de laadpaal aan te sturen |
| Optimaal laden | Start de sessie en past daarna het TxProfile van het opgeslagen laadplan toe |
| Verwijder laadplan | Verwijder alleen het lokaal opgeslagen schema |
| Laadschema opvragen | Vraag het samengestelde schema van de laadpaal op |

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
| Direct laden in schema | Uit | Laaduren chronologisch vullen op 16 A |
| Minimale zonneproductie | 0,3 kWh/uur | Ondergrens voor zonne-uren in fase 1 |
| Testmodus | Uit | Blokkeert alle PlugChoice API-verzoeken zolang deze is ingeschakeld |

De schakelaar **Test Mode** is ook als entiteit beschikbaar. In deze modus worden geen PlugChoice-verzoeken gedaan: ook initialisatie, polling, handmatige laadknoppen en geplande start-/stopacties blijven lokaal. Bij het inschakelen wordt de integratie opnieuw geladen. Als de modus bij een herstart al aanstaat, wordt ook de initiële API-validatie overgeslagen.

In testmodus toont de sensor **Charging Schedule** na het indrukken van een actieknop de request of acties die anders naar PlugChoice zouden gaan in `test_mode_message`. Gebruik bijvoorbeeld deze Markdown-kaart:

~~~yaml
type: markdown
title: PlugChoice testbericht
content: >
  ```json
  {{ state_attr('sensor.charging_schedule', 'test_mode_message')
    | to_json(pretty_print=True)
     | replace('\\n', '\n') }}
  ```
~~~

### Laadschema

De integratie leest `detailedHourly` van de Solcast-entiteiten `sensor.solcast_pv_forecast_voorspelling_vandaag`, `sensor.solcast_pv_forecast_voorspelling_morgen` en `sensor.solcast_pv_forecast_voorspelling_dag_3`. **Bereken laadschema** slaat een berekend schema op zonder verzoeken naar de laadpaal te sturen. Druk daarna op **Optimaal laden** om één startverzoek uit te voeren en vervolgens het TxProfile van het opgeslagen schema in te stellen, gekoppeld aan de transactie-id uit de startrespons. De laadpaal voert het schema uit, inclusief pauzes tussen laadperioden; Home Assistant gebruikt hiervoor geen start- of stoptimers. **Verwijder laadplan** verwijdert alleen het lokaal opgeslagen schema. De slider **Maximale laadstroom direct laden** stelt direct het TxDefaultProfile in op de gekozen stroom; **Direct laden** start daarna met dat profiel. **Stop Charging** stopt de sessie maar verwijdert geen laadprofielen van de laadpaal. In testmodus worden de acties niet uitgevoerd, maar als preview getoond.

De sensor **Charging Schedule** bevat de haalbaarheid, energie-totalen en `hourly_energy`-attributen met zonne- en netenergie per uur. Gebruik eerst **Bereken laadschema** om het plan te genereren. Bij onvoldoende capaciteit geeft de sensor de maximale beschikbare energie en foutmelding terug. Druk daarna op **Optimaal laden** om de laadsessie met dit plan te starten. De integratie stelt voor nieuwe entiteiten `sensor.charging_schedule` voor, maar Home Assistant kan een bestaande of conflicterende entity-id behouden. Controleer daarom de entity-id van **Charging Schedule** onder **Instellingen → Apparaten & Diensten → PlugChoice → apparaat** en gebruik die in beide kaarten.

Druk op **Laadschema opvragen** om het door de laadpaal berekende samengestelde schema op te vragen. De leesbare tekst staat daarna in `composite_schedule_text` van de sensor **Charging Schedule** en kan als volgt worden weergegeven:

```yaml
type: markdown
title: Laadschema laadpaal
content: >
  {{ state_attr('sensor.charging_schedule', 'composite_schedule_text')
     or 'Nog geen laadschema beschikbaar.' }}
```

`hourly_energy` bevat één datapunt per uur vanaf nu tot de deadline, met de ruwe Solcast-prognose (`pv_forecast_kwh`), de geplande zonne-/netenergie en de verdeling van de laadstroom in `solar_ampere` en `grid_ampere`. De som (`ampere`) is tijdens geplande laaduren altijd 6, 8, 10, 13 of 16 A; uren zonder gepland laden hebben waarde `0`. Eerst worden uren boven de drempel op aflopende Solcast-productie gerangschikt. Resterende energie wordt daarna bij voorkeur in uren met de minste zonneproductie als netstroom ingepland; zonnige laaduren worden pas naar 16 A verhoogd als er geen vrije uren meer zijn. De tekstuele planning staat in het attribuut `schedule_text` en kan met een Markdown-kaart worden getoond:

```yaml
type: markdown
title: Laadschema in tekst
content: >
  {{ state_attr('sensor.charging_schedule', 'schedule_text')
     or 'Nog geen laadschema beschikbaar.' }}
```

De berekende ampères zijn advies en worden gekozen uit 6, 8, 10, 13 en 16 A op basis van de verwachte zonneproductie. De integratie stuurt de geplande laadlimieten als charging profile naar de laadpaal en stuurt daarna één remote-startopdracht. De laadpaal voert het profiel uit; Home Assistant verstuurt geen remote-start- of remote-stopopdrachten per laadperiode. De werkelijke energie kan afwijken als de laadpaal of auto met een andere stroom laadt.

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
  yaxis:
    min: 0
    max: 16
    tickAmount: 8
    title:
      text: Laadstroom (A)
    labels:
      formatter: |
        EVAL:function (value) {
          return Math.round(value);
        }
  plotOptions:
    bar:
      columnWidth: 70%
series:
  - entity: sensor.charging_schedule
    name: Zonnestroom
    type: column
    color: "#E6B833"
    data_generator: |
      const hours = entity?.attributes?.hourly_energy ?? [];
      return hours.map((hour) => [
        new Date(hour.period_start).getTime(), hour.solar_ampere
      ]);
  - entity: sensor.charging_schedule
    name: Netstroom
    type: column
    color: "#398B8B"
    data_generator: |
      const hours = entity?.attributes?.hourly_energy ?? [];
      return hours.map((hour) => [
        new Date(hour.period_start).getTime(), hour.grid_ampere
      ]);
```

## API

Deze integratie gebruikt de [PlugChoice REST API v3](https://developer.plugchoice.com).

- Basis-URL: `https://app.plugchoice.com/api/v3`
- Authenticatie: Bearer token (Personal Access Token)
