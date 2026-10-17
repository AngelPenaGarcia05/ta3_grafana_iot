# Pruebas del sistema de monitoreo IoT (TA3, Grupo 4)

Equipo monitoreado: motor eléctrico de 22 kW de la cinta transportadora (`motor-01`, línea `envasado-1`).

> **Importante:** el nodo IoT es un **SIMULADOR** en Python. Todas las pruebas usan datos generados por software, no lecturas de un sensor físico. Los umbrales son supuestos del caso y deben validarse con el fabricante en una implementación real.

## Entorno de prueba

| Elemento | Detalle |
|---|---|
| Equipo | Laptop con Windows 11 Home y Docker Desktop (Docker 27.5.1, Compose 2.32.4) |
| Servicios | EMQX 5.8.6, Telegraf 1.34.4, InfluxDB 2.7.11, Grafana 11.6.1 (Docker Compose) |
| Nodo | `node/simulador.py` (Python 3.13.7, paho-mqtt 2.1.0) |
| Fecha | 16 de octubre de 2026, hora de Lima (UTC-5). Los datos MQTT se registran en UTC |

## Cómo leer el estado de cada prueba

| Estado | Significado |
|---|---|
| **Ejecutada** | La prueba se corrió de verdad y el resultado obtenido está registrado en un archivo de `docs/evidencias/` |
| **Ejecutada, falta captura** | La prueba se corrió, pero falta la captura de pantalla que debe tomar el grupo (MQTTX o Grafana) |
| **Solo comportamiento esperado** | La prueba no se ejecutó; se describe lo que debería pasar según el diseño |

Las pruebas marcadas como ejecutadas se corrieron con scripts de verificación. Los scripts consultan los mismos servicios que usa el sistema: un suscriptor MQTT de prueba, consultas Flux a InfluxDB y la API de Grafana. No usan MQTTX ni la pantalla de Grafana. Por eso las capturas de pantalla las debe tomar el grupo.

## Resumen

| # | Prueba | Estado | Evidencia |
|---|---|---|---|
| 1 | Lectura normal | Ejecutada | `evidencias/prueba1_lectura_normal.txt` |
| 2 | Transmisión y recepción | Ejecutada, falta captura de MQTTX | `evidencias/prueba2_transmision_recepcion.txt` |
| 3 | Almacenamiento | Ejecutada, falta captura del Data Explorer | `evidencias/prueba3_almacenamiento.txt` |
| 4 | Visualización | Ejecutada, falta captura del dashboard | `evidencias/prueba4_visualizacion_api.txt` |
| 5 | Umbral superado | Ejecutada, falta captura del dashboard y de las alertas | `evidencias/fase6_registro_escenarios.txt` |
| 6 | Interrupción de comunicación | Ejecutada, falta captura de MQTTX y de Grafana | `evidencias/fase6_registro_escenarios.txt` |

---

## Prueba 1: lectura normal

**Objetivo:** comprobar que el nodo genera lecturas creíbles, dentro del rango normal y con la frecuencia definida.

**Procedimiento:**

```bash
py node/simulador.py
```

Dejarlo funcionando unos 30 segundos y revisar la consola.

**Resultado esperado:** el aviso de SIMULADOR al inicio. Temperatura cada 5 s entre 45 y 70 °C, vibración cada 1 s hasta 2.8 mm/s y corriente cada 2 s entre 28 y 40 A. Todas las lecturas marcadas `[normal]` y `enviado`.

**Resultado obtenido** (16/10/2026, 19:48, unos 32 s de ejecución):

| Variable | Lecturas | Mínimo | Máximo | Rango normal del caso |
|---|---|---|---|---|
| Temperatura de carcasa | 7 | 59.69 °C | 60.44 °C | 45 a 70 °C |
| Vibración RMS | 32 | 1.374 mm/s | 1.974 mm/s | hasta 2.8 mm/s |
| Corriente | 16 | 34.13 A | 35.98 A | 28 a 40 A |
| Potencia (calculada) | 16 | 19.32 kW | 20.37 kW | motor de 22 kW nominales |

Las 55 lecturas quedaron como `[normal]` y `enviado`; ninguna quedó en cola. La consola muestra el aviso "SIMULADOR DE NODO IoT (no es un sensor físico)".

**Estado:** Ejecutada. **Cumple.**

---

## Prueba 2: transmisión y recepción

**Objetivo:** comprobar que los mensajes llegan al broker EMQX y que un cliente suscrito los recibe completos, con QoS 1 y en formato JSON.

**Procedimiento:**
1. Con el simulador encendido, abrir MQTTX y conectarse a `localhost:1883`.
2. Suscribirse a `fabrica/envasado1/motor01/#` con QoS 1.
3. Revisar los mensajes que llegan.

**Resultado esperado:**
- Llegan mensajes en los cuatro tópicos (temperatura, vibración, consumo y estado).
- Cada mensaje es un JSON con `machine_id`, `line`, el valor medido, `timestamp` en UTC y `simulado: true`.
- El tópico estado muestra `online` al conectarse el simulador.

