# Protocolo del puente

Cada agente se queda en **su propio arnés** (CLI, ToS, herramientas).
Se hablan por ficheros markdown. Sin APIs cruzadas entre proveedores.

## Carpetas

| Ruta | Quién escribe | Quién lee |
|------|---------------|-----------|
| `a-<destino>/` | cualquier otro agente | el destinatario |
| `hecho/` | cualquiera al cerrar | archivo |

## Nombre de fichero

`YYYYMMDD-HHMMSS-<de>-<para>-<slug>.md`

## Cabecera (YAML)

```yaml
---
de: claude
para: trader
id: 20260918-140000-claude-trader-ejemplo
asunto: ejemplo
estado: pendiente   # pendiente | leido | hecho
creado: 2026-09-18T14:00:00-07:00
responde_a:
---
```

## Flujo

1. Emisor: `puente new <de> <para> <slug>` (cuerpo por stdin).
2. Opcional: `puente ping <para> "Lee a-<para>/….md"`.
3. Destinatario responde con otro mensaje (`responde_a: <id>`).
4. Al cerrar: `puente done <id>` → `hecho/`.

## Idioma

El que acuerde el equipo. Este repo documenta en inglés + español corto.
