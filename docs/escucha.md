# Escucha opcional bajo demanda

Al 20-09-2026 esta integración añade un lector de archivos y, opcionalmente, de Slack.
Cada agente conserva su arnés; los mensajes largos siguen en las bandejas del puente.
No se instala un servicio, no se inyecta texto en terminales y no se ejecutan órdenes tomadas
del contenido de un mensaje. `puente watch` y la instalación básica conservan su comportamiento.

## Instalación

Python 3.11+ y POSIX (Linux/macOS; bloqueo `flock`). Sin paquetes Python externos.

```sh
make install-escucha
mkdir -p ~/.config/puente
cp examples/escucha.toml.example ~/.config/puente/escucha.toml
```

Edita `agente` y `raiz`. La bandeja debe existir como `RAIZ/a-AGENTE/`.
Para varios agentes, usa un TOML por agente y pasa `--config RUTA` **antes** del comando,
o exporta `PUENTE_ESCUCHA_CONFIG`. Las rutas relativas del TOML se resuelven desde su directorio.
El estado va fuera del repo, por defecto en `$XDG_STATE_HOME/agente-puente` o
`~/.local/state/agente-puente`. Los ejemplos son ficticios: no copies tokens ni tus archivos
operativos al checkout. Para Slack consulta la [guía breve](slack.md).

## Ciclo de uso

Desde la herramienta de tareas en segundo plano del propio arnés:

```sh
puente-escucha esperar --duracion 15m
```

Termina al emitir el primer lote. El lote incluye las rutas de la configuración y de la raíz para localizar las referencias.
El arnés entrega el aviso al agente según su
[adaptador](adaptadores.md). Después de **recibir y leer** un evento, el destinatario confirma:

```sh
puente-escucha confirmar --evento ID_EVENTO
puente-escucha esperar
```

El segundo `esperar` conserva el vencimiento inicial. No pongas de nuevo `--duracion` en
cada rearme: una duración explícita concede un plazo nuevo. El tiempo sin proceso también
consume el plazo. Tras cancelar o vencer, hace falta un nuevo inicio autorizado explícitamente.
Si no confirmas, el aviso puede repetirse después de `reavisar` segundos; no se borra.

Alternativa: `iniciar --duracion 15m` emite lotes durante todo el plazo. También corre en
primer plano, dentro de la tarea supervisada por tu arnés. No basta con lanzar un bucle a
segundo plano para garantizar que un modelo ocioso vea stdout.

```sh
puente-escucha estado
puente-escucha detener
puente-escucha estado
```

`detener` cancela la autorización persistente; el lector comprueba la cancelación y sale.
No envía señales a PIDs ajenos. Una solicitud HTTP ya en curso puede tardar hasta 10 s;
una cola Codex hasta 15 s. La parada no revoca un aviso ya en tránsito. Comprueba
`proceso_activo: false` antes de afirmar que terminó. Ctrl-C/SIGTERM también cancela.
Un cierre inesperado libera el bloqueo; los pendientes y el plazo quedan para el siguiente
`esperar`. No se detecta automáticamente el cierre de todo tipo de arnés: el plazo máximo
es la protección disponible donde no existe esa señal.

## Comandos

| Comando | Efecto |
| --- | --- |
| `iniciar --duracion 15m` | Autoriza el plazo y escucha hasta cierre/vencimiento |
| `esperar [--duracion 15m]` | Emite un lote y termina; sin duración reusa el plazo vigente |
| `estado` | Proceso activo, plazo, errores, referencias pendientes y confirmaciones |
| `detener` | Cancela el plazo y solicita cierre cooperativo |
| `confirmar --evento ID` | Confirma recepción de un evento; admite repetir la opción |
| `seguir-hilo --canal ID --padre TS` | Registra un hilo, inicialmente desde sus respuestas disponibles |
| `dejar-hilo --canal ID --padre TS` | Deja de consultar; conserva avisos pendientes |
| `comprobar-slack [--canal ID --padre TS]` | Verifica identidad y lectura sin mostrar mensajes |

Códigos: `0` lote emitido (esperar) o parada solicitada atendida; `1` configuración,
instancia duplicada o error de control; `2` plazo vencido sin nuevo lote; `3` vencimiento
con errores de fuente/adaptador. `iniciar` acaba con 2 al agotar su plazo incluso si emitió
avisos antes: emitir no convierte el vencimiento en un encargo completado.

## Garantías y límites

- Un bloqueo por agente impide dos lectores en el mismo directorio de estado. No configures
  distintos directorios para la misma identidad si buscas esa exclusión. Dos configuraciones
  con distinta raíz/identidad/canales no pueden reutilizar accidentalmente sus cursores.
- Estado JSON transaccional, permisos privados y sustitución atómica. Eventos y avance de
  página/cursor se guardan juntos. Un fallo de escritura no se trata como consulta exitosa.
- Entrega **al menos una vez**: emisión, cola aceptada, recepción y trabajo terminado son
  hechos distintos. Una caída tras emitir y antes de persistir puede repetir un aviso.
  La confirmación por ID es idempotente. No se eliminan pendientes por un fallo al avisar.
- Se guardan referencias, tiempos Unix en segundos e IDs; no cuerpos privados ni tokens. La cola mantiene
  confirmaciones para deduplicar; esta versión no poda automáticamente el estado. Monitoriza
  su tamaño en usos prolongados. No borres el estado para resolver un error de autenticación.
- Archivos: sólo `.md` regulares, sin enlaces simbólicos, hasta 1 MiB; cabecera simple del
  protocolo con `para` y `estado: pendiente`. Se espera estabilidad entre dos observaciones.
  Eso no demuestra que una escritura pausada haya terminado: publica por rename cuando
  controles el emisor. No se anuncian ediciones del mismo mensaje como eventos nuevos.
- Slack: paginación persistida, cursores decimales exactos, intervalo por método y errores
  visibles; 429 conserva `Retry-After` entre rearmes. Al primer arranque, cero segundos de
  recuperación significa «desde ahora». Después se usa el cursor guardado; una página a
  medias se retoma. La autenticación se verifica de nuevo si cambia el archivo del token.
- Hilos: `seguir-hilo` permite padres antiguos sin depender de los últimos mensajes del canal.
  `seguir_nuevos = true` registra los padres nuevos observados; no descubre todos los hilos
  históricos. El seguimiento permanece tras rearmar; usa `dejar-hilo` cuando corresponda.
  El tiempo de recorrido crece con los hilos registrados. El historial disponible depende
  de Slack y de tu plan/permisos; no se promete recuperar mensajes que Slack ya no ofrece.

## Verificar tu instalación

Con dos mensajes ficticios, comprueba cada paso: archivo creado → evento persistido → aviso
al arnés → acuse del destinatario. No basta con ver un proceso activo. Prueba también un
mensaje durante el rearme, una parada y un reinicio sin confirmar. Para Slack, agrega una
respuesta a un padre antiguo registrado. Los ensayos unitarios no prueban el despertar de
una versión particular de tu arnés: repite esa medición en tu instalación.
