"""Pruebas sin red ni modelos: entregas, recuperación y fallos observables."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / 'integraciones/escucha'))
from puente_escucha.config import cargar
from puente_escucha.estado import Estado, ErrorEscucha, agregar, evento
from puente_escucha.fuentes import Archivos, ErrorFuente, Slack, registrar_hilo, solicitud_slack
from puente_escucha.cli import emitir, main


class Banco(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.bandeja = self.base / 'puente/a-beta'
        self.bandeja.mkdir(parents=True)
        self.cfg = self.base / 'escucha.toml'
        self.cfg.write_text('agente="beta"\nraiz="puente"\nestado="estado"\nintervalo=0.05\nreavisar=0.1\n')
        self.c = cargar(self.cfg)
        self.estado = Estado(self.c['estado'], 'beta', self.c['vinculo'])

    def mensaje(self, nombre='uno', completo=True):
        p = self.bandeja / (nombre + '.md')
        p.write_text('---\nde: alfa\npara: beta\nid: ' + nombre + '\nestado: pendiente\n' + ('---\ncuerpo privado\n' if completo else ''))
        return p

    def slack(self, fn):
        token = self.base / 'bot.token'
        token.write_text('xoxb-FICTICIO')
        token.chmod(0o600)
        self.c['slack'] = {'habilitado': True, 'token_archivo': str(token), 'usuario': 'UFICTICIO',
                           'canales': ['CFICTICIO'], 'intervalo': 1, 'pagina': 2,
                           'recuperar_segundos': 3600, 'seguir_nuevos': False}
        with self.estado.transaccion() as d:
            d['autorizacion'] = {'id': 'ensayo', 'cancelada': False, 'vence': time.time() + 300}
        def api(t, metodo, q):
            if metodo == 'auth.test':
                return {'ok': True, 'user_id': 'UFICTICIO', 'bot_id': 'BFICTICIO'}
            return fn(t, metodo, q)
        return Slack(self.c, self.estado, api)

    def correr(self, *args):
        return subprocess.run([str(RAIZ / 'bin/puente-escucha'), '--config', str(self.cfg), *args],
                              capture_output=True, text=True, timeout=5)

    def iniciar(self, *args):
        p = subprocess.Popen([str(RAIZ / 'bin/puente-escucha'), '--config', str(self.cfg), *args],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def cerrar():
            if p.poll() is None:
                p.terminate()
            p.communicate(timeout=4)
        self.addCleanup(cerrar)
        hasta = time.monotonic() + 3
        while time.monotonic() < hasta:
            if self.estado.activo():
                return p
            if p.poll() is not None:
                self.fail(p.communicate())
            time.sleep(0.02)
        self.fail('El lector no inició')


class Persistencia(Banco):
    def test_confirmacion_no_es_emision(self):
        e = evento('beta', 'archivo', {'ruta': 'a-beta/uno.md'})
        with self.estado.transaccion() as d:
            agregar(d, [e])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(emitir(self.c, [e], time.time() + 5), 'emitido')
        self.assertIsNone(self.estado.leer()['eventos'][e['id']]['confirmado_en'])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--config', str(self.cfg), 'confirmar', '--evento', e['id']]), 0)
        self.assertIsNotNone(self.estado.leer()['eventos'][e['id']]['confirmado_en'])

    def test_fallo_de_transaccion_no_avanza_cursor(self):
        with self.assertRaises(RuntimeError):
            with self.estado.transaccion() as d:
                d['fuentes']['inventado'] = {'desde': '9.000000'}
                raise RuntimeError('corte simulado')
        self.assertNotIn('inventado', self.estado.leer()['fuentes'])

    def test_estado_corrupto_no_se_reinicia(self):
        self.estado.ruta.write_text('{cortado')
        with self.assertRaises(ErrorEscucha):
            self.estado.leer()
        self.assertEqual(self.estado.ruta.read_text(), '{cortado')

    def test_estado_json_sin_estructura_no_se_reinicia(self):
        self.estado.ruta.write_text('[]')
        with self.assertRaises(ErrorEscucha):
            self.estado.leer()
        self.assertEqual(self.estado.ruta.read_text(), '[]')

    def test_no_mezclar_configuraciones(self):
        with self.estado.transaccion():
            pass
        otro = Estado(self.c['estado'], 'beta', 'otro-vinculo')
        with self.assertRaises(ErrorEscucha):
            otro.leer()

    def test_permisos_privados(self):
        with self.estado.transaccion():
            pass
        self.assertEqual(self.estado.ruta.stat().st_mode & 0o777, 0o600)

    def test_confirmar_desconocido_no_confirma_lote_parcial(self):
        e = evento('beta', 'archivo', {'ruta': 'a-beta/uno.md'})
        with self.estado.transaccion() as d:
            agregar(d, [e])
        with contextlib.redirect_stderr(io.StringIO()):
            result = main(['--config', str(self.cfg), 'confirmar', '--evento', e['id'], '--evento', 'desconocido'])
        self.assertEqual(result, 1)
        self.assertIsNone(self.estado.leer()['eventos'][e['id']]['confirmado_en'])


class FuenteArchivos(Banco):
    def test_parcial_y_reinicio(self):
        fuente = Archivos(self.c, self.estado)
        self.mensaje(completo=False)
        fuente.paso(); fuente.paso()
        self.assertEqual(self.estado.leer()['eventos'], {})
        self.mensaje()
        fuente.paso(); fuente.paso()
        self.assertEqual(len(self.estado.leer()['eventos']), 1)
        segunda = Archivos(self.c, self.estado)
        segunda.paso(); segunda.paso()
        self.assertEqual(len(self.estado.leer()['eventos']), 1)
        serial = self.estado.ruta.read_text()
        self.assertNotIn('cuerpo privado', serial)

    def test_no_reentrega_confirmado(self):
        self.mensaje()
        f = Archivos(self.c, self.estado)
        f.paso(); f.paso()
        with self.estado.transaccion() as d:
            next(iter(d['eventos'].values()))['confirmado_en'] = time.time()
        f.paso()
        self.assertTrue(next(iter(self.estado.leer()['eventos'].values()))['confirmado_en'])

    def test_ignora_otro_destinatario_y_symlink(self):
        p = self.mensaje()
        p.write_text(p.read_text().replace('para: beta', 'para: gamma'))
        externo = self.base / 'externo.md'; externo.write_text('privado')
        (self.bandeja / 'enlace.md').symlink_to(externo)
        f = Archivos(self.c, self.estado)
        f.paso(); f.paso()
        self.assertEqual(self.estado.leer()['eventos'], {})

    def test_rafaga_completa(self):
        for i in range(80):
            self.mensaje(str(i))
        f = Archivos(self.c, self.estado)
        f.paso(); f.paso()
        self.assertEqual(len(self.estado.leer()['eventos']), 80)


class FuenteSlack(Banco):
    def preparar_scope(self, slack, desde='1.000000'):
        slack.preparar()
        with self.estado.transaccion() as d:
            d['fuentes']['canal:CFICTICIO']['desde'] = desde
            d['ritmo'] = {}
        return dict(self.estado.leer()['fuentes']['canal:CFICTICIO'], hasta='100.000000')

    def test_paginacion_persistida_antes_del_cursor_final(self):
        llamadas = []
        def api(_t, _m, q):
            llamadas.append(q)
            if not q.get('cursor'):
                return {'messages': [{'ts': '9.000000', 'user': 'UOTRO', 'text': 'privado'}],
                        'has_more': True, 'response_metadata': {'next_cursor': 'pagina-dos'}}
            return {'messages': [{'ts': '2.000000', 'user': 'UOTRO'}]}
        f = self.slack(api)
        trabajo = self.preparar_scope(f)
        with self.estado.transaccion() as d:
            d['fuentes']['canal:CFICTICIO']['hasta'] = trabajo['hasta']
        f.pagina('ficticio', 'conversations.history', 'canal:CFICTICIO', trabajo)
        d = self.estado.leer()
        self.assertEqual(d['fuentes']['canal:CFICTICIO']['desde'], '1.000000')
        self.assertEqual(len(d['eventos']), 1)
        # Simular reinicio entre páginas; debe pedir la pendiente sin perder la anterior.
        f2 = Slack(self.c, self.estado, api)
        f2.pagina('ficticio', 'conversations.history', 'canal:CFICTICIO', d['fuentes']['canal:CFICTICIO'])
        d = self.estado.leer()
        self.assertEqual(llamadas[1]['cursor'], 'pagina-dos')
        self.assertEqual(len(d['eventos']), 2)
        self.assertEqual(d['fuentes']['canal:CFICTICIO']['desde'], '100.000000')
        self.assertNotIn('privado', self.estado.ruta.read_text())

    def test_paginacion_incompleta_no_avanza(self):
        f = self.slack(lambda *_: {'messages': [], 'has_more': True})
        t = self.preparar_scope(f)
        with self.assertRaisesRegex(ErrorFuente, 'paginacion_incompleta'):
            f.pagina('', 'conversations.history', 'canal:CFICTICIO', t)
        self.assertEqual(self.estado.leer()['fuentes']['canal:CFICTICIO']['desde'], '1.000000')

    def test_metadatos_invalidos_no_avanzan(self):
        for valor in (None, [], 'invalido'):
            with self.subTest(valor=valor):
                f = self.slack(lambda *_: {'messages': [], 'response_metadata': valor})
                t = self.preparar_scope(f)
                with self.assertRaisesRegex(ErrorFuente, 'metadatos_invalidos'):
                    f.pagina('', 'conversations.history', 'canal:CFICTICIO', t)
                self.assertEqual(self.estado.leer()['fuentes']['canal:CFICTICIO']['desde'], '1.000000')

    def test_ts_decimal_y_filtro_propio(self):
        f = self.slack(lambda *_: {'messages': [
            {'ts': '1700000000.000000002', 'user': 'UOTRO'},
            {'ts': '1700000000.000000003', 'user': 'UFICTICIO'},
            {'ts': '1700000000.000000004', 'subtype': 'channel_join', 'user': 'UOTRO'}]})
        t = self.preparar_scope(f, '1700000000.000000001')
        t['hasta'] = '1700000001.000000000'
        f.pagina('', 'conversations.history', 'canal:CFICTICIO', t)
        self.assertEqual(len(self.estado.leer()['eventos']), 1)

    def test_hilo_antiguo_no_depende_de_history(self):
        vistas = []
        def api(_t, m, q):
            vistas.append((m, q))
            if m == 'conversations.history':
                return {'messages': []}
            return {'messages': [{'ts': '7.000000', 'thread_ts': '2.000000', 'user': 'UOTRO'}]}
        f = self.slack(api)
        with self.estado.transaccion() as d:
            registrar_hilo(d, 'CFICTICIO', '2.000000')
        f.paso()
        self.assertTrue(any(m == 'conversations.replies' for m, _ in vistas))
        self.assertEqual(len(self.estado.leer()['eventos']), 1)

    def test_429_persistido_y_respeta_demora(self):
        veces = []
        def api(*_):
            veces.append(1)
            raise ErrorFuente('ratelimited', 120)
        f = self.slack(api)
        ahora = time.time(); f.paso(); f.paso()
        self.assertEqual(len(veces), 1)
        d = self.estado.leer()
        self.assertGreaterEqual(d['ritmo']['conversations.history'], ahora + 120)
        self.assertEqual(d['salud']['canal:CFICTICIO']['error'], 'ratelimited')
        self.assertEqual(d['fuentes']['canal:CFICTICIO']['pagina'], '')

    def test_error_hilo_visible_sin_bloquear_canal(self):
        def api(_t, metodo, _q):
            if metodo == 'conversations.replies':
                raise ErrorFuente('missing_scope')
            return {'messages': []}
        f = self.slack(api)
        with self.estado.transaccion() as d:
            registrar_hilo(d, 'CFICTICIO', '2.000000')
        f.paso()
        d = self.estado.leer()
        self.assertIsNone(d['salud']['canal:CFICTICIO']['error'])
        self.assertEqual(d['salud']['hilo:CFICTICIO:2.000000']['error'], 'missing_scope')

    def test_identidad_incorrecta_impide_lectura(self):
        f = self.slack(lambda *_: self.fail('No debe leer mensajes'))
        f.solicitar = lambda *_: {'ok': True, 'user_id': 'UOTRO', 'bot_id': 'BOTRO'}
        with self.assertRaisesRegex(ErrorFuente, 'identidad_no_coincide'):
            f.paso()

    def test_token_de_usuario_no_se_usa(self):
        f = self.slack(lambda *_: self.fail('No debe llamar Slack'))
        Path(self.c['slack']['token_archivo']).write_text('xoxp-FICTICIO')
        with self.assertRaisesRegex(ErrorFuente, 'token_bot_propio'):
            f.credencial()

    def test_token_permisos_y_rotacion(self):
        f = self.slack(lambda *_: {'messages': []})
        token = Path(self.c['slack']['token_archivo']); token.chmod(0o644)
        with self.assertRaisesRegex(ErrorFuente, 'permisos_600'):
            f.credencial()
        token.chmod(0o600); f.credencial()
        token.write_text('xoxb-NUEVO-FICTICIO')
        self.assertEqual(f.credencial(), 'xoxb-NUEVO-FICTICIO')

    def test_confirmacion_concurrente_no_se_pierde(self):
        e = evento('beta', 'archivo', {'ruta': 'uno'})
        with self.estado.transaccion() as d:
            agregar(d, [e])
        def api(*_):
            with self.estado.transaccion() as d:
                d['eventos'][e['id']]['confirmado_en'] = 99
            return {'messages': []}
        f = self.slack(api); t = self.preparar_scope(f)
        f.pagina('', 'conversations.history', 'canal:CFICTICIO', t)
        self.assertEqual(self.estado.leer()['eventos'][e['id']]['confirmado_en'], 99)

    def test_dejar_hilo_durante_consulta(self):
        def api(*_):
            with self.estado.transaccion() as d:
                d['fuentes'].pop('hilo:CFICTICIO:2.000000')
            return {'messages': [{'ts': '7.000000', 'user': 'UOTRO'}]}
        f = self.slack(api)
        with self.estado.transaccion() as d:
            clave = registrar_hilo(d, 'CFICTICIO', '2.000000')
        t = dict(self.estado.leer()['fuentes'][clave], hasta='100.000000')
        f.pagina('', 'conversations.replies', clave, t)
        self.assertNotIn(clave, self.estado.leer()['fuentes'])

    def test_broadcast_no_duplica_respuesta(self):
        f = self.slack(lambda *_: {'messages': [{'ts': '7.000000', 'thread_ts': '2.000000', 'user': 'UOTRO', 'subtype': 'thread_broadcast'}]})
        t = self.preparar_scope(f)
        f.pagina('', 'conversations.history', 'canal:CFICTICIO', t)
        with self.estado.transaccion() as d:
            k = registrar_hilo(d, 'CFICTICIO', '2.000000')
        t = dict(self.estado.leer()['fuentes'][k], hasta='100.000000')
        f.pagina('', 'conversations.replies', k, t)
        self.assertEqual(len(self.estado.leer()['eventos']), 1)

    def test_recrear_hilo_durante_consulta_no_usa_cursor_viejo(self):
        def api(*_):
            with self.estado.transaccion() as d:
                d['fuentes'].pop('hilo:CFICTICIO:2.000000')
                registrar_hilo(d, 'CFICTICIO', '2.000000')
            return {'messages': []}
        f = self.slack(api)
        with self.estado.transaccion() as d:
            clave = registrar_hilo(d, 'CFICTICIO', '2.000000')
        t = dict(self.estado.leer()['fuentes'][clave], hasta='100.000000')
        f.pagina('', 'conversations.replies', clave, t)
        self.assertEqual(self.estado.leer()['fuentes'][clave]['desde'], '0.000000')

    def test_error_http_retry_after_y_sin_token(self):
        import urllib.error
        from email.message import Message
        h = Message(); h['Retry-After'] = '73'
        error = urllib.error.HTTPError('https://slack.com/api/test', 429, 'limitado', h, None)
        with patch('urllib.request.urlopen', side_effect=error):
            with self.assertRaises(ErrorFuente) as resultado:
                solicitud_slack('NO-DEBE-APARECER', 'auth.test', {})
        self.assertEqual(resultado.exception.demora, 73)
        self.assertNotIn('NO-DEBE', str(resultado.exception))

    def test_padres_nuevos_se_siguen_incluso_propios(self):
        f = self.slack(lambda *_: {'messages': [{'ts': '4.000000', 'user': 'UFICTICIO'}]})
        self.c['slack']['seguir_nuevos'] = True
        t = self.preparar_scope(f)
        f.pagina('', 'conversations.history', 'canal:CFICTICIO', t)
        d = self.estado.leer()
        self.assertIn('hilo:CFICTICIO:4.000000', d['fuentes'])
        self.assertEqual(len(d['eventos']), 0)

    def test_error_api_no_filtra_texto_arbitrario(self):
        respuesta = io.BytesIO(json.dumps({'ok': False, 'error': 'secreto-no-publicable'}).encode())
        with patch('urllib.request.urlopen', return_value=respuesta):
            with self.assertRaisesRegex(ErrorFuente, '^slack_error$'):
                solicitud_slack('ficticio', 'auth.test', {})


class Adaptadores(Banco):
    def test_codex_predeterminado_sol_bajo(self):
        with self.cfg.open('a') as f:
            f.write('\n[adaptador]\ntipo="codex"\nhilo="00000000-0000-0000-0000-000000000000"\n')
        c = cargar(self.cfg)
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0)) as cmd:
            emitir(c, [evento('beta', 'archivo', {'ruta': 'uno'})], time.time() + 3)
        argv = cmd.call_args.args[0]
        self.assertEqual(argv[argv.index('--model') + 1], 'gpt-5.6-sol')
        self.assertEqual(argv[argv.index('-c') + 1], 'model_reasoning_effort="low"')

    def test_monitor_no_usa_failed(self):
        self.c['adaptador']['tipo'] = 'monitor'
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            emitir(self.c, [evento('beta', 'archivo', {'ruta': 'uno'})], time.time() + 2)
        self.assertTrue(salida.getvalue().startswith('ACTION_REQUIRED: '))
        self.assertNotIn('FAILED', salida.getvalue())

    def test_codex_argv_sin_shell_y_sin_confirmacion(self):
        self.c['adaptador'] = {'tipo': 'codex', 'hilo': '00000000-0000-0000-0000-000000000000', 'modelo': 'modelo-propio'}
        e = evento('beta', 'archivo', {'ruta': 'a-beta/$(no-ejecutar).md'})
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0)) as cmd:
            self.assertEqual(emitir(self.c, [e], time.time() + 3), 'encolado')
            self.assertNotIn('shell', cmd.call_args.kwargs)
            self.assertEqual(cmd.call_args.args[0][:2], ['codex', 'queue'])
            self.assertIn('$(no-ejecutar)', cmd.call_args.args[0][5])
        self.assertIsNone(e['confirmado_en'])

    def test_codex_fallo_conserva_evento(self):
        self.c['adaptador'] = {'tipo': 'codex', 'hilo': '00000000-0000-0000-0000-000000000000'}
        e = evento('beta', 'archivo', {'ruta': 'uno'})
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaises(ErrorEscucha):
                emitir(self.c, [e], time.time() + 3)
        self.assertIsNone(e['aviso_en'])


class CicloVida(Banco):
    def test_duplicado_y_parada_sin_senales_ajenas(self):
        p = self.iniciar('iniciar', '--duracion', '4s')
        otra = self.correr('iniciar', '--duracion', '1s')
        self.assertNotEqual(otra.returncode, 0)
        self.assertIn('activa', otra.stderr)
        self.assertEqual(self.correr('detener').returncode, 0)
        p.communicate(timeout=3)
        self.assertEqual(p.returncode, 0)
        self.assertFalse(self.estado.activo())
        self.assertNotEqual(self.correr('esperar').returncode, 0)

    def test_rearme_conserva_plazo_y_recupera_nuevo(self):
        self.mensaje('uno')
        primera = self.correr('esperar', '--duracion', '3s')
        self.assertEqual(primera.returncode, 0, primera.stderr)
        e = json.loads(primera.stdout)['eventos'][0]
        vence = self.estado.leer()['autorizacion']['vence']
        self.correr('confirmar', '--evento', e['id'])
        self.mensaje('dos')
        segunda = self.correr('esperar')
        self.assertEqual(segunda.returncode, 0, segunda.stderr)
        self.assertEqual(self.estado.leer()['autorizacion']['vence'], vence)
        self.assertEqual(json.loads(segunda.stdout)['eventos'][0]['referencia']['mensaje'], 'dos')

    def test_reentrega_sin_acuse_tras_reinicio(self):
        self.mensaje()
        primera = self.correr('esperar', '--duracion', '2s')
        segunda = self.correr('esperar')
        self.assertEqual(primera.returncode, 0)
        self.assertEqual(segunda.returncode, 0)
        self.assertEqual(json.loads(primera.stdout)['eventos'][0]['id'], json.loads(segunda.stdout)['eventos'][0]['id'])

    def test_caducidad_no_inventa_exito(self):
        r = self.correr('esperar', '--duracion', '0.2s')
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, '')
        self.assertFalse(self.estado.activo())

    def test_error_fuente_visible(self):
        self.bandeja.rmdir()
        r = self.correr('esperar', '--duracion', '0.2s')
        self.assertEqual(r.returncode, 3)
        estado = json.loads(self.correr('estado').stdout)
        self.assertEqual(estado['salud']['archivos']['error'], 'bandeja_inexistente')

    def test_lote_y_confirmacion_real(self):
        self.cfg.write_text(self.cfg.read_text() + 'lote=2\n')
        for nombre in ['uno', 'dos', 'tres']:
            self.mensaje(nombre)
        r = self.correr('esperar', '--duracion', '3s')
        lote = json.loads(r.stdout)['eventos']; self.assertEqual(len(lote), 2)
        for e in lote:
            self.correr('confirmar', '--evento', e['id'])
        r = self.correr('esperar')
        self.assertEqual(len(json.loads(r.stdout)['eventos']), 1)

    def test_tabla_config_invalida_da_error_legible(self):
        self.cfg.write_text('agente="beta"\nslack="no es tabla"\n')
        r = self.correr('estado')
        self.assertEqual(r.returncode, 1)
        self.assertIn('tabla TOML', r.stderr)
        self.assertNotIn('Traceback', r.stderr)

    def test_duracion_invalida_y_config_invalida(self):
        self.assertNotEqual(self.correr('iniciar', '--duracion', '0s').returncode, 0)
        self.cfg.write_text('agente="../escape"')
        self.assertNotEqual(self.correr('estado').returncode, 0)


if __name__ == '__main__':
    unittest.main()
