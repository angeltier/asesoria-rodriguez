"""
SERVIDOR GESTIÓN DE CLIENTES — ASESORÍA RODRÍGUEZ
FastAPI + almacenamiento JSON local + documentos en base64

Deploy: Render.com
  Build:  pip install -r requirements_clientes.txt
  Start:  uvicorn servidor_clientes:app --host 0.0.0.0 --port $PORT
"""

import json, os, uuid, base64
from datetime import datetime, timezone
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File, Form
from fastapi.responses import HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ── ARCHIVOS ──────────────────────────────────────────────
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
HTML_FILE      = os.path.join(BASE_DIR, "clientes.html")
CLIENTES_FILE  = os.path.join(BASE_DIR, "clientes.json")
TRAMITES_FILE  = os.path.join(BASE_DIR, "tramites.json")
USUARIOS_FILE  = os.path.join(BASE_DIR, "usuarios.json")
DOCS_FILE      = os.path.join(BASE_DIR, "documentos.json")

MAX_FILE_SIZE  = 10 * 1024 * 1024  # 10 MB por archivo

# ── USUARIOS ──────────────────────────────────────────────
USUARIOS_DEFAULT = {
    "Tier": {"password": "Plcdoae123", "nombre": "Angel Tier", "rol": "admin"}
}

