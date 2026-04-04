"""
SERVIDOR GESTIÓN DE CLIENTES — TRÁMITES MIGRATORIOS
FastAPI + almacenamiento JSON local

Trámites: Visa Americana, Pasaporte MX, Pasaporte USA,
          Permiso de Viaje, Ciudadanía, Residencia, Consulta

Deploy: Render.com
  Build:  pip install -r requirements_clientes.txt
  Start:  uvicorn servidor_clientes:app --host 0.0.0.0 --port $PORT
"""

import json, os, uuid
from datetime import datetime, timezone
from typing import Optional, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ── ARCHIVOS ────────────────────────────────────────────
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
HTML_FILE      = os.path.join(BASE_DIR, "clientes.html")
CLIENTES_FILE  = os.path.join(BASE_DIR, "clientes.json")
TRAMITES_FILE  = os.path.join(BASE_DIR, "tramites.json")

# ── AUTH ─────────────────────────────────────────────────
APP_PASSWORD = os.environ.get("APP_PASSWORD", "Tier2024*")

# ── ESTADO EN MEMORIA ────────────────────────────────────
clientes_db: dict = {}
tramites_db: dict = {}


# ── PERSISTENCIA ─────────────────────────────────────────
def cargar_datos():
    global clientes_db, tramites_db
    for path, store, name in [
        (CLIENTES_FILE, "clientes", "clientes"),
        (TRAMITES_FILE, "tramites", "trámites"),
    ]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if name == "clientes":
                    clientes_db = data
                else:
                    tramites_db = data
                print(f"[{name}] Cargados: {len(data)} registros")
            except Exception as e:
                print(f"[ERROR] Cargando {name}: {e}")


def guardar_clientes():
    with open(CLIENTES_FILE, "w", encoding="utf-8") as f:
        json.dump(clientes_db, f, ensure_ascii=False, indent=2, default=str)


def guardar_tramites():
    with open(TRAMITES_FILE, "w", encoding="utf-8") as f:
        json.dump(tramites_db, f, ensure_ascii=False, indent=2, default=str)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ── LIFESPAN ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    cargar_datos()
    yield


