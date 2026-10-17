# TA3: Monitoreo IoT para mantenimiento predictivo (Grupo 4, Manufactura)

Curso: Herramientas de Desarrollo Profesional TIC (UTP).

> **Aviso importante:** el nodo IoT de este proyecto es un **SIMULADOR** escrito en Python. No hay un sensor físico conectado. Los valores se generan por software para representar el comportamiento de un motor real. Los umbrales son supuestos del caso y deben validarse con el fabricante en una implementación real.

## Caso

Una empresa manufacturera quiere mantenimiento predictivo básico. Se monitorea el motor eléctrico de 22 kW de la cinta transportadora de la línea de envasado 1 (`machine_id` = `motor-01`, `line` = `envasado-1`) para detectar a tiempo el sobrecalentamiento, el desgaste de rodamientos y la sobrecarga.

| Variable | Frecuencia | Normal | Advertencia | Crítico |
|---|---|---|---|---|
| Temperatura de carcasa (°C) | 5 s | 45 a 70 | > 75 | > 85 |
| Vibración, velocidad RMS (mm/s) | 1 s | hasta 2.8 | > 2.8 | > 7.1 |
| Corriente (A), con potencia en kW derivada | 2 s | 28 a 40 | > 44 | > 50 |

Estado de la máquina:

- **Normal:** ninguna variable en advertencia.
- **Atención:** una variable en advertencia.
- **Riesgo de falla:** dos o más variables en advertencia, o cualquiera en crítico.

## Arquitectura

```
                         MQTT (QoS 1, JSON)
Simulador Python  ------------------------------>  EMQX (broker)  ---> Telegraf ---> InfluxDB 2 ---> Grafana
(node/simulador.py)                                     |            (mqtt_consumer)  (bucket planta)  (dashboard y alertas)
                                                        v
                                               MQTTX (cliente de verificación)
```

El simulador corre en la laptop con Python. EMQX, Telegraf, InfluxDB y Grafana corren en Docker Compose, con versiones fijas.

| Servicio | Imagen | Dirección |
|---|---|---|
| EMQX (broker MQTT) | `emqx/emqx:5.8.6` | MQTT `localhost:1883`, WebSocket `8083`, panel http://localhost:18083 |
| InfluxDB | `influxdb:2.7.11` | http://localhost:8086 |
| Telegraf | `telegraf:1.34.4` | interno, sin puerto |
| Grafana | `grafana/grafana:11.6.1` | http://localhost:3000 |

## Requisitos

- Windows con **Docker Desktop** instalado.
- **Python 3** (probado con 3.13). En Windows se usa con el comando `py`.
- **MQTTX** (gratuito) para ver los mensajes MQTT. Se descarga de https://mqttx.app o se instala con `winget install EMQ.MQTTX`.

---

## Instrucciones de arranque

Todos los comandos se ejecutan en una terminal abierta en la carpeta del proyecto.

### La primera vez

1. **Abrir Docker Desktop** y esperar a que diga que está funcionando ("Engine running").

2. **Preparar las credenciales.** Si no existe el archivo `.env`, copiar la plantilla:

   ```bash
   copy .env.example .env
   ```

   Luego abrir `.env` y reemplazar los valores `cambiar_...` por claves propias. El token de InfluxDB debe ser un texto largo y aleatorio.

3. **Encender los servicios** (la primera vez descarga las imágenes y tarda unos minutos):

   ```bash
   docker compose up -d
   ```

4. **Comprobar que están encendidos:**

   ```bash
   docker compose ps
   ```

   Deben aparecer `ta3-emqx`, `ta3-influxdb`, `ta3-telegraf` y `ta3-grafana` con estado "Up". EMQX e InfluxDB además deben decir "(healthy)".

5. **Cambiar la clave del panel de EMQX.** Entrar a http://localhost:18083 con usuario `admin` y clave `public`, que es la de fábrica. EMQX pide cambiarla; poner la de `EMQX_DASHBOARD_PASSWORD` del `.env`. Este paso es manual porque EMQX no toma la clave desde el `.env`.

6. **Instalar la librería MQTT del simulador:**

   ```bash
   py -m pip install -r node/requirements.txt
   ```

### Cada vez que se use

1. Abrir Docker Desktop. Los servicios se encienden solos porque tienen `restart: unless-stopped`. Si no se encienden, ejecutar `docker compose up -d`.
2. Encender el simulador y dejar la terminal abierta:

   ```bash
   py node/simulador.py
   ```

