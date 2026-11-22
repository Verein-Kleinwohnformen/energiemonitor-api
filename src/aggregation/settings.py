"""Schwellen und Konstanten der Tageswerte.

Das sind Schwellen der Auswertung, keine Faktoren. Heizwerte und
Primärenergiefaktoren stehen nie im Code, sondern in /config/factors.
Die Schwellen folgen dem Konzept (docs/konzept/05_infotexte.md im App-Repo)
und der Auswertung Langzeittest.
"""

AGGREGATION_VERSION = 1
TIMEZONE = 'Europe/Zurich'

# Strom: Sensor-Reihenfolge pro Messpunkt und Feld der Leistung in W.
# TODO(prüfen): A1 wird von shelly-3em-pro und pzem-017 gemessen; gezählt wird
# der erste Sensor dieser Liste, der am Tag Daten hat.
POWER_SENSORS = [('victron', 'power'), ('shelly-3em-pro', 'act_power'), ('pzem-017', 'power')]
ELECTRIC_MPS = ['E1', 'E2', 'E3', 'A1', 'I1', 'I2', 'I3']
# Ein Messwert gilt höchstens so lange wie 3 mal der übliche Abstand,
# mindestens 30 s, höchstens 15 min. Längere Lücken zählen als nicht verfügbar.
STEP_FACTOR = 3
STEP_MIN_MS = 30_000
STEP_MAX_MS = 15 * 60_000

# Klima: Auflösung wie in der Studie (15 min).
CLIMATE_BUCKET_MS = 15 * 60_000
CLIMATE_SOURCES = ['netatmo', 'sensirion_voc']  # Studienquelle zuerst
HOT_THRESHOLD_C = 28.0
DAYTIME_HOURS = (8, 20)  # Tagesmittel für die heisseste Woche

# Belegung aus CO2, pro Sensor eine Regel:
# - Sensirion SCD4x: bewohnt, wenn das CO2 irgendwann über 600 ppm steigt
#   (wie Auswertung Langzeittest, Beispielhaus April bis September 125 Tage).
# - Netatmo: ihr Nullpunkt wandert (leeres Haus im April um 750, im September um
#   600 ppm), darum zählt der Anstieg: Höchstwert minus 10. Perzentil des Tages
#   über 150 ppm. Im Beispielhaus 127 Tage, an 167 von 183 Tagen gleich wie
#   Sensirion. Ein fester höherer Schwellwert trifft höchstens 151 von 183.
OCCUPANCY_SOURCES = ['sensirion_scd4x', 'netatmo']
OCCUPANCY_RULES = {
    'sensirion_scd4x': ('absolute', 600.0),
    'netatmo': ('rise', 150.0),
}
OCCUPANCY_BASELINE_PERCENTILE = 0.10
# TODO(prüfen): mit weniger als einem Viertel der Viertelstunden gilt die Belegung als unbekannt.
OCCUPANCY_MIN_COVERAGE = 0.25

# Ofensignatur (Feuer erkennen), Auflösung 10 min.
FIRE_BUCKET_MS = 10 * 60_000
FIRE_WINDOW_MS = 30 * 60_000  # Anstieg über mindestens 30 min
FIRE_RISE_K_PER_H = 3.0
FIRE_I2_MAX_W = 50.0  # keine elektrische Heizung
FIRE_E3_MAX_W = 300.0  # kein starker Sonneneintrag
# Sonne: Mit voller Batterie drosselt der Victron die PV, E3 zeigt dann wenig.
# Darum zählt der Höchstwert von E3 (10-min-Mittel) ab 2 h vor dem Anstieg.
FIRE_SUN_LOOKBACK_MS = 2 * 3600_000
FIRE_MERGE_MS = 2 * 3600_000  # weniger als 2 h Abstand = ein Feuer
FIRE_MAX_DURATION_MS = 12 * 3600_000
# Rohdaten vor und nach dem Tag, damit Feuer über Mitternacht ganz erfasst werden.
FIRE_LOOKBACK_MS = 3 * 3600_000
FIRE_LOOKAHEAD_MS = 12 * 3600_000

# Heizgradtage (Fallback 2): 20 °C minus Tagesmittel aussen, nur Tage unter 12 °C.
HDD_BASE_C = 20.0
HDD_LIMIT_C = 12.0

# Brennstoffe und Verteilmethoden, in der Reihenfolge der Fallbacks.
FIRE_FUELS = {'pellets', 'woodKg', 'woodSter', 'oil'}
OCCUPANCY_FUELS = {'propane'}
# Diesel und Benzin werden nicht auf Tage verteilt (Konzept 2.3).
METHODS_FIRE = ['ofensignatur', 'heizgradtage', 'gleichmaessig']
METHODS_OCCUPANCY = ['bewohnte_tage', 'gleichmaessig']
