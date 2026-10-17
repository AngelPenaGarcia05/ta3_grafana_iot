"""
SIMULADOR del nodo IoT del motor-01 (línea envasado-1).

IMPORTANTE: este programa NO lee un sensor físico. Genera valores por software
que imitan el comportamiento de un motor eléctrico de 22 kW y los publica por
MQTT en el broker EMQX, igual que lo haría un nodo IoT real.

Variables publicadas:
  - Temperatura de carcasa (°C) cada 5 s
  - Vibración, velocidad RMS (mm/s) cada 1 s
  - Corriente (A) y potencia derivada (kW) cada 2 s
  - Estado del nodo (online / offline) retenido, con Last Will

Escenarios (--escenario):
  normal               Operación normal, todo dentro de rango.
  sobrecalentamiento   La temperatura sube hasta pasar 75 °C y luego 85 °C (falla de ventilación).
  desgaste_rodamiento  La vibración sube de forma gradual, con leve alza de temperatura y corriente.
  sobrecarga           La corriente sube y la temperatura la sigue con retraso.
  corte                Publica normal un rato y luego deja de publicar sin avisar.

Todos los escenarios empiezan en operación normal; la falla comienza a los
--inicio-falla segundos (por defecto 60).

Uso (desde la carpeta del proyecto):
    py node/simulador.py
    py node/simulador.py --escenario sobrecarga
    py node/simulador.py --escenario corte --inicio-falla 30
"""

import argparse
import json
import math
import os
import random
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

# Datos fijos del equipo monitoreado
MACHINE_ID = "motor-01"
LINE = "envasado-1"

# Tópicos MQTT
TOPICO_BASE = "fabrica/envasado1/motor01"
TOPICO_TEMPERATURA = f"{TOPICO_BASE}/temperatura"
TOPICO_VIBRACION = f"{TOPICO_BASE}/vibracion"
TOPICO_CONSUMO = f"{TOPICO_BASE}/consumo"
TOPICO_ESTADO = f"{TOPICO_BASE}/estado"

QOS = 1
KEEPALIVE_S = 15   # el broker da por caído al nodo tras 1.5 x keepalive sin noticias

# Frecuencia de publicación de cada variable (segundos)
INTERVALO_TEMPERATURA_S = 5
INTERVALO_VIBRACION_S = 1
INTERVALO_CONSUMO_S = 2

# Umbrales del caso (supuestos, a validar con el fabricante): (advertencia, crítico)
UMBRALES = {
    "temperatura": (75.0, 85.0),   # °C
    "vibracion": (2.8, 7.1),       # mm/s RMS
    "corriente": (44.0, 50.0),     # A
}

# Datos eléctricos supuestos para calcular la potencia a partir de la corriente
# (motor trifásico): P [kW] = raíz(3) x V x I x fp / 1000
TENSION_V = 380.0
FACTOR_POTENCIA = 0.86

ESCENARIOS = {
    "normal": "Operación normal, todas las variables dentro de rango",
    "sobrecalentamiento": "Falla de ventilación: la temperatura sube hasta superar 75 °C y luego 85 °C",
    "desgaste_rodamiento": "Desgaste de rodamiento: la vibración sube gradualmente, con leve alza de temperatura y corriente",
    "sobrecarga": "Sobrecarga mecánica: la corriente sube y la temperatura la sigue con retraso",
    "corte": "Corte de comunicación: el nodo deja de publicar sin avisar",
}


def cargar_env(ruta):
    """Lee el archivo .env (formato CLAVE=valor) sin librerías extra."""
    valores = {}
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                clave, valor = linea.split("=", 1)
                valores[clave.strip()] = valor.strip()
    return valores