**Resultado obtenido** (16/10/2026, 19:48). Un suscriptor de prueba en Python, conectado igual que MQTTX, recibió en unos 32 s:

| Tópico | Mensajes recibidos | QoS |
|---|---|---|
| `fabrica/envasado1/motor01/temperatura` | 7 | 1 |
| `fabrica/envasado1/motor01/vibracion` | 32 | 1 |
| `fabrica/envasado1/motor01/consumo` | 16 | 1 |
| `fabrica/envasado1/motor01/estado` | 3 | 1 |

Los mensajes recibidos coinciden en cantidad con los publicados en la prueba 1. Ejemplo recibido:

```json
{"machine_id": "motor-01", "line": "envasado-1", "temperature_c": 60.02, "timestamp": "2026-10-17T00:48:07.010Z", "simulado": true}
```

Los 3 mensajes de estado fueron:
1. `offline` retenido de una sesión anterior (el broker lo entrega al suscribirse).
2. `online` al conectarse el simulador.
3. `offline` con motivo `desconexion_inesperada` al cortar el proceso a la fuerza (Last Will).

Además, Telegraf recibió los mismos mensajes, como se ve en la prueba 3.

**Estado:** Ejecutada. **Cumple.** Falta la captura de pantalla de MQTTX, que debe tomar el grupo.

---

## Prueba 3: almacenamiento

**Objetivo:** comprobar que Telegraf guarda cada lectura en InfluxDB con el measurement, las etiquetas y la hora correctos.

**Procedimiento:**
1. Con el simulador encendido, abrir http://localhost:8086 y luego el Data Explorer.
2. En "Script Editor", ejecutar:

```
from(bucket: "planta")
  |> range(start: -15m)
  |> filter(fn: (r) => r._measurement == "temperatura_motor")
  |> filter(fn: (r) => r.machine_id == "motor-01")
  |> filter(fn: (r) => r._field == "temperature_c")
```

**Resultado esperado:**
- En el bucket `planta` existen los measurements `temperatura_motor`, `vibracion_motor` y `consumo_motor`, con las etiquetas `machine_id = motor-01` y `line = envasado-1`.
- Cada punto tiene la misma hora (UTC) que el `timestamp` del mensaje del simulador.

**Resultado obtenido** (16/10/2026, 19:48, consulta Flux del último minuto):

| Measurement | Campo | Puntos guardados |
|---|---|---|
| `consumo_motor` | `current_a` | 16 |
| `consumo_motor` | `power_kw` | 16 |
| `temperatura_motor` | `temperature_c` | 7 |
| `vibracion_motor` | `vibration_mms` | 32 |

Las cantidades coinciden con las lecturas publicadas en la prueba 1, así que no se perdió ninguna. Las temperaturas guardadas tienen la misma hora, hasta el milisegundo, que el simulador. Por ejemplo, la lectura de las 00:48:22.005Z vale 59.95 °C. Todas tienen las etiquetas `line = envasado-1` y `machine_id = motor-01`.

**Estado:** Ejecutada. **Cumple.** Falta la captura del Data Explorer, que debe tomar el grupo.

---

## Prueba 4: visualización

**Objetivo:** comprobar que Grafana muestra los datos almacenados en el dashboard, con sus umbrales.

**Procedimiento:**
1. Con el simulador encendido, abrir http://localhost:3000/d/ta3-motor01.
2. Revisar cada panel.

**Resultado esperado:**
- El dashboard carga solo, provisionado por archivo.
- Los paneles muestran la última temperatura, vibración, corriente y potencia, el estado "Normal" en verde y las gráficas en el tiempo.
- Las gráficas muestran líneas de umbral en 75 y 85 °C, 2.8 y 7.1 mm/s, y 44 y 50 A.
- Se actualiza cada 5 s.

**Resultado obtenido** (16/10/2026, 19:48). Se ejecutó, a través de la API de Grafana, la consulta de cada uno de los 15 paneles con datos. Todas devolvieron datos:
- Estado = 0 (Normal).
- Última temperatura 60.06 °C.
- Última vibración 1.738 mm/s.
- Última corriente 35.98 A.
- Última potencia 20.37 kW.
- Entre 40 y 41 puntos en cada gráfica de los últimos 5 min.

Además, en fases anteriores se vio el dashboard en el navegador con datos reales (paneles de temperatura y vibración). La fuente de datos responde "datasource is working".

Nota: en ese momento el panel de promedio, mínimo y máximo mostraba un máximo de 90.39 °C. Ese valor viene de una ejecución del escenario de sobrecalentamiento hecha entre las 19:27 y las 19:46, dentro de los 5 minutos consultados.

**Estado:** Ejecutada. **Cumple.** Falta la captura de pantalla del dashboard completo, que debe tomar el grupo. Es la evidencia visual principal.

---

## Prueba 5: umbral superado

**Objetivo:** comprobar que, cuando una variable supera su umbral, el sistema lo muestra en el dashboard (color, nivel y estado) y que la alerta de Grafana se dispara si la condición dura más de 30 s.

**Procedimiento:** ejecutar los escenarios de falla del simulador uno por uno y observar el dashboard y el panel "Alertas activas":

```bash
py node/simulador.py --escenario sobrecalentamiento
```

