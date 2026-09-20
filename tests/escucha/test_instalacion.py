"""Instalación opcional aislada: no modifica el entorno del usuario."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

RAIZ = Path(__file__).resolve().parents[2]


class Instalacion(unittest.TestCase):
    def test_prefijo_aislado_y_cli_basica_independiente(self):
        with tempfile.TemporaryDirectory(prefix='puente-instalacion-') as d:
            base = Path(d)
            prefijo = base / 'prefijo'
            def make(objetivo):
                p = subprocess.run(['make', objetivo, f'PREFIX={prefijo}'], cwd=RAIZ,
                                   capture_output=True, text=True, timeout=10)
                self.assertEqual(p.returncode, 0, p.stderr)
            make('install')
            self.assertTrue((prefijo / 'bin/puente').exists())
            self.assertFalse((prefijo / 'bin/puente-escucha').exists())
            make('install-escucha')
            config = base / 'escucha.toml'
            config.write_text(f'agente="prueba"\nraiz="{base}/puente"\nestado="{base}/estado"\nintervalo=0.05\n')
            bandeja = base / 'puente/a-prueba'; bandeja.mkdir(parents=True)
            (bandeja / 'mensaje.md').write_text('---\npara: prueba\nestado: pendiente\nid: sintesis\n---\ntexto ficticio\n')
            cli = prefijo / 'bin/puente-escucha'
            p = subprocess.run([str(cli), '--config', str(config), 'esperar', '--duracion', '2s'],
                               cwd=base, capture_output=True, text=True, timeout=5)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(p.stdout)['eventos'][0]['referencia']['mensaje'], 'sintesis')
            make('uninstall-escucha')
            self.assertFalse(cli.exists())
            self.assertTrue((prefijo / 'bin/puente').exists())
            self.assertTrue((base / 'estado/prueba/estado.json').exists())
            make('uninstall')
            self.assertFalse((prefijo / 'bin/puente').exists())