def cargar_usuarios():
    if os.path.exists(USUARIOS_FILE):
        try:
            with open(USUARIOS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return dict(USUARIOS_DEFAULT)

def guardar_usuarios(u):
    with open(USUARIOS_FILE, "w", encoding="utf-8") as f:
        json.dump(u, f, ensure_ascii=False, indent=2)

# ── ESTADO ────────────────────────────────────────────────
clientes_db: dict = {}
tramites_db: dict = {}
docs_db:     dict = {}

def cargar_datos():
    global clientes_db, tramites_db, docs_db
    for path, nombre, ref in [
        (CLIENTES_FILE, "clientes",   "clientes_db"),
        (TRAMITES_FILE, "tramites",   "tramites_db"),
        (DOCS_FILE,     "documentos", "docs_db"),
    ]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                globals()[ref] = data
                print(f"[{nombre}] {len(data)} registros cargados")
            except Exception as e:
                print(f"[ERROR] {nombre}: {e}")

def guardar_clientes():
    with open(CLIENTES_FILE, "w", encoding="utf-8") as f:
        json.dump(clientes_db, f, ensure_ascii=False, indent=2, default=str)

def guardar_tramites():
    with open(TRAMITES_FILE, "w", encoding="utf-8") as f:
        json.dump(tramites_db, f, ensure_ascii=False, indent=2, default=str)

def guardar_docs():
    # Guardar sin el contenido base64 en el índice, solo en los registros completos
    with open(DOCS_FILE, "w", encoding="utf-8") as f:
        json.dump(docs_db, f, ensure_ascii=False, indent=2, default=str)

def now_iso():
    return datetime.now(timezone.utc).isoformat()

# ── LIFESPAN ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    cargar_datos()
    yield

# ── APP ───────────────────────────────────────────────────
app = FastAPI(title="Gestion de Clientes — Asesoria Rodriguez", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# ── AUTH ──────────────────────────────────────────────────
def verificar_auth(
    x_usuario: Optional[str] = Header(None),
    x_password: Optional[str] = Header(None)
):
    usuarios = cargar_usuarios()
    if x_usuario:
        u = usuarios.get(x_usuario)
        if not u or u.get("password") != x_password:
            raise HTTPException(401, "Usuario o contrasena incorrectos")
        return {"usuario": x_usuario, "rol": u.get("rol","editor"), "nombre": u.get("nombre", x_usuario)}
    for nombre, data in usuarios.items():
        if data.get("password") == x_password:
            return {"usuario": nombre, "rol": data.get("rol","editor"), "nombre": data.get("nombre", nombre)}
    raise HTTPException(401, "Contrasena incorrecta")

def verificar_admin(auth=Depends(verificar_auth)):
    if auth.get("rol") != "admin":
        raise HTTPException(403, "Se requiere rol admin")
    return auth

# ── HTML ──────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def raiz():
    if os.path.exists(HTML_FILE):
        with open(HTML_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse("<h2>clientes.html no encontrado</h2>", 404)

# ── STATUS ────────────────────────────────────────────────
@app.get("/status")
async def status():
    pe = {}
    for t in tramites_db.values():
        e = t.get("estado","nuevo"); pe[e] = pe.get(e,0)+1
    total_docs = sum(len(v) for v in docs_db.values())
    return {"clientes": len(clientes_db), "tramites": len(tramites_db),
            "documentos": total_docs, "por_estado": pe}

# ══════════════════════════════════════════════════════════
#  USUARIOS
# ══════════════════════════════════════════════════════════

@app.get("/usuarios")
async def listar_usuarios(auth=Depends(verificar_admin)):
    u = cargar_usuarios()
    return [{"usuario": k, "nombre": v.get("nombre",k), "rol": v.get("rol","editor")}
            for k, v in u.items()]

@app.post("/usuarios")
async def crear_usuario(data: dict, auth=Depends(verificar_admin)):
    u = cargar_usuarios(); nu = data.get("usuario","").strip()
    if not nu: raise HTTPException(400, "Usuario requerido")
    if nu in u: raise HTTPException(400, f"'{nu}' ya existe")
    u[nu] = {"password": data.get("password",""), "nombre": data.get("nombre",nu), "rol": data.get("rol","editor")}
    guardar_usuarios(u); return {"ok": True, "usuario": nu}

@app.put("/usuarios/{nu}")
async def actualizar_usuario(nu: str, data: dict, auth=Depends(verificar_admin)):
    u = cargar_usuarios()
    if nu not in u: raise HTTPException(404, "No encontrado")
    if data.get("password"): u[nu]["password"] = data["password"]
    if data.get("nombre"):   u[nu]["nombre"]   = data["nombre"]
    if data.get("rol"):      u[nu]["rol"]       = data["rol"]
    guardar_usuarios(u); return {"ok": True}

@app.delete("/usuarios/{nu}")
async def eliminar_usuario(nu: str, auth=Depends(verificar_admin)):
    u = cargar_usuarios()
    if nu not in u: raise HTTPException(404, "No encontrado")
    if nu == auth.get("usuario"): raise HTTPException(400, "No puedes eliminarte")
    del u[nu]; guardar_usuarios(u); return {"ok": True}

@app.get("/mi-perfil")
async def mi_perfil(auth=Depends(verificar_auth)):
    return auth

# ══════════════════════════════════════════════════════════
#  CLIENTES
# ══════════════════════════════════════════════════════════

@app.get("/clientes")
async def listar_clientes(q: Optional[str] = None, _=Depends(verificar_auth)):
    cs = [c for c in clientes_db.values() if not c.get("eliminado")]
    if q:
        ql = q.lower()
        cs = [c for c in cs if
              ql in (c.get("nombre","")+" "+c.get("ap_paterno","")+" "+c.get("ap_materno","")).lower()
              or ql in c.get("telefono","").lower()
              or ql in c.get("email","").lower()
              or ql in c.get("curp","").lower()
              or ql in str(c.get("id_secuencial",""))]
    cs.sort(key=lambda c: c.get("fecha_registro",""), reverse=True)
    for c in cs:
        tc = [t for t in tramites_db.values()
              if t.get("cliente_id")==c["id"] and not t.get("eliminado")]
        c["_num_tramites"] = len(tc)
        c["_tramite_activo"] = next(
            (t["tipo"] for t in tc if t.get("estado") not in ("aprobado","entregado","rechazado","cancelado")), None)
        c["_num_docs"] = len(docs_db.get(c["id"], []))
    return cs

@app.get("/clientes/{cid}")
async def obtener_cliente(cid: str, _=Depends(verificar_auth)):
    c = clientes_db.get(cid)
    if not c or c.get("eliminado"): raise HTTPException(404, "No encontrado")
    ts = [t for t in tramites_db.values()
          if t.get("cliente_id")==cid and not t.get("eliminado")]
    ts.sort(key=lambda t: t.get("fecha_inicio",""), reverse=True)
    c = dict(c)
    c["tramites"] = ts
    # Documentos sin contenido base64 (solo metadatos)
    c["documentos"] = [
        {k: v for k, v in d.items() if k != "contenido"}
        for d in docs_db.get(cid, [])
        if not d.get("eliminado")
    ]
    return c

@app.post("/clientes")
async def crear_cliente(data: dict, _=Depends(verificar_auth)):
    cid = str(uuid.uuid4())
    ids = [c.get("id_secuencial",0) for c in clientes_db.values()]
    cliente = {"id": cid, "id_secuencial": (max(ids)+1 if ids else 1),
               "fecha_registro": now_iso(), "fecha_actualizacion": now_iso(),
               "eliminado": False, **data}
    clientes_db[cid] = cliente; guardar_clientes(); return cliente

@app.put("/clientes/{cid}")
async def actualizar_cliente(cid: str, data: dict, _=Depends(verificar_auth)):
    if cid not in clientes_db: raise HTTPException(404, "No encontrado")
    c = clientes_db[cid]
    for k in ("id","id_secuencial","fecha_registro","eliminado"): data.pop(k,None)
    c.update(data); c["fecha_actualizacion"] = now_iso()
    guardar_clientes(); return c

@app.delete("/clientes/{cid}")
async def eliminar_cliente(cid: str, _=Depends(verificar_auth)):
    if cid not in clientes_db: raise HTTPException(404, "No encontrado")
    clientes_db[cid]["eliminado"] = True
    clientes_db[cid]["fecha_actualizacion"] = now_iso()
    guardar_clientes(); return {"ok": True}

# ══════════════════════════════════════════════════════════
#  TRÁMITES
# ══════════════════════════════════════════════════════════

@app.get("/tramites")
async def listar_tramites(cliente_id: Optional[str]=None, tipo: Optional[str]=None,
                           estado: Optional[str]=None, _=Depends(verificar_auth)):
    ts = [t for t in tramites_db.values() if not t.get("eliminado")]
    if cliente_id: ts = [t for t in ts if t.get("cliente_id")==cliente_id]
    if tipo:       ts = [t for t in ts if t.get("tipo")==tipo]
    if estado:     ts = [t for t in ts if t.get("estado")==estado]
    ts.sort(key=lambda t: t.get("fecha_inicio",""), reverse=True)
    for t in ts:
        c = clientes_db.get(t.get("cliente_id",""), {})
        t["_cliente_nombre"] = f"{c.get('nombre','')} {c.get('ap_paterno','')} {c.get('ap_materno','')}".strip()
        t["_cliente_folio"]  = c.get("id_secuencial","")
    return ts

@app.post("/tramites")
async def crear_tramite(data: dict, _=Depends(verificar_auth)):
    tid = str(uuid.uuid4())
    ids = [t.get("id_secuencial",0) for t in tramites_db.values()]
    tramite = {"id": tid, "id_secuencial": (max(ids)+1 if ids else 1),
               "fecha_inicio": now_iso(), "fecha_actualizacion": now_iso(),
               "estado": "nuevo", "eliminado": False,
               "historial": [{"fecha": now_iso(), "accion": "Tramite creado",
                               "usuario": data.pop("_usuario","sistema")}],
               "documentos_pendientes": [], **data}
    tramites_db[tid] = tramite; guardar_tramites(); return tramite

@app.put("/tramites/{tid}")
async def actualizar_tramite(tid: str, data: dict, _=Depends(verificar_auth)):
    if tid not in tramites_db: raise HTTPException(404, "No encontrado")
    t = tramites_db[tid]; ne = data.get("estado")
    if ne and ne != t.get("estado"):
        t.setdefault("historial",[]).append(
            {"fecha": now_iso(), "accion": f"Estado: {t.get('estado')} -> {ne}",
             "nota": data.get("_nota_estado",""), "usuario": data.get("_usuario","sistema")})
    nota = data.pop("_nota_nueva", None)
    if nota:
        t.setdefault("historial",[]).append(
            {"fecha": now_iso(), "accion": "Nota", "nota": nota,
             "usuario": data.get("_usuario","sistema")})
    for k in ("id","id_secuencial","fecha_inicio","eliminado","historial","_usuario","_nota_estado"):
        data.pop(k,None)
    t.update(data); t["fecha_actualizacion"] = now_iso()
    guardar_tramites(); return t

@app.delete("/tramites/{tid}")
async def eliminar_tramite(tid: str, _=Depends(verificar_auth)):
    if tid not in tramites_db: raise HTTPException(404, "No encontrado")
    tramites_db[tid]["eliminado"] = True; guardar_tramites(); return {"ok": True}

# ══════════════════════════════════════════════════════════
#  DOCUMENTOS
# ══════════════════════════════════════════════════════════

TIPOS_MIME = {
    ".pdf":  "application/pdf",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".webp": "image/webp",
    ".doc":  "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls":  "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

@app.get("/clientes/{cid}/documentos")
async def listar_documentos(cid: str, _=Depends(verificar_auth)):
    if cid not in clientes_db: raise HTTPException(404, "Cliente no encontrado")
    docs = [
        {k: v for k, v in d.items() if k != "contenido"}
        for d in docs_db.get(cid, [])
        if not d.get("eliminado")
    ]
    return docs

@app.post("/clientes/{cid}/documentos")
async def subir_documento(
    cid: str,
    archivo: UploadFile = File(...),
    categoria: str = Form("general"),
    descripcion: str = Form(""),
    x_usuario: Optional[str] = Header(None),
    x_password: Optional[str] = Header(None)
):
    # Verificar auth manualmente (multipart no pasa por Depends fácilmente)
    auth = verificar_auth(x_usuario, x_password)
    if cid not in clientes_db: raise HTTPException(404, "Cliente no encontrado")

    contenido = await archivo.read()
    if len(contenido) > MAX_FILE_SIZE:
        raise HTTPException(413, f"Archivo demasiado grande. Máximo 10 MB.")

    ext = os.path.splitext(archivo.filename or "")[1].lower()
    mime = TIPOS_MIME.get(ext, archivo.content_type or "application/octet-stream")

    doc = {
        "id":          str(uuid.uuid4()),
        "cliente_id":  cid,
        "nombre":      archivo.filename or "documento",
        "categoria":   categoria,
        "descripcion": descripcion,
        "mime":        mime,
        "extension":   ext,
        "tamano":      len(contenido),
        "contenido":   base64.b64encode(contenido).decode("utf-8"),
        "fecha":       now_iso(),
        "subido_por":  auth.get("nombre", "sistema"),
        "eliminado":   False,
    }

    if cid not in docs_db:
        docs_db[cid] = []
    docs_db[cid].append(doc)
    guardar_docs()

    return {k: v for k, v in doc.items() if k != "contenido"}

@app.get("/clientes/{cid}/documentos/{doc_id}")
async def descargar_documento(cid: str, doc_id: str, _=Depends(verificar_auth)):
    docs = docs_db.get(cid, [])
    doc = next((d for d in docs if d["id"]==doc_id and not d.get("eliminado")), None)
    if not doc: raise HTTPException(404, "Documento no encontrado")
    contenido = base64.b64decode(doc["contenido"])
    return Response(
        content=contenido,
        media_type=doc.get("mime","application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{doc["nombre"]}"'}
    )

@app.delete("/clientes/{cid}/documentos/{doc_id}")
async def eliminar_documento(cid: str, doc_id: str, _=Depends(verificar_auth)):
    docs = docs_db.get(cid, [])
    doc = next((d for d in docs if d["id"]==doc_id), None)
    if not doc: raise HTTPException(404, "Documento no encontrado")
    doc["eliminado"] = True
    guardar_docs()
    return {"ok": True}

# ── MAIN ──────────────────────────────────────────────────
if __name__ == "__main__":
    print("="*52)
    print("  SERVIDOR CLIENTES — ASESORIA RODRIGUEZ")
    print("  http://localhost:8001")
    print("="*52)
    uvicorn.run("servidor_clientes:app", host="0.0.0.0", port=8001, reload=True)
