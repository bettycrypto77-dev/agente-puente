"""Lectores que persisten referencias, nunca cuerpos de conversaciones."""
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from .estado import ErrorEscucha, agregar, evento


class ErrorFuente(ErrorEscucha):
    def __init__(self, codigo, demora=30):
        self.codigo = codigo
        self.demora = demora
        super().__init__(codigo)


def marca_valida(ts):
    return isinstance(ts, str) and bool(re.fullmatch(r'\d{1,16}\.\d{1,9}', ts))


class Archivos:
    def __init__(self, config, estado):
        self.c = config
        self.estado = estado
        self.observados = {}

    def paso(self):
        raiz = Path(self.c['raiz'])
        bandeja = raiz / ('a-' + self.c['agente'])
        if not bandeja.is_dir():
            raise ErrorFuente('bandeja_inexistente')
        eventos = []
        vistos = {}
        for p in sorted(bandeja.glob('*.md')):
            if p.is_symlink() or not p.is_file():
                continue
            stat = p.stat()
            firma = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
            vistos[p.name] = firma
            # Dos observaciones iguales: tolerar escrituras parciales sin consumirlas.
            if self.observados.get(p.name) != firma:
                continue
            if stat.st_size > 1024 * 1024:
                raise ErrorFuente('archivo_demasiado_grande')
            texto = p.read_text(encoding='utf-8')
            if (p.stat().st_size, p.stat().st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
                continue
            lineas = texto.splitlines()
            if not lineas or lineas[0] != '---':
                continue
            try:
                fin = lineas.index('---', 1)
            except ValueError:
                continue
            campos = {}
            for linea in lineas[1:fin]:
                k, separador, v = linea.partition(':')
                if separador:
                    campos[k.strip()] = v.strip().strip('"\'')
            if campos.get('para') != self.c['agente'] or campos.get('estado') != 'pendiente':
                continue
            identificador = campos.get('id', p.stem)
            # El identificador público va acotado; los cuerpos no salen de este lector.
            if len(identificador) > 256:
                raise ErrorFuente('identificador_demasiado_largo')
            eventos.append(evento(self.c['agente'], 'archivo', {
                'ruta': str(p.relative_to(raiz)), 'mensaje': identificador}))
        self.observados = vistos
        with self.estado.transaccion() as d:
            agregar(d, eventos)
            d['salud']['archivos'] = {'consulta_en': time.time(), 'error': None}


def solicitud_slack(token, metodo, parametros):
    # Endpoint fijo: la configuración no puede redirigir la credencial.
    req = urllib.request.Request('https://slack.com/api/' + metodo + '?' + urllib.parse.urlencode(parametros),
                                 headers={'Authorization': 'Bearer ' + token})
    try:
        with urllib.request.urlopen(req, timeout=10) as respuesta:
            datos = json.load(respuesta)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            try:
                espera = max(1, float(e.headers.get('Retry-After', '60')))
                if not __import__('math').isfinite(espera):
                    espera = 60
            except ValueError:
                espera = 60
            raise ErrorFuente('ratelimited', espera) from None
        raise ErrorFuente('http_error') from None
    except (OSError, ValueError):
        raise ErrorFuente('red_o_respuesta_invalida') from None
    if not isinstance(datos, dict) or not datos.get('ok'):
        permitidos = {'invalid_auth', 'token_revoked', 'account_inactive', 'missing_scope',
                      'not_in_channel', 'channel_not_found', 'thread_not_found',
                      'not_allowed_token_type', 'ratelimited', 'access_denied'}
        error = datos.get('error') if isinstance(datos, dict) else None
        raise ErrorFuente(error if error in permitidos else 'slack_error', 60)
    return datos


class Slack:
    def __init__(self, config, estado, solicitar=solicitud_slack):
        self.c = config
        self.s = config['slack']
        self.estado = estado
        self.solicitar = solicitar
        self.token_validado = None
        self.reintentar_identidad = 0

    def credencial(self):
        p = Path(self.s['token_archivo'])
        try:
            st = p.stat()
            if st.st_uid != os.getuid() or st.st_mode & 0o077:
                raise ErrorFuente('token_requiere_permisos_600')
            token = p.read_text().strip()
        except OSError:
            raise ErrorFuente('token_no_disponible') from None
        if not token.startswith('xoxb-') or any(x.isspace() for x in token):
            raise ErrorFuente('se_requiere_token_bot_propio')
        if token != self.token_validado:
            datos = self.solicitar(token, 'auth.test', {})
            if datos.get('user_id') != self.s['usuario'] or not datos.get('bot_id'):
                raise ErrorFuente('identidad_no_coincide')
            self.token_validado = token
        return token

    def preparar(self):
        with self.estado.transaccion() as d:
            for canal in self.s['canales']:
                clave = 'canal:' + canal
                if clave not in d['fuentes']:
                    desde = f"{max(0, time.time() - self.s['recuperar_segundos']):.6f}"
                    d['fuentes'][clave] = {'canal': canal, 'padre': None, 'desde': desde, 'generacion': str(uuid.uuid4()),
                                            'pagina': '', 'hasta': None, 'consulta_en': 0}

    def paso(self):
        self.preparar()
        if time.time() < self.reintentar_identidad:
            return
        try:
            token = self.credencial()
        except ErrorFuente as e:
            self.reintentar_identidad = time.time() + e.demora
            raise
        # Una página por método y paso. La pausa por método queda persistida para el rearme.
        for metodo, hilos in [('conversations.history', False), ('conversations.replies', True)]:
            if not self.estado.autorizado():
                return
            with self.estado.transaccion() as d:
                if d['ritmo'].get(metodo, 0) > time.time():
                    continue
                candidatos = [(k, v) for k, v in d['fuentes'].items()
                              if bool(v['padre']) == hilos and v.get('reintentar_en', 0) <= time.time()]
                if not candidatos:
                    continue
                clave, trabajo = min(candidatos, key=lambda kv: (kv[1]['consulta_en'], kv[0]))
                if not trabajo['hasta']:
                    trabajo['hasta'] = f'{time.time():.6f}'
                trabajo['consulta_en'] = time.time()
                trabajo = dict(trabajo)
                d['ritmo'][metodo] = time.time() + self.s['intervalo']
            try:
                self.pagina(token, metodo, clave, trabajo)
            except ErrorFuente as e:
                with self.estado.transaccion() as d:
                    anterior = d['salud'].get(clave, {})
                    intentos = anterior.get('fallos', 0) + 1
                    demora = e.demora if e.codigo == 'ratelimited' else max(e.demora, min(300, 2 ** min(intentos, 8)))
                    if e.codigo == 'ratelimited':
                        d['ritmo'][metodo] = max(d['ritmo'].get(metodo, 0), time.time() + demora)
                    if clave not in d['fuentes']:
                        continue
                    d['fuentes'][clave]['reintentar_en'] = time.time() + demora
                    d['salud'][clave] = {'error': e.codigo, 'fallos': intentos, 'consulta_en': time.time()}
                # No abortar el otro método: un hilo sin permiso no debe ocultar el canal.

    def pagina(self, token, metodo, clave, trabajo):
        q = {'channel': trabajo['canal'], 'oldest': trabajo['desde'],
             'latest': trabajo['hasta'], 'inclusive': 'true', 'limit': self.s['pagina']}
        if trabajo['pagina']:
            q['cursor'] = trabajo['pagina']
        if trabajo['padre']:
            q['ts'] = trabajo['padre']
        respuesta = self.solicitar(token, metodo, q)
        mensajes = respuesta.get('messages')
        if not isinstance(mensajes, list):
            raise ErrorFuente('respuesta_sin_mensajes')
        metadatos = respuesta.get('response_metadata', {})
        if not isinstance(metadatos, dict):
            raise ErrorFuente('metadatos_invalidos')
        siguiente = metadatos.get('next_cursor', '')
        if not isinstance(siguiente, str) or (siguiente and siguiente == trabajo['pagina']):
            raise ErrorFuente('cursor_invalido')
        if respuesta.get('has_more') and not siguiente:
            raise ErrorFuente('paginacion_incompleta')
        nuevos, padres = [], []
        for m in mensajes:
            if not isinstance(m, dict) or not marca_valida(m.get('ts')):
                raise ErrorFuente('mensaje_sin_ts_valido')
            ts = m['ts']
            if Decimal(ts) <= Decimal(trabajo['desde']) or Decimal(ts) > Decimal(trabajo['hasta']):
                continue
            padre = m.get('thread_ts')
            if padre is not None and not marca_valida(padre):
                raise ErrorFuente('hilo_invalido')
            if not trabajo['padre'] and self.s['seguir_nuevos'] and m.get('subtype') in (None, 'bot_message', 'thread_broadcast'):
                padres.append(padre or ts)
            if ts == trabajo['padre']:
                continue
            if m.get('user') == self.s['usuario'] or m.get('subtype') not in (None, 'bot_message', 'thread_broadcast'):
                continue
            # Mismo id en canal y replies; un broadcast de hilo no genera dos avisos.
            referencia = {'canal': trabajo['canal'], 'ts': ts,
                          'hilo': (padre if padre and padre != ts else trabajo['padre'])}
            nuevos.append(evento(self.c['agente'], 'slack', referencia))
        with self.estado.transaccion() as d:
            if clave not in d['fuentes'] or d['fuentes'][clave].get('generacion') != trabajo.get('generacion'):
                return  # Se retiró o reemplazó el seguimiento durante la consulta.
            agregar(d, nuevos)
            actual = d['fuentes'][clave]
            if siguiente:
                actual['pagina'] = siguiente
            else:
                actual['desde'] = trabajo['hasta']
                actual['hasta'] = None
                actual['pagina'] = ''
            actual['reintentar_en'] = 0
            d['salud'][clave] = {'consulta_en': time.time(), 'error': None, 'fallos': 0}
            d['salud']['slack'] = {'consulta_en': time.time(), 'error': None}
            for padre in padres:
                registrar_hilo(d, trabajo['canal'], padre, padre)


def registrar_hilo(datos, canal, padre, desde='0.000000'):
    clave = 'hilo:' + canal + ':' + padre
    datos['fuentes'].setdefault(clave, {'canal': canal, 'padre': padre, 'desde': desde, 'generacion': str(uuid.uuid4()),
                                        'pagina': '', 'hasta': None, 'consulta_en': 0})
    return clave