3. Abrir el dashboard: http://localhost:3000/d/ta3-motor01 (usuario y clave de Grafana en `.env`).

Para detener el simulador, presionar **Ctrl+C** en su terminal. Así publica el estado `offline` antes de cerrarse.

### Apagar los servicios

```bash
docker compose stop
```

Los datos se conservan en volúmenes de Docker. Para borrar **todo** (datos de InfluxDB, configuración de Grafana y la clave de EMQX) y empezar de cero:

```bash
docker compose down -v
```

Después de borrar todo hay que repetir el paso 5 de "La primera vez", porque la clave de EMQX vuelve a `public`.

---

## Verificación rápida

| Qué verificar | Cómo | Qué se debe ver |
|---|---|---|
| Servicios | `docker compose ps` | 4 contenedores "Up" |
| Simulador | consola de `py node/simulador.py` | Aviso "SIMULADOR", lecturas con `[normal]` y `enviado` |
| Mensajes MQTT | MQTTX: conexión a `localhost:1883`, suscripción a `fabrica/envasado1/motor01/#` con QoS 1 | Mensajes JSON en los 4 tópicos |
| Almacenamiento | InfluxDB, Data Explorer, Script Editor, consulta Flux (ver abajo) | Una lectura de temperatura cada 5 s |
| Visualización | http://localhost:3000/d/ta3-motor01 | Estado "Normal" en verde y gráficas que avanzan |

El detalle de las 6 pruebas y sus resultados está en [docs/pruebas.md](docs/pruebas.md).

---

## Simulador del nodo IoT

`node/simulador.py` genera valores creíbles: un valor base, una oscilación senoidal suave, una deriva lenta y un ruido pequeño. Los publica por MQTT con QoS 1:

| Variable | Tópico | Campos | Frecuencia |
|---|---|---|---|
| Temperatura de carcasa | `fabrica/envasado1/motor01/temperatura` | `temperature_c` (°C) | 5 s |
| Vibración (velocidad RMS) | `fabrica/envasado1/motor01/vibracion` | `vibration_mms` (mm/s) | 1 s |
| Corriente y potencia | `fabrica/envasado1/motor01/consumo` | `current_a` (A), `power_kw` (kW) | 2 s |
| Estado del nodo | `fabrica/envasado1/motor01/estado` | `status` (`online` / `offline`), retenido, con Last Will | al conectar o desconectar |

Todos los mensajes llevan `machine_id`, `line`, `timestamp` (UTC, ISO 8601) y `simulado: true`. Ejemplo:

```json
{"machine_id": "motor-01", "line": "envasado-1", "temperature_c": 59.88, "timestamp": "2026-10-16T18:14:21.097Z", "simulado": true}
```

La potencia se calcula con la fórmula trifásica P = raíz(3) x 380 V x I x 0.86 / 1000. La tensión de 380 V y el factor de potencia 0.86 son supuestos del caso.

**Robustez de la comunicación:**
- **Reconexión automática:** si se cae el broker, reintenta cada 1 a 30 s y guarda en cola las lecturas pendientes.
- **Last Will:** si el nodo se cae sin avisar, EMQX publica `offline` en su nombre.

### Escenarios de falla

Se elige con `--escenario`. Todos empiezan en operación normal y la falla comienza a los `--inicio-falla` segundos (por defecto 60).

| Escenario | Qué simula | Qué se espera ver |
|---|---|---|
| `normal` | Operación normal | Todo en verde, estado Normal |
| `sobrecalentamiento` | Falla de ventilación | La temperatura sube hasta unos 92 °C: pasa 75 °C a los 2 a 2.5 min de iniciada la falla y 85 °C a los 6 a 7 min |
| `desgaste_rodamiento` | Rodamiento gastado | La vibración sube de forma gradual hasta unos 8 mm/s en 8 min (pasa 2.8 mm/s en 1 a 1.5 min), con alza leve de temperatura (+8 °C) y corriente (+3 A) |
| `sobrecarga` | Sobrecarga mecánica de la cinta | La corriente sube hasta unos 52 A (pasa 44 A en menos de 1 min y 50 A en 1 a 1.5 min); la temperatura la sigue con retraso (constante térmica de 3 min) |
| `corte` | Corte de comunicación del nodo | Publica normal y luego deja de publicar sin avisar; el broker publica `offline` (Last Will) y Grafana marca "Sin datos" |

