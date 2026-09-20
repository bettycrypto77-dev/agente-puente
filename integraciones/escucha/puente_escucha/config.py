"""Configuración personal separada del repositorio y de sus credenciales."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tomllib
from .estado import ErrorEscucha


def numero(valor, minimo, nombre):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ErrorEscucha(f'{nombre} debe ser numérico')
    if not math.isfinite(valor) or valor < minimo:
        raise ErrorEscucha(f'{nombre} fuera de rango')
    return valor


def cargar(ruta):
    ruta = Path(ruta).expanduser().resolve()
    try:
        c = tomllib.loads(ruta.read_text())
    except (OSError, ValueError):
        raise ErrorEscucha('No se pudo leer la configuración TOML') from None
    agente = c.get('agente', '')
    if not isinstance(agente, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', agente):
        raise ErrorEscucha('agente debe ser un identificador simple')
    def camino(valor):
        if not isinstance(valor, str) or not valor:
            raise ErrorEscucha('Ruta de configuración vacía o inválida')
        p = Path(valor).expanduser()
        return str((ruta.parent / p).resolve())
    c['configuracion'] = str(ruta)
    c['raiz'] = camino(c.get('raiz', '~/agente-puente'))
    c['estado'] = camino(c.get('estado', str(Path(os.environ.get('XDG_STATE_HOME', '~/.local/state')) / 'agente-puente')))
    c['intervalo'] = numero(c.get('intervalo', 5), 0.05, 'intervalo')
    c['reavisar'] = numero(c.get('reavisar', 60), 0.05, 'reavisar')
    c['lote'] = c.get('lote', 20)
    if type(c['lote']) is not int or not 1 <= c['lote'] <= 100:
        raise ErrorEscucha('lote debe estar entre 1 y 100')
    c['archivos'] = c.get('archivos', True)
    if type(c['archivos']) is not bool:
        raise ErrorEscucha('archivos debe ser booleano')
    s = c.setdefault('slack', {})
    if not isinstance(s, dict):
        raise ErrorEscucha('slack debe ser una tabla TOML')
    s['habilitado'] = s.get('habilitado', False)
    if type(s['habilitado']) is not bool:
        raise ErrorEscucha('slack.habilitado debe ser booleano')
    if s['habilitado']:
        s['token_archivo'] = camino(s.get('token_archivo', ''))
        if not isinstance(s.get('usuario'), str) or not re.fullmatch(r'U[A-Z0-9]+', s['usuario']):
            raise ErrorEscucha('Falta el identificador propio del bot Slack')
        canales = s.get('canales', [])
        if not isinstance(canales, list) or not canales or not all(isinstance(x, str) and re.fullmatch(r'[CGD][A-Z0-9]+', x) for x in canales):
            raise ErrorEscucha('Configura los identificadores de canales propios')
        s['intervalo'] = numero(s.get('intervalo', 60), 1, 'slack.intervalo')
        s['recuperar_segundos'] = numero(s.get('recuperar_segundos', 0), 0, 'slack.recuperar_segundos')
        s['seguir_nuevos'] = s.get('seguir_nuevos', False)
        if type(s['seguir_nuevos']) is not bool:
            raise ErrorEscucha('slack.seguir_nuevos debe ser booleano')
        s['pagina'] = s.get('pagina', 15)
        if type(s['pagina']) is not int or not 1 <= s['pagina'] <= 200:
            raise ErrorEscucha('slack.pagina debe estar entre 1 y 200')
    a = c.setdefault('adaptador', {})
    if not isinstance(a, dict):
        raise ErrorEscucha('adaptador debe ser una tabla TOML')
    a['tipo'] = a.get('tipo', 'json')
    if a['tipo'] not in ('json', 'monitor', 'codex'):
        raise ErrorEscucha('Adaptador válido: json, monitor o codex')
    if a['tipo'] == 'codex':
        if not isinstance(a.get('hilo'), str) or not re.fullmatch(r'[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}', a['hilo']):
            raise ErrorEscucha('Codex requiere el UUID exacto del hilo receptor')
        a.setdefault('modelo', 'gpt-5.6-sol')
        a.setdefault('esfuerzo', 'low')
        if not isinstance(a['modelo'], str) or not a['modelo'].strip():
            raise ErrorEscucha('modelo debe ser texto no vacío')
        if a['esfuerzo'] not in ('low', 'medium', 'high', 'xhigh', 'max', 'ultra'):
            raise ErrorEscucha('esfuerzo no reconocido')
    if not c['archivos'] and not s['habilitado']:
        raise ErrorEscucha('Habilita al menos una fuente')
    # El valor del token nunca forma parte del vínculo ni del estado.
    identidad = [c['agente'], c['raiz'], s.get('usuario'), sorted(s.get('canales', []))]
    c['vinculo'] = hashlib.sha256(json.dumps(identidad).encode()).hexdigest()
    return c