def ahora_utc():
    """Fecha y hora actual en UTC, formato ISO 8601 (ejemplo: 2026-10-16T07:10:00.123Z)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class ModeloSenoidal:
    """
    Señal creíble para una variable del motor:
    base + oscilación senoidal suave (cambios de carga de la cinta)
    + deriva lenta que vuelve a cero + ruido pequeño del sensor.
    El escenario de falla suma un valor "extra" sobre esta base.
    """

    def __init__(self, base, amplitud, periodo_s, ruido, deriva, decimales, minimo=0.0):
        self.base = base
        self.amplitud = amplitud
        self.periodo_s = periodo_s
        self.ruido = ruido
        self.paso_deriva = deriva
        self.decimales = decimales
        self.minimo = minimo
        self.deriva = 0.0
        self.inicio = time.monotonic()

    def leer(self, extra=0.0, ruido_extra=0.0):
        t = time.monotonic() - self.inicio
        oscilacion = self.amplitud * math.sin(2 * math.pi * t / self.periodo_s)
        self.deriva = 0.95 * self.deriva + random.gauss(0, self.paso_deriva)
        valor = self.base + oscilacion + self.deriva + extra + random.gauss(0, self.ruido + ruido_extra)
        return round(max(self.minimo, valor), self.decimales)


def potencia_kw(corriente_a):
    """Potencia activa trifásica estimada a partir de la corriente."""
    return round(math.sqrt(3) * TENSION_V * corriente_a * FACTOR_POTENCIA / 1000, 2)


def clasificar(variable, valor):
    advertencia, critico = UMBRALES[variable]
    if valor > critico:
        return "CRITICO"
    if valor > advertencia:
        return "ADVERTENCIA"
    return "normal"


def mensaje_estado(estado, motivo):
    return json.dumps({
        "machine_id": MACHINE_ID,
        "line": LINE,
        "status": estado,
        "motivo": motivo,
        "timestamp": ahora_utc(),
        "simulado": True,
    })


def al_conectar(cliente, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"[MQTT] No se pudo conectar: {reason_code}")
        return
    # Mensaje retenido: quien se suscriba después verá el último estado conocido
    cliente.publish(TOPICO_ESTADO, mensaje_estado("online", "nodo_conectado"), qos=QOS, retain=True)
    print(f"[MQTT] Conectado al broker {userdata['host']}:{userdata['port']}. "
          f"Estado publicado: online (retenido) en {TOPICO_ESTADO}")
    userdata["conectado"].set()


def al_desconectar(cliente, userdata, flags, reason_code, properties):
    if userdata.get("cerrando"):
        return
    print(f"[MQTT] Conexión perdida ({reason_code}). Reintentando automáticamente...")


class Nodo:
    """Genera y publica las lecturas de las tres variables del motor."""

    def __init__(self, cliente, escenario, inicio_falla_s):
        self.cliente = cliente
        self.escenario = escenario
        self.inicio_falla_s = inicio_falla_s
        self.t0 = time.monotonic()
        self.falla_anunciada = False
        # Retraso térmico de la sobrecarga (la carcasa se calienta despacio)
        self.calor_acumulado = 0.0
        self.ultima_temp_t = self.t0
        # Operación normal: valores dentro de los rangos normales del caso
        self.temperatura = ModeloSenoidal(base=60.0, amplitud=3.0, periodo_s=1800, ruido=0.15,
                                          deriva=0.08, decimales=2)
        self.vibracion = ModeloSenoidal(base=1.6, amplitud=0.25, periodo_s=300, ruido=0.06,
                                        deriva=0.03, decimales=3)
        self.corriente = ModeloSenoidal(base=34.0, amplitud=2.5, periodo_s=600, ruido=0.3,
                                        deriva=0.2, decimales=2)

    def segundos_de_falla(self):
        """Segundos transcurridos desde que empezó la falla (0 si aún no empieza)."""
        s = time.monotonic() - self.t0 - self.inicio_falla_s
        if s > 0 and not self.falla_anunciada and self.escenario not in ("normal", "corte"):
            self.falla_anunciada = True
            print(f"\n[ESCENARIO] Comienza la falla simulada: {ESCENARIOS[self.escenario]}\n")
        return max(0.0, s)

    # Cada escenario suma un "extra" a la operación normal
    def extra_corriente(self):
        s = self.segundos_de_falla()
        if self.escenario == "sobrecarga":
            return 18.0 * (1 - math.exp(-s / 60))           # hasta unos 52 A
        if self.escenario == "desgaste_rodamiento":
            return 3.0 * min(1.0, s / 480)                  # leve alza por mayor fricción
        return 0.0

    def extra_vibracion(self):
        s = self.segundos_de_falla()
        if self.escenario == "desgaste_rodamiento":
            return 6.5 * min(1.0, s / 480)                  # sube gradual hasta unos 8 mm/s en 8 min
        return 0.0

    def extra_temperatura(self):
        s = self.segundos_de_falla()
        if self.escenario == "sobrecalentamiento":
            return 32.0 * (1 - math.exp(-s / 240))          # hasta unos 92 °C
        if self.escenario == "desgaste_rodamiento":
            return 8.0 * min(1.0, s / 480)                  # leve alza por fricción
        if self.escenario == "sobrecarga":
            # La temperatura persigue al exceso de corriente con una constante de tiempo de 3 min
            ahora = time.monotonic()
            objetivo = 1.6 * self.extra_corriente()         # 1.6 °C por cada amperio de exceso
            factor = 1 - math.exp(-(ahora - self.ultima_temp_t) / 180)
            self.calor_acumulado += (objetivo - self.calor_acumulado) * factor
            self.ultima_temp_t = ahora
            return self.calor_acumulado
        return 0.0

    def publicar(self, topico, campos):
        carga = {"machine_id": MACHINE_ID, "line": LINE, **campos,
                 "timestamp": ahora_utc(), "simulado": True}
        resultado = self.cliente.publish(topico, json.dumps(carga), qos=QOS)
        envio = "enviado" if resultado.rc == mqtt.MQTT_ERR_SUCCESS else "en cola (sin conexión)"
        return carga["timestamp"], envio

    def temperatura_tick(self):
        valor = self.temperatura.leer(extra=self.extra_temperatura())
        ts, envio = self.publicar(TOPICO_TEMPERATURA, {"temperature_c": valor})
        print(f"{ts}  temperatura = {valor:6.2f} °C              "
              f"[{clasificar('temperatura', valor)}]  {envio}")

    def vibracion_tick(self):
        extra = self.extra_vibracion()
        valor = self.vibracion.leer(extra=extra, ruido_extra=0.05 * extra)
        ts, envio = self.publicar(TOPICO_VIBRACION, {"vibration_mms": valor})
        print(f"{ts}  vibración   = {valor:6.3f} mm/s            "
              f"[{clasificar('vibracion', valor)}]  {envio}")

    def consumo_tick(self):
        corriente = self.corriente.leer(extra=self.extra_corriente())
        potencia = potencia_kw(corriente)
        ts, envio = self.publicar(TOPICO_CONSUMO, {"current_a": corriente, "power_kw": potencia})
        print(f"{ts}  corriente   = {corriente:6.2f} A  potencia = {potencia:5.2f} kW  "
              f"[{clasificar('corriente', corriente)}]  {envio}")


def simular_corte(cliente):
    """
    Simula que el nodo se queda sin comunicación (por ejemplo, cable o WiFi caído):
    deja de publicar y de responder al broker, SIN enviar el aviso de desconexión.
    El broker lo detecta al vencer el keepalive y publica el Last Will (offline).
    """
    print("\n[ESCENARIO] CORTE DE COMUNICACIÓN SIMULADO: el nodo deja de publicar sin avisar.")
    print(f"[ESCENARIO] El broker debería publicar el estado offline (Last Will) en unos "
          f"{int(KEEPALIVE_S * 1.5)} s. Grafana debería marcar 'sin datos' a los 30 s.")
    print("[ESCENARIO] Presione Ctrl+C para cerrar el programa.\n")
    cliente.loop_stop()   # se detiene la red sin enviar DISCONNECT
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[SIMULADOR] Fin (no se publica 'detenido_por_usuario' porque el nodo ya estaba caído).")
        os._exit(0)


def main():
    # Evita errores con tildes y el símbolo de grados en la consola de Windows
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    raiz = Path(__file__).resolve().parent.parent
    env = cargar_env(raiz / ".env")

    parser = argparse.ArgumentParser(description="SIMULADOR del nodo IoT del motor-01.")
    parser.add_argument("--escenario", choices=list(ESCENARIOS), default="normal",
                        help="Escenario a simular (por defecto: normal)")
    parser.add_argument("--inicio-falla", type=int, default=60,
                        help="Segundos de operación normal antes de que empiece la falla (por defecto: 60)")
    parser.add_argument("--host", default=env.get("MQTT_HOST", "localhost"), help="Dirección del broker MQTT")
    parser.add_argument("--port", type=int, default=int(env.get("MQTT_PORT", "1883")), help="Puerto del broker MQTT")
    args = parser.parse_args()

    print("=" * 78)
    print(" SIMULADOR DE NODO IoT (no es un sensor físico)")
    print(f" Equipo: {MACHINE_ID} | Línea: {LINE} | Broker: {args.host}:{args.port}")
    print(f" Temperatura cada {INTERVALO_TEMPERATURA_S} s | Vibración cada {INTERVALO_VIBRACION_S} s | "
          f"Corriente y potencia cada {INTERVALO_CONSUMO_S} s")
    print(f" Potencia calculada con {TENSION_V:.0f} V trifásico y factor de potencia {FACTOR_POTENCIA}")
    print(f" Escenario: {args.escenario} ({ESCENARIOS[args.escenario]})")
    if args.escenario != "normal":
        print(f" La falla comienza a los {args.inicio_falla} s de operación normal")
    print(" Para detenerlo presione Ctrl+C")
    print("=" * 78)

    datos_cliente = {"host": args.host, "port": args.port, "cerrando": False,
                     "conectado": threading.Event()}
    cliente = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"simulador-{MACHINE_ID}",
        clean_session=True,
        userdata=datos_cliente,
    )
    cliente.on_connect = al_conectar
    cliente.on_disconnect = al_desconectar

    # Last Will: si el nodo se cae sin avisar, el broker publica "offline" por él
    cliente.will_set(
        TOPICO_ESTADO,
        json.dumps({"machine_id": MACHINE_ID, "line": LINE, "status": "offline",
                    "motivo": "desconexion_inesperada", "simulado": True}),
        qos=QOS,
        retain=True,
    )
    # Reconexión automática: espera entre 1 y 30 segundos entre intentos
    cliente.reconnect_delay_set(min_delay=1, max_delay=30)

    # Primer intento de conexión; si el broker no está, sigue intentando
    while True:
        try:
            cliente.connect(args.host, args.port, keepalive=KEEPALIVE_S)
            break
        except OSError as error:
            print(f"[MQTT] Broker no disponible ({error}). Nuevo intento en 5 s...")
            time.sleep(5)

    cliente.loop_start()
    # Espera la confirmación del broker antes de empezar a publicar lecturas
    datos_cliente["conectado"].wait(timeout=10)

    nodo = Nodo(cliente, args.escenario, args.inicio_falla)
    # Calendario: cada variable tiene su propio intervalo de publicación
    tareas = [
        [INTERVALO_VIBRACION_S, nodo.vibracion_tick],
        [INTERVALO_CONSUMO_S, nodo.consumo_tick],
        [INTERVALO_TEMPERATURA_S, nodo.temperatura_tick],
    ]
    inicio = time.monotonic()
    proximas = [inicio for _ in tareas]

    try:
        while True:
            ahora = time.monotonic()
            if args.escenario == "corte" and ahora - inicio >= args.inicio_falla:
                simular_corte(cliente)
            for i, (intervalo, funcion) in enumerate(tareas):
                if ahora >= proximas[i]:
                    funcion()
                    proximas[i] += intervalo
                    # Si el programa se atrasó mucho, no intenta recuperar lecturas perdidas
                    if proximas[i] < ahora:
                        proximas[i] = ahora + intervalo
            time.sleep(max(0.0, min(proximas) - time.monotonic()))
    except KeyboardInterrupt:
        print("\n[SIMULADOR] Detenido por el usuario. Publicando estado offline...")
        datos_cliente["cerrando"] = True
        info = cliente.publish(TOPICO_ESTADO, mensaje_estado("offline", "detenido_por_usuario"), qos=QOS, retain=True)
        info.wait_for_publish(timeout=3)
        cliente.disconnect()
        cliente.loop_stop()
        print("[SIMULADOR] Fin.")


if __name__ == "__main__":
    main()
