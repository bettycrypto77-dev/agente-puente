# Slack opcional: configuración breve

El puente funciona sin Slack. Para añadir avisos, usa **tu workspace y un bot propio por agente**;
no necesitas copiar la infraestructura de nadie.

1. Crea una app en [Slack Apps](https://api.slack.com/apps). En **OAuth & Permissions** agrega
   `channels:history` para canales públicos o `groups:history` para privados. Instálala en tu
   workspace e invita su bot al canal que usarás. Este lector no necesita publicar mensajes.
2. Guarda el **Bot User OAuth Token** en un archivo privado, por ejemplo
   `~/.config/puente/agente-b.token`, mediante tu editor; aplica `chmod 600` a ese archivo.
   No lo pongas en el chat, en comandos del historial ni en el repositorio.
3. Ejecuta `make install-escucha` (Python 3.11+, Linux/macOS). Copia
   `examples/escucha.toml.example` a `~/.config/puente/escucha.toml` y edita:
   `agente`, `raiz`, `slack.habilitado = true`, `token_archivo`, el ID del bot en `usuario`
   y el ID de tu canal en `canales`. Puedes copiar los IDs desde Slack; no son el nombre visible.
   Si sólo quieres Slack, pon `archivos = false`.
4. Comprueba y escucha desde una tarea de tu propio arnés:

   ```sh
   puente-escucha comprobar-slack
   puente-escucha esperar --duracion 15m
   ```

   El lector **comprueba que el token corresponde al bot configurado**. Elige el
   [adaptador del arnés](adaptadores.md): imprimir una línea no despierta a todos los agentes.
5. Para un hilo: `puente-escucha seguir-hilo --canal ID_CANAL --padre TS_PADRE`.
   Comprueba sus permisos con `comprobar-slack --canal ID_CANAL --padre TS_PADRE`.
   Al terminar: `puente-escucha detener`, seguido de `estado` para comprobar el cierre.

**Límites:** el lector respeta `Retry-After`; deja el intervalo conservador del ejemplo hasta
conocer los límites de tu app. Los permisos de canal no sustituyen la prueba del hilo.
Si hay un error de permisos, corrige tu app; no uses el token personal del usuario ni el de otro
agente. El seguimiento sólo cubre los hilos registrados (o padres nuevos si activas esa opción).

Fuentes: [history](https://docs.slack.dev/reference/methods/conversations.history/),
[replies](https://docs.slack.dev/reference/methods/conversations.replies/),
[límites](https://docs.slack.dev/apis/web-api/rate-limits/). Consultadas el 20-09-2026.
Recuperación, confirmaciones y arranque: [manual de escucha](escucha.md).
