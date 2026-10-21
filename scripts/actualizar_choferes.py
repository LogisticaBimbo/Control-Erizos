"""
Trae de Driv.in los choferes que salen a reparto en La Tablada
y los guarda en Supabase (tabla choferes_reparto).

- Corrida automatica: consulta el dia de hoy.
- Corrida manual: se puede indicar un rango (desde / hasta) para
  cargar dias anteriores. Consulta de a un dia por vez.

Las claves NO estan en este archivo: se leen de los Secrets de GitHub.
  DRIVIN_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone, date

import requests

DRIVIN_BASE = "https://external.driv.in"
ENDPOINT = "api/external/v2/pods"
PREFIJO_CV = "14117"          # La Tablada
TZ_AR = timezone(timedelta(hours=-3))
MAX_DIAS = 120                # tope de seguridad por corrida

CAMPOS_CHOFER = ["driver_name", "driver", "driver_full_name", "courier_name", "chofer"]
CAMPOS_RUTA = ["vehicle_code", "route_code", "vehicle"]


def falta(nombre):
    print(f"ERROR: falta el secret {nombre} en GitHub.")
    sys.exit(1)


def texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, dict):
        for k in ("name", "full_name", "description", "code"):
            if valor.get(k):
                return str(valor[k]).strip()
        return " ".join(str(valor.get(k, "")) for k in ("first_name", "last_name")).strip()
    return str(valor).strip()


def primer_campo(reg, candidatos):
    for c in candidatos:
        if c in reg and texto(reg[c]):
            return texto(reg[c])
    return ""


def leer_fecha(valor, nombre):
    try:
        return datetime.strptime(valor.strip(), "%Y-%m-%d").date()
    except Exception:
        print(f"ERROR: la fecha '{nombre}' tiene que tener el formato AAAA-MM-DD (ej: 2026-09-01).")
        sys.exit(1)


def consultar_dia(dia, api_key):
    for intento in range(1, 4):
        try:
            resp = requests.get(
                f"{DRIVIN_BASE}/{ENDPOINT}",
                params={"start_date": dia, "end_date": dia},
                headers={"X-API-Key": api_key, "Accept": "application/json",
                         "Content-Type": "application/json"},
                timeout=300,
            )
            resp.raise_for_status()
            cuerpo = resp.json()
            datos = cuerpo.get("response", cuerpo) if isinstance(cuerpo, dict) else cuerpo
            return datos if isinstance(datos, list) else []
        except Exception as e:
            print(f"  Intento {intento} fallo para {dia}: {e}")
            time.sleep(10 * intento)
    print(f"  No se pudo consultar {dia}. Se sigue con el proximo dia.")
    return None


def armar_filas(dia, datos):
    por_ruta = {}
    for reg in datos:
        ruta_full = primer_campo(reg, CAMPOS_RUTA)
        if not ruta_full.startswith(PREFIJO_CV):
            continue
        ruta = ruta_full[len(PREFIJO_CV):].lstrip("0").zfill(3)
        chofer = primer_campo(reg, CAMPOS_CHOFER)
        if ruta in por_ruta and por_ruta[ruta]["chofer"]:
            continue
        por_ruta[ruta] = {
            "fecha": dia,
            "ruta": ruta,
            "ruta_completa": ruta_full,
            "chofer": chofer.title() if chofer else None,
            "escenario": texto(reg.get("description")) or None,
            "datos_origen": reg,
            "actualizado_at": datetime.now(timezone.utc).isoformat(),
        }
    return list(por_ruta.values())


def guardar(filas, sb_url, sb_key):
    r = requests.post(
        f"{sb_url}/rest/v1/choferes_reparto?on_conflict=fecha,ruta",
        headers={
            "apikey": sb_key,
            "Authorization": f"Bearer {sb_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
        data=json.dumps(filas, default=str),
        timeout=120,
    )
    if r.status_code >= 300:
        print(f"  Error al guardar en Supabase: HTTP {r.status_code} {r.text}")
        return False
    return True


def main():
    api_key = os.environ.get("DRIVIN_API_KEY") or falta("DRIVIN_API_KEY")
    sb_url = (os.environ.get("SUPABASE_URL") or falta("SUPABASE_URL")).rstrip("/")
    sb_key = os.environ.get("SUPABASE_SERVICE_KEY") or falta("SUPABASE_SERVICE_KEY")

    hoy = datetime.now(TZ_AR).date()
    desde_txt = (os.environ.get("FECHA_DESDE") or "").strip()
    hasta_txt = (os.environ.get("FECHA_HASTA") or "").strip()

    desde = leer_fecha(desde_txt, "desde") if desde_txt else hoy
    hasta = leer_fecha(hasta_txt, "hasta") if hasta_txt else (desde if desde_txt else hoy)
    if hasta < desde:
        desde, hasta = hasta, desde
    if hasta > hoy:
        hasta = hoy
    total = (hasta - desde).days + 1
    if total > MAX_DIAS:
        print(f"ERROR: el rango tiene {total} dias. El maximo por corrida es {MAX_DIAS}.")
        sys.exit(1)

    print(f"Rango a cargar: {desde} a {hasta} ({total} dia/s)")
    resumen = []
    errores = 0
    dia = desde
    while dia <= hasta:
        iso = dia.isoformat()
        print(f"\n== {iso} ==")
        datos = consultar_dia(iso, api_key)
        if datos is None:
            errores += 1
            resumen.append((iso, "ERROR"))
        else:
            filas = armar_filas(iso, datos)
            print(f"  Registros Driv.in: {len(datos)} | Rutas La Tablada: {len(filas)}")
            if filas:
                ok = guardar(filas, sb_url, sb_key)
                if not ok:
                    errores += 1
                resumen.append((iso, len(filas) if ok else "ERROR"))
            else:
                resumen.append((iso, 0))
        dia += timedelta(days=1)

    print("\n===== RESUMEN =====")
    for f, c in resumen:
        print(f"  {f}: {c} ruta/s")
    if errores:
        print(f"Termino con {errores} dia/s con error. Podes volver a correrlos.")
        sys.exit(1)
    print("Listo.")


if __name__ == "__main__":
    main()
