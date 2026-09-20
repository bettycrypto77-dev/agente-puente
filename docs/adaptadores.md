# Entregar el aviso al arnés

El lector y el arnés hacen trabajos distintos. El lector detecta referencias; el arnés debe
provocar un turno. Una línea en un registro no acredita que el agente la recibió.

## Claude Code y Grok Build

Configura `[adaptador] tipo = "monitor"`. Ejecuta `puente-escucha iniciar --duracion 15m`
desde la herramienta Monitor del propio arnés. Los lotes salen como `ACTION_REQUIRED: {JSON}`;
`DONE` queda para el fin de escucha, con motivo y código. No se usa `FAILED` para mensajes
correctos. El agente confirma los IDs después de recibirlos.

Al 20-09-2026 los ensayos locales del método dieron recepción de canal e hilo en ambos arneses;
Grok también pasó dos avisos `ACTION_REQUIRED` manteniendo vivo el proceso entre ellos.
La disponibilidad y semántica de Monitor puede variar: verifica dos avisos, no sólo el primero.

## Antigravity

Configura `tipo = "json"` y ejecuta `puente-escucha esperar --duracion 15m` como tarea en
segundo plano del propio arnés. Al detectar, el proceso emite un lote y termina. La notificación
de finalización despierta al agente; éste confirma y rearma con `puente-escucha esperar`,
sin renovar duración. Si la autorización venció o fue cancelada, no rearmes automáticamente.

Al 20-09-2026 los ensayos mostraron que un bucle infinito guardaba stdout sin despertar;
terminar la tarea sí produjo el turno, tanto con archivo como con Slack. Este paquete no
invoca otro proveedor ni configura sus credenciales.

## Codex

Configura `tipo = "codex"` y `hilo = "UUID_DE_TU_SESION"`.
El receptor usa por defecto `modelo = "gpt-5.6-sol"` y `esfuerzo = "low"`.
Ambos son configurables según los modelos y esfuerzos disponibles en tu cuenta.
Mantén abierta esa sesión y ejecuta `iniciar --duracion 15m` como tarea local supervisada.
El adaptador llama `codex queue --thread ... --message ...` con argumentos separados,
sin shell y sin trasladar el cuerpo del mensaje. Sólo encola referencias; el receptor usa
sus herramientas para leerlas y confirma el evento con su configuración de escucha.

Al 20-09-2026 se midió con `gpt-5.6-sol` y esfuerzo bajo el circuito completo:
recepción desde reposo, lectura local, acuse contrastado y confirmación persistida.
Con la CLI cerrada, la cola esperó hasta reabrir la sesión.
El lector funciona por una duración explícita; no necesita un modelo consultando en bucle.
La medición no demuestra que este modelo consuma menos cuota que todos los demás.
`chatgpt-web/*` es opcional: en las pruebas del 20-09-2026 hubo lecturas directas correctas
y rechazos de herramientas al recibir avisos; no se considera validado ese circuito.
El adaptador no instala esa integración ni modifica la configuración global de Codex.
No se suministra UUID, cuenta, túnel ni clave de una instalación ajena.

## Apps de escritorio (por ejemplo, Grok Bot)

Si tu app ofrece un listener de Slack, puedes usarlo como alternativa al lector de este paquete.
Registra por separado mensajes de canal y respuestas en hilo; mantén **la misma rutina** hasta
el cierre explícito. No la retires al recibir un mensaje de control o retorno. Exige un acuse
por archivo y una duración máxima; retira sólo la rutina creada para esa escucha.

Al 20-09-2026 una corrida falló en hilo y otra pasó padre/hilo/control con la rutina estable;
no se demostró la causa de la diferencia. Comprueba esas tres fases en tu app. El ping de
preparación puede usar su CLI oficial (por ejemplo `gbot send` cuando esté disponible), pero
no se automatiza ni se configura aquí: no existe un contrato universal entre apps de escritorio.
El conector debe usar la identidad autorizada; no publiques como la cuenta personal del usuario
para suplir un bot ausente.

## Criterio de aceptación

Registrar una detección o aceptar una cola no equivale a despertar al destinatario. La prueba
pasa al obtener un acuse con la referencia exacta sin intervención manual durante esa fase.
Conserva tiempos distintos para detección, emisión y respuesta. No atribuyas a stdout un turno
que en realidad provocó un ping. Los ensayos anteriores respaldan el método, no sustituyen la
verificación de esta integración en la versión del arnés que instales.