# ── APP ───────────────────────────────────────────────────
app = FastAPI(title="Gestión de Clientes", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


# ── AUTH DEPENDENCY ───────────────────────────────────────
def verificar_auth(x_password: Optional[str] = Header(None)):
    if x_password != APP_PASSWORD:
        raise HTTPException(status_code=401, detail="No autorizado")
    return True


# ── HTML ─────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def raiz():
    if os.path.exists(HTML_FILE):
        with open(HTML_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse("<h2>clientes.html no encontrado en el servidor</h2>", 404)


# ── STATUS ────────────────────────────────────────────────
@app.get("/status")
async def status():
    tramites_por_estado = {}
    for t in tramites_db.values():
        e = t.get("estado", "nuevo")
        tramites_por_estado[e] = tramites_por_estado.get(e, 0) + 1
    return {
        "clientes": len(clientes_db),
        "tramites": len(tramites_db),
        "tramites_por_estado": tramites_por_estado,
        "tramites_por_tipo": _contar_por_campo(tramites_db, "tipo"),
    }


def _contar_por_campo(db, campo):
    conteo = {}
    for item in db.values():
        v = item.get(campo, "otro")
        conteo[v] = conteo.get(v, 0) + 1
    return conteo


# ══════════════════════════════════════════════════════════
#  CLIENTES
# ══════════════════════════════════════════════════════════

@app.get("/clientes")
async def listar_clientes(
    q: Optional[str] = None,
    _: bool = Depends(verificar_auth)
):
    """Lista todos los clientes. q = búsqueda por nombre/teléfono/email."""
    clientes = list(clientes_db.values())
    # Filtrar eliminados
    clientes = [c for c in clientes if not c.get("eliminado")]
    if q:
        q_lower = q.lower()
        clientes = [
            c for c in clientes
            if q_lower in (c.get("nombre", "") + " " + c.get("ap_paterno", "") +
                           " " + c.get("ap_materno", "")).lower()
            or q_lower in c.get("telefono", "").lower()
            or q_lower in c.get("email", "").lower()
            or q_lower in c.get("curp", "").lower()
            or q_lower in str(c.get("id_secuencial", ""))
        ]
    # Ordenar por fecha de registro desc
    clientes.sort(key=lambda c: c.get("fecha_registro", ""), reverse=True)
    # Añadir conteo de trámites a cada cliente
    for c in clientes:
        cid = c["id"]
        t_cliente = [t for t in tramites_db.values()
                     if t.get("cliente_id") == cid and not t.get("eliminado")]
        c["_num_tramites"] = len(t_cliente)
        c["_tramite_activo"] = next(
            (t["tipo"] for t in t_cliente
             if t.get("estado") not in ("aprobado","entregado","rechazado","cancelado")),
            None
        )
    return clientes


@app.get("/clientes/{cliente_id}")
async def obtener_cliente(cliente_id: str, _: bool = Depends(verificar_auth)):
    c = clientes_db.get(cliente_id)
    if not c or c.get("eliminado"):
        raise HTTPException(404, "Cliente no encontrado")
    # Incluir trámites
    tramites = [t for t in tramites_db.values()
                if t.get("cliente_id") == cliente_id and not t.get("eliminado")]
    tramites.sort(key=lambda t: t.get("fecha_inicio", ""), reverse=True)
    c = dict(c)
    c["tramites"] = tramites
    return c


@app.post("/clientes")
async def crear_cliente(data: dict, _: bool = Depends(verificar_auth)):
    cid = str(uuid.uuid4())
    # ID secuencial
    ids_existentes = [c.get("id_secuencial", 0) for c in clientes_db.values()]
    sig_id = (max(ids_existentes) + 1) if ids_existentes else 1
    cliente = {
        "id": cid,
        "id_secuencial": sig_id,
        "fecha_registro": now_iso(),
        "fecha_actualizacion": now_iso(),
        "eliminado": False,
        **data
    }
    clientes_db[cid] = cliente
    guardar_clientes()
    return cliente


@app.put("/clientes/{cliente_id}")
async def actualizar_cliente(cliente_id: str, data: dict, _: bool = Depends(verificar_auth)):
    if cliente_id not in clientes_db:
        raise HTTPException(404, "Cliente no encontrado")
    cliente = clientes_db[cliente_id]
    # No sobrescribir campos internos
    for k in ("id", "id_secuencial", "fecha_registro", "eliminado"):
        data.pop(k, None)
    cliente.update(data)
    cliente["fecha_actualizacion"] = now_iso()
    guardar_clientes()
    return cliente


@app.delete("/clientes/{cliente_id}")
async def eliminar_cliente(cliente_id: str, _: bool = Depends(verificar_auth)):
    if cliente_id not in clientes_db:
        raise HTTPException(404, "Cliente no encontrado")
    clientes_db[cliente_id]["eliminado"] = True
    clientes_db[cliente_id]["fecha_actualizacion"] = now_iso()
    guardar_clientes()
    return {"ok": True}


# ══════════════════════════════════════════════════════════
#  TRÁMITES
# ══════════════════════════════════════════════════════════

@app.get("/tramites")
async def listar_tramites(
    cliente_id: Optional[str] = None,
    tipo: Optional[str] = None,
    estado: Optional[str] = None,
    _: bool = Depends(verificar_auth)
):
    tramites = [t for t in tramites_db.values() if not t.get("eliminado")]
    if cliente_id:
        tramites = [t for t in tramites if t.get("cliente_id") == cliente_id]
    if tipo:
        tramites = [t for t in tramites if t.get("tipo") == tipo]
    if estado:
        tramites = [t for t in tramites if t.get("estado") == estado]
    tramites.sort(key=lambda t: t.get("fecha_inicio", ""), reverse=True)
    # Enriquecer con nombre de cliente
    for t in tramites:
        c = clientes_db.get(t.get("cliente_id", ""), {})
        t["_cliente_nombre"] = (
            f"{c.get('nombre','')} {c.get('ap_paterno','')} {c.get('ap_materno','')}".strip()
        )
        t["_cliente_folio"] = c.get("id_secuencial", "")
    return tramites


@app.post("/tramites")
async def crear_tramite(data: dict, _: bool = Depends(verificar_auth)):
    tid = str(uuid.uuid4())
    # ID secuencial de trámites
    ids_existentes = [t.get("id_secuencial", 0) for t in tramites_db.values()]
    sig_id = (max(ids_existentes) + 1) if ids_existentes else 1
    tramite = {
        "id": tid,
        "id_secuencial": sig_id,
        "fecha_inicio": now_iso(),
        "fecha_actualizacion": now_iso(),
        "estado": "nuevo",
        "eliminado": False,
        "historial": [{
            "fecha": now_iso(),
            "accion": "Trámite creado",
            "usuario": data.get("_usuario", "sistema")
        }],
        "documentos_pendientes": [],
        **data
    }
    tramite.pop("_usuario", None)
    tramites_db[tid] = tramite
    guardar_tramites()
    return tramite


@app.put("/tramites/{tramite_id}")
async def actualizar_tramite(tramite_id: str, data: dict, _: bool = Depends(verificar_auth)):
    if tramite_id not in tramites_db:
        raise HTTPException(404, "Trámite no encontrado")
    tramite = tramites_db[tramite_id]

    # Registrar cambio de estado en historial
    nuevo_estado = data.get("estado")
    if nuevo_estado and nuevo_estado != tramite.get("estado"):
        nota_historial = {
            "fecha": now_iso(),
            "accion": f"Estado cambiado: {tramite.get('estado')} → {nuevo_estado}",
            "nota": data.get("_nota_estado", ""),
            "usuario": data.get("_usuario", "sistema")
        }
        tramite.setdefault("historial", []).append(nota_historial)

    # Agregar nota al historial si viene
    nota = data.pop("_nota_nueva", None)
    if nota:
        tramite.setdefault("historial", []).append({
            "fecha": now_iso(),
            "accion": "Nota agregada",
            "nota": nota,
            "usuario": data.get("_usuario", "sistema")
        })

    for k in ("id", "id_secuencial", "fecha_inicio", "eliminado", "historial"):
        data.pop(k, None)
    data.pop("_usuario", None)
    data.pop("_nota_estado", None)

    tramite.update(data)
    tramite["fecha_actualizacion"] = now_iso()
    guardar_tramites()
    return tramite


@app.delete("/tramites/{tramite_id}")
async def eliminar_tramite(tramite_id: str, _: bool = Depends(verificar_auth)):
    if tramite_id not in tramites_db:
        raise HTTPException(404, "Trámite no encontrado")
    tramites_db[tramite_id]["eliminado"] = True
    guardar_tramites()
    return {"ok": True}


# ── MAIN ──────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 52)
    print("  SERVIDOR CLIENTES — TRÁMITES MIGRATORIOS")
    print(f"  http://localhost:8001")
    print("=" * 52)
    uvicorn.run("servidor_clientes:app", host="0.0.0.0", port=8001, reload=True)