Ejemplos:

```bash
py node/simulador.py --escenario sobrecalentamiento
```

```bash
py node/simulador.py --escenario corte --inicio-falla 30
```

Ver todas las opciones:

```bash
py node/simulador.py --help
```

Los tiempos están comprimidos para poder demostrarlos en clase. En un motor real, el calentamiento o el desgaste tardan horas o semanas.

**Importante:** debe haber un solo simulador encendido a la vez. Todos usan el mismo identificador MQTT, así que un segundo simulador desconecta al primero.

---

## Almacenamiento en InfluxDB

Telegraf (`telegraf/telegraf.conf`) se suscribe a los tres tópicos de medición y guarda cada lectura en InfluxDB:

| Dato | Valor |
|---|---|
| Organización | `fabrica` |
| Bucket | `planta` (retención 30 días) |
| Measurements y campos | `temperatura_motor` (`temperature_c`), `vibracion_motor` (`vibration_mms`), `consumo_motor` (`current_a`, `power_kw`) |
| Etiquetas (tags) | `machine_id`, `line` |
| Hora del punto | la hora UTC en que el simulador tomó la lectura |

Telegraf usa sesión MQTT persistente. Si se reinicia, EMQX le guarda los mensajes que llegaron mientras tanto.

Consulta Flux de ejemplo (últimos 15 minutos de temperatura), para pegar en el Script Editor del Data Explorer:

```
from(bucket: "planta")
  |> range(start: -15m)
  |> filter(fn: (r) => r._measurement == "temperatura_motor")
  |> filter(fn: (r) => r.machine_id == "motor-01")
  |> filter(fn: (r) => r._field == "temperature_c")
```

---

## Visualización en Grafana

Grafana crea sola, al arrancar, la conexión con InfluxDB, el dashboard y las alertas, desde los archivos de `grafana/provisioning/` y `grafana/dashboards/`. No hay que configurar nada a mano.

Dashboard: http://localhost:3000/d/ta3-motor01 (carpeta "TA3 Mantenimiento predictivo"). Se actualiza cada 5 s y muestra por defecto los últimos 15 minutos.

| Sección | Paneles |
|---|---|
| Aviso | Equipo, origen SIMULADOR y umbrales supuestos |
| Estado de la máquina y tendencias | Estado (Normal, Atención, Riesgo de falla o "Sin datos" si no llega nada en 30 s); nivel de cada variable; pendiente de temperatura en °C/min (regresión lineal de los últimos 5 min); vibración promedio del último minuto; lista de alertas activas |
| Temperatura de carcasa | Última lectura con colores, aguja con marcas en 75 y 85 °C, promedio, mínimo y máximo del periodo, y gráfica con líneas de umbral |
| Vibración | Última lectura, aguja con marcas en 2.8 y 7.1 mm/s, y gráfica con promedio móvil de 1 min (línea discontinua) |
| Consumo eléctrico | Última corriente (umbrales 44 y 50 A), última potencia, y gráficas de corriente y potencia |

El estado se calcula en Grafana con una consulta Flux: toma la última lectura de cada variable de los últimos 30 s y la compara con sus umbrales. El estado no se guarda en InfluxDB.

El dashboard está definido en `grafana/dashboards/motor01.json` y no se puede modificar desde la pantalla de Grafana. Para cambiarlo hay que editar el archivo; Grafana lo vuelve a leer en unos 30 s.

### Alertas

Definidas en `grafana/provisioning/alerting/reglas_motor01.yaml`. Se evalúan cada 10 s:

| Alerta | Condición | Severidad |
|---|---|---|
| Temperatura de carcasa sobre 75 °C | Temperatura > 75 °C durante más de 30 s | advertencia |
| Vibración sobre 2.8 mm/s | Vibración > 2.8 mm/s durante más de 30 s | advertencia |
| Corriente sobre 44 A | Corriente > 44 A durante más de 30 s | advertencia |
| Estado RIESGO DE FALLA | Estado combinado en Riesgo de falla durante más de 30 s | crítica |
| Sin datos por más de 30 s | Ninguna lectura del motor-01 en los últimos 30 s | crítica |

