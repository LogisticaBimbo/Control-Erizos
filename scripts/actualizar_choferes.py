"""
Trae de Driv.in los choferes que salen a reparto HOY en La Tablada
y los guarda en Supabase (tabla choferes_reparto).

Las claves NO estan en este archivo: se leen de los Secrets de GitHub.
  DRIVIN_API_KEY        -> clave de Driv.in
  SUPABASE_URL          -> url del proyecto Supabase
  SUPABASE_SERVICE_KEY  -> clave service_role de Supabase
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

DRIVIN_BASE = "https://external.driv.in"
ENDPOINT = "api/external/v2/pods"
PREFIJO_CV = "14117"          # La Tablada
TZ_AR = timezone(timedelta(hours=-3))

# Posibles nombres del campo chofer (se confirma en la primera corrida)
CAMPOS_CHOFER = [
    "driver_name", "driver", "driver_full_name", "courier_name",
    "courier", "user_name", "conductor", "chofer",
]
CAMPOS_RUTA = ["vehicle_code", "route_code", "vehicle"]


def falta(nombre):
    print(f"ERROR: falta el secret {nombre} en GitHub.")
    sys.exit(1)


def texto(valor):
    """Convierte un campo a texto, aunque venga como objeto anidado."""
    if valor is None:
        return ""
    if isinstance(valor, dict):
        for k in ("name", "full_name", "description", "code"):
            if valor.get(k):
                return str(valor[k]).strip()
        nombre = " ".join(str(valor.get(k, "")) for k in ("first_name", "last_name")).strip()
        return nombre
    return str(valor).strip()


def primer_campo(reg, candidatos):
    for c in candidatos:
        if c in reg and texto(reg[c]):
            return c, texto(reg[c])
    return None, ""


def main():
    api_key = os.environ.get("DRIVIN_API_KEY") or falta("DRIVIN_API_KEY")
    sb_url = (os.environ.get("SUPABASE_URL") or falta("SUPABASE_URL")).rstrip("/")
    sb_key = os.environ.get("SUPABASE_SERVICE_KEY") or falta("SUPABASE_SERVICE_KEY")

    hoy = os.environ.get("FECHA_MANUAL") or datetime.now(TZ_AR).strftime("%Y-%m-%d")
    print(f"Consultando Driv.in para el dia {hoy}...")

    resp = requests.get(
        f"{DRIVIN_BASE}/{ENDPOINT}",
        params={"start_date": hoy, "end_date": hoy},
        headers={"X-API-Key": api_key, "Accept": "application/json",
                 "Content-Type": "application/json"},
        timeout=300,
    )
    print(f"Respuesta Driv.in: HTTP {resp.status_code}")
    resp.raise_for_status()
    cuerpo = resp.json()
    datos = cuerpo.get("response", cuerpo) if isinstance(cuerpo, dict) else cuerpo
    if not isinstance(datos, list):
        datos = []
    print(f"Registros recibidos: {len(datos)}")

    if datos:
        # Muestra la estructura (sin datos sensibles) para confirmar nombres de campos
        print("Campos disponibles en Driv.in:", sorted(datos[0].keys()))

    por_ruta = {}
    sin_chofer = 0
    for reg in datos:
        _, ruta_full = primer_campo(reg, CAMPOS_RUTA)
        if not ruta_full.startswith(PREFIJO_CV):
            continue
        ruta = ruta_full[len(PREFIJO_CV):].lstrip("0").zfill(3)
        campo_chofer, chofer = primer_campo(reg, CAMPOS_CHOFER)
        if not chofer:
            sin_chofer += 1
        if ruta in por_ruta and por_ruta[ruta]["chofer"]:
            continue  # una fila por ruta y dia
        por_ruta[ruta] = {
            "fecha": hoy,
            "ruta": ruta,
            "ruta_completa": ruta_full,
            "chofer": chofer.title() if chofer else None,
            "escenario": texto(reg.get("description")) or None,
            "datos_origen": reg,
            "actualizado_at": datetime.now(timezone.utc).isoformat(),
        }

    filas = list(por_ruta.values())
    print(f"Rutas de La Tablada encontradas: {len(filas)}")
    if sin_chofer:
        print(f"AVISO: {sin_chofer} registro(s) sin nombre de chofer. "
              f"Revisar 'Campos disponibles' arriba y avisar cual es el campo del chofer.")
    for f in sorted(filas, key=lambda x: x["ruta"]):
        print(f"  Ruta {f['ruta']}: {f['chofer'] or '(sin chofer)'}")

    if not filas:
        print("No hay rutas para guardar hoy. Fin.")
        return

    r = requests.post(
        f"{sb_url}/rest/v1/choferes_reparto?on_conflict=fecha,ruta",
        headers={
            "apikey": sb_key,
            "Authorization": f"Bearer {sb_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
        data=json.dumps(filas, default=str),
        timeout=60,
    )
    print(f"Guardado en Supabase: HTTP {r.status_code}")
    if r.status_code >= 300:
        print(r.text)
        sys.exit(1)
    print("Listo.")


if __name__ == "__main__":
    main()
