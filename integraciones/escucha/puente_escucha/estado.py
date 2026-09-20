"""Persistencia transaccional y exclusión por agente en sistemas POSIX."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time


class ErrorEscucha(Exception):
    """Error publicable: nunca incluye cuerpos de mensajes ni credenciales."""


def guardar(ruta, datos):
    fd, temporal = tempfile.mkstemp(prefix='.estado-', dir=ruta.parent)
    try:
        with os.fdopen(fd, 'w') as salida:
            json.dump(datos, salida, ensure_ascii=False, sort_keys=True)
            salida.flush()
            os.fsync(salida.fileno())
        os.replace(temporal, ruta)
        directorio = os.open(ruta.parent, os.O_RDONLY)
        try:
            os.fsync(directorio)
        finally:
            os.close(directorio)
    finally:
        if os.path.exists(temporal):
            os.unlink(temporal)


class Estado:
    def __init__(self, base, agente, vinculo):
        self.directorio = Path(base) / agente
        self.directorio.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.ruta = self.directorio / 'estado.json'
        self.vinculo = vinculo

    @contextlib.contextmanager
    def bloqueo(self, nombre, esperar=True):
        fd = os.open(self.directorio / nombre, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | (0 if esperar else fcntl.LOCK_NB))
            except BlockingIOError:
                raise ErrorEscucha('Ya hay una escucha activa para este agente') from None
            yield
        finally:
            os.close(fd)

    def leer(self):
        if not self.ruta.exists():
            return {'version': 1, 'vinculo': self.vinculo, 'eventos': {},
                    'fuentes': {}, 'ritmo': {}, 'salud': {}, 'autorizacion': None}
        try:
            datos = json.loads(self.ruta.read_text())
        except (ValueError, OSError):
            raise ErrorEscucha('Estado ilegible; se conserva y no se reinician los cursores') from None
        if not isinstance(datos, dict) or datos.get('version') != 1 or datos.get('vinculo') != self.vinculo:
            raise ErrorEscucha('Estado incompatible con esta configuración; usa otro directorio de estado')
        if any(not isinstance(datos.get(k), dict) for k in ('eventos', 'fuentes', 'ritmo', 'salud')) or 'autorizacion' not in datos:
            raise ErrorEscucha('Estructura de estado inválida; no se reinician los cursores')
        return datos

    @contextlib.contextmanager
    def transaccion(self):
        with self.bloqueo('estado.lock'):
            datos = self.leer()
            yield datos
            guardar(self.ruta, datos)

    def activo(self):
        try:
            with self.bloqueo('lector.lock', esperar=False):
                return False
        except ErrorEscucha:
            return True

    def autorizado(self):
        a = self.leer()['autorizacion']
        return bool(a and not a['cancelada'] and time.time() < a['vence'])


def evento(agente, fuente, referencia):
    material = json.dumps([agente, fuente, referencia], sort_keys=True)
    return {'version': 1, 'id': hashlib.sha256(material.encode()).hexdigest(),
            'tipo': 'mensaje', 'agente': agente, 'fuente': fuente,
            'referencia': referencia, 'detectado_en': time.time(),
            'aviso_en': None, 'confirmado_en': None}


def agregar(datos, eventos):
    for e in eventos:
        datos['eventos'].setdefault(e['id'], e)