Mientras la condición se cumple pero todavía no pasan 30 s, la alerta aparece como "Pendiente". Después pasa a "Disparada".

Las alertas se ven en el panel "Alertas activas" y en el menú de Grafana **Alerting > Alert rules**. Cuando el simulador está apagado, la alerta "Sin datos" queda disparada; es lo esperado.

---

## Estructura del proyecto

| Archivo o carpeta | Para qué sirve |
|---|---|
| `docker-compose.yml` | Define los 4 servicios, sus puertos y volúmenes |
| `.env` | Credenciales reales (no se sube a git) |
| `.env.example` | Plantilla de credenciales |
| `.gitignore` | Archivos que git no debe subir |
| `node/simulador.py` | Simulador del nodo IoT |
| `node/requirements.txt` | Librería que necesita el simulador (`paho-mqtt==2.1.0`) |
| `telegraf/telegraf.conf` | Lectura MQTT y escritura en InfluxDB |
| `grafana/provisioning/datasources/` | Conexión de Grafana con InfluxDB |
| `grafana/provisioning/dashboards/` | Indica a Grafana dónde están los dashboards |
| `grafana/provisioning/alerting/` | Reglas de alerta |
| `grafana/dashboards/motor01.json` | Dashboard del motor-01 |
| `docs/pruebas.md` | Las 6 pruebas mínimas y sus resultados |
| `docs/evidencias/` | Registros de las pruebas y capturas de pantalla |

## Credenciales

Las claves reales están en `.env`, que no se sube a git; `.env.example` es la plantilla.

Las claves de InfluxDB y Grafana se aplican solo la primera vez que se crean sus volúmenes. Si se cambian después en `.env`, hay que borrar todo con `docker compose down -v` y volver a arrancar.

## Solución de problemas

| Problema | Qué hacer |
|---|---|
| `docker compose` dice que no encuentra el motor de Docker | Abrir Docker Desktop y esperar a que diga "Engine running" |
| `python` abre la Microsoft Store o no funciona | Usar `py` en lugar de `python` |
| `ModuleNotFoundError: No module named 'paho'` | Ejecutar `py -m pip install -r node/requirements.txt` |
| El simulador dice "Broker no disponible" | Revisar con `docker compose ps` que `ta3-emqx` esté encendido. El simulador reintenta solo |
| El simulador se desconecta y reconecta seguido | Hay dos simuladores encendidos. Cerrar uno |
| El dashboard muestra "Sin datos" | El simulador está apagado o lleva más de 30 s sin publicar. Encenderlo y esperar unos segundos |
| Un puerto (1883, 3000, 8086 o 18083) está ocupado | Cerrar el programa que lo usa o cambiar el puerto en `docker-compose.yml` |

## Limitaciones

- El nodo es un **simulador**. Para pasar a un equipo real habría que reemplazarlo por un microcontrolador con sensores (por ejemplo, un ESP32 con sensor de temperatura, acelerómetro y transformador de corriente) que publique en los mismos tópicos y con el mismo formato JSON.
- Los umbrales, la tensión de 380 V y el factor de potencia son supuestos del caso.
- Los tiempos de los escenarios están comprimidos para la demostración.
- Las alertas no envían correo ni mensajes, porque no hay servidor de correo en el laboratorio. En una planta se agregaría un punto de contacto (correo, Telegram, Teams, etc.).
- EMQX acepta conexiones sin usuario ni cifrado. Basta para un laboratorio local, pero en planta se debe activar autenticación y TLS.
- Todo corre en una sola laptop, sin alta disponibilidad ni respaldos.

## Estado del proyecto

| Fase | Contenido | Estado |
|---|---|---|
| 0 | Estructura del proyecto y verificación de herramientas | Completada |
| 1 | Servicios en Docker Compose | Completada |
| 2 | Simulador de temperatura y verificación con MQTTX | Completada |
| 3 | Telegraf hacia InfluxDB | Completada |
| 4 | Dashboard de Grafana (temperatura y umbrales) | Completada |
| 5 | Vibración y consumo | Completada |
| 6 | Estado combinado, tendencias, escenarios y alertas | Completada |
| 7 | Documento de pruebas y README final | Completada |

Las capturas de pantalla (MQTTX, Data Explorer, dashboard y alertas) las debe tomar el grupo y guardar en `docs/evidencias/`. Ver [docs/pruebas.md](docs/pruebas.md).