```bash
py node/simulador.py --escenario desgaste_rodamiento
```

```bash
py node/simulador.py --escenario sobrecarga
```

**Resultado esperado:**
- Al pasar el umbral de advertencia, el valor se pone naranja, el nivel de la variable pasa a "Advertencia" y el estado a "Atención".
- La alerta queda "Pendiente" y, si la condición dura más de 30 s, pasa a "Disparada".
- Con una variable en crítico, o dos en advertencia, el estado pasa a "Riesgo de falla" y se dispara también la alerta de riesgo.

**Resultado obtenido** (16/10/2026, 19:04 a 19:21; registro cada 15 s en `evidencias/fase6_registro_escenarios.txt`):

| Escenario | Qué ocurrió | Alertas |
|---|---|---|
| Sobrecarga | Corriente sobre 44 A a los 36 s de falla, estado Atención. Corriente sobre 50 A (crítico) a los 72 s, estado Riesgo de falla. La temperatura siguió con retraso y pasó 75 °C a los 2.9 min de falla | Corriente: pendiente y luego disparada unos 30 s después. Riesgo de falla: disparada. Temperatura: disparada |
| Desgaste de rodamiento | Vibración sobre 2.8 mm/s a los 59 s de falla; subió hasta unos 4 mm/s en 4 min. Estado Atención (una variable en advertencia) | Vibración: pendiente y luego disparada |
| Sobrecalentamiento | Temperatura sobre 75 °C a los 2.2 min de falla; llegó a 83 °C en la ventana de prueba. Estado Atención | Temperatura: pendiente y luego disparada |

En los tres casos, las variables que no estaban en falla siguieron en "Normal" y sus alertas quedaron inactivas.

En InfluxDB también hay datos de otra ejecución del sobrecalentamiento, entre las 19:27 y las 19:46, que llegó a unos 92 °C. Pasó el umbral crítico de 85 °C. Esa ejecución no quedó registrada por los scripts de verificación, así que se toma solo como dato observado.

**Estado:** Ejecutada. **Cumple.** Faltan las capturas del dashboard en "Atención" y en "Riesgo de falla", y de la lista de alertas disparadas, que debe tomar el grupo.

---

## Prueba 6: interrupción de comunicación

**Objetivo:** comprobar que, si el nodo deja de comunicarse sin avisar, el sistema lo detecta: el broker publica `offline` (Last Will), el dashboard muestra "Sin datos" y Grafana dispara la alerta de falta de datos.

**Procedimiento:**

```bash
py node/simulador.py --escenario corte --inicio-falla 30
```

Observar MQTTX (tópico `estado`) y el dashboard durante unos 90 s.

**Resultado esperado:**
- A los 30 s el nodo deja de publicar sin enviar aviso de desconexión.
- Unos 22 s después, al vencer el keepalive de 15 s x 1.5, EMQX publica `offline` con motivo `desconexion_inesperada`.
- A los 30 s sin datos, el estado pasa a "Sin datos" y se dispara la alerta "Motor-01: sin datos por más de 30 s".
- Las alertas de umbral no se disparan por falta de datos.

**Resultado obtenido** (16/10/2026, dos ejecuciones):

| Evento | Primera ejecución (19:19) | Segunda ejecución (19:22) |
|---|---|---|
| Última lectura publicada | 19:19:46 | 19:23:16 |
| EMQX publica `offline` (Last Will) | 19:20:09 (23 s después) | no medido |
| Panel de estado en "Sin datos" | no medido (falló el script de registro) | 19:23:47 (31 s después) |
| Alerta "sin datos" disparada | no medido | 19:23:58 (42 s después) |

La alerta se dispara entre 30 y 40 s después del corte, porque Grafana revisa las reglas cada 10 s. Las alertas de temperatura, vibración, corriente y riesgo siguieron inactivas.

También se probó la **reconexión automática** (Fase 2). Se apagó EMQX durante 12 s con el simulador encendido. El simulador guardó las lecturas en cola y, al volver el broker, se reconectó solo, publicó `online` y envió las lecturas pendientes.

**Estado:** Ejecutada. **Cumple.** Faltan las capturas de MQTTX mostrando el mensaje `offline` y de Grafana con "Sin datos" y la alerta disparada, que debe tomar el grupo.

---

## Limitaciones conocidas

- El nodo es un **simulador**. Para pasar a un sensor real habría que reemplazar `node/simulador.py` por un microcontrolador (por ejemplo, un ESP32 con sensores de temperatura, vibración y corriente) que publique en los mismos tópicos y con el mismo formato.
- Los tiempos de los escenarios están comprimidos para la demostración. En un motor real el calentamiento o el desgaste tardan horas o semanas.
- Las alertas se ven solo dentro de Grafana. No se configuró envío por correo ni mensajería.
- EMQX acepta conexiones sin usuario ni cifrado. Basta para un laboratorio local, pero en planta se debe activar autenticación y TLS.
- La pendiente de temperatura usa los últimos 5 minutos. Al cambiar de escenario muestra valores grandes durante unos 5 minutos, porque mezcla datos del escenario anterior.
