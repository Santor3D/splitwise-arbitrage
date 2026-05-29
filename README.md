# Splitwise Arbitrage

Bot para ordenar saldos entre los grupos de Splitwise `Office Servicios` y `Office`.

Flujo diario:

1. En `Office Servicios`, mueve el saldo neto de cada dummy al responsable configurado.
2. Los dummies de `Sensus3D` se reparten entre `Reski` y `Gordo`.
3. `dummyMeli` se mueve a `Fran`.
4. Despues mueve el saldo neto de `Gordo`, `Reski`, `Fran` y `Teo` desde `Office Servicios` hacia `Office`, dejando el resultado consolidado en `Office`.

## Setup

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Edita `.env`:

- `SPLITWISE_API_KEY`: API key o token OAuth2 bearer.
- `SPLITWISE_AUTH_MODE=api_key`: usa la API key como bearer token.
- `SPLITWISE_CONSUMER_KEY` y `SPLITWISE_CONSUMER_SECRET`: quedan preparados para un flujo OAuth2 futuro.
- `SPLITWISE_OFFICE_GROUP_ID` y `SPLITWISE_OFFICE_SERVICES_GROUP_ID`: ids de los grupos.
- `SPLITWISE_USERS_JSON`: alias interno a id de usuario Splitwise.
- `BUSINESS_GROUPS_JSON`: grupos de negocio, admins/jefes y empleados/dummies.
- `DRY_RUN=true`: deja el bot en modo prueba. Cambialo a `false` cuando el plan sea correcto.

Para descubrir ids de grupos y usuarios:

```powershell
.venv\Scripts\python.exe -m splitwise_arbitrage discover
```

## Uso

Validar configuracion y membresias:

```powershell
.venv\Scripts\python.exe -m splitwise_arbitrage validate
```

Ver el plan sin escribir en Splitwise:

```powershell
.venv\Scripts\python.exe -m splitwise_arbitrage plan
```

Ver solo el arbitraje interno de dummies en `Offi Servicios`:

```powershell
.venv\Scripts\python.exe -m splitwise_arbitrage plan --scope internal
```

Por defecto, ese arbitraje interno se compacta en una sola expense multiusuario. Para ver el detalle historico de pares:

```powershell
.venv\Scripts\python.exe -m splitwise_arbitrage plan --scope internal --granular-internal
```

El arbitraje entre `Offi Servicios` y `Office` tambien se compacta en una expense por grupo. Para ver el detalle por pares:

```powershell
.venv\Scripts\python.exe -m splitwise_arbitrage plan --scope cross --granular-cross
```

Ver balances de los dos grupos configurados:

```powershell
.venv\Scripts\python.exe -m splitwise_arbitrage balances
```

Ejecutar una vez. Si `DRY_RUN=true`, solo imprime el plan:

```powershell
.venv\Scripts\python.exe -m splitwise_arbitrage run
```

Ejecutar solo el arbitraje interno de dummies:

```powershell
.venv\Scripts\python.exe -m splitwise_arbitrage run --scope internal --apply
```

Forzar escritura aunque `.env` tenga `DRY_RUN=true`:

```powershell
.venv\Scripts\python.exe -m splitwise_arbitrage run --apply
```

Mantener un proceso corriendo y ejecutar todos los dias a `SCHEDULE_TIME`:

```powershell
.venv\Scripts\python.exe -m splitwise_arbitrage schedule
```

Tambien podes instalar una tarea diaria de Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_task.ps1 -TaskName SplitwiseArbitrage -At 06:00
```

## Seguridad operativa

Cada corrida que escribe en Splitwise guarda un estado pendiente en `STATE_FILE`. Si falla a mitad de camino, la siguiente corrida intenta terminar las operaciones faltantes antes de planificar algo nuevo. Las operaciones incluyen una clave de idempotencia en `details` para evitar duplicados cuando Splitwise ya recibio una operacion pero el proceso se corto antes de registrar el resultado.
