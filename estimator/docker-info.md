# Docker — comandos esenciales

Todos los comandos se ejecutan desde la carpeta `estimator/`.

---

## Arrancar la aplicación

```bash
# Primera vez (o cuando cambie pyproject.toml / Dockerfile)
docker compose up --build

# El resto de veces
docker compose up
```

Cuando veas estas líneas, todo está listo:

```
estimator  | INFO: Application startup complete.
streamlit  | You can now view your Streamlit app in your browser.
```

- FastAPI (backend): http://localhost:8000/docs
- Streamlit (interfaz): http://localhost:8501

---

## Parar la aplicación

```bash
# Parar sin borrar nada (puedes volver a hacer `up`)
docker compose down

# Parar Y borrar las imágenes construidas (rebuild limpio)
docker compose down --rmi local
```

---

## Ver logs

```bash
# Logs de todos los servicios en tiempo real
docker compose logs -f

# Solo el backend FastAPI
docker compose logs -f estimator

# Solo Streamlit
docker compose logs -f streamlit
```

Sal con `Ctrl + C`.

---

## Reconstruir tras cambios

| Qué cambiaste | Comando |
|---|---|
| Código Python (`app/`, `streamlit_app.py`) | `docker compose up` (el volumen se monta en vivo, sin rebuild) |
| Dependencias (`pyproject.toml`) | `docker compose up --build` |
| `Dockerfile` | `docker compose up --build` |

---

## Comandos de diagnóstico

```bash
# Ver qué contenedores están corriendo
docker compose ps

# Ver cuánta CPU/memoria consume cada contenedor
docker stats

# Abrir una terminal dentro del contenedor del backend
docker compose exec estimator bash
```

---

## Flujo habitual de trabajo

```bash
# 1. Situarse en la carpeta del proyecto
cd estimator

# 2. Arrancar (primera vez: con --build)
docker compose up --build

# 3. Abrir http://localhost:8501 en el navegador

# 4. Editar código → los cambios se reflejan automáticamente
#    (sin necesidad de reiniciar)

# 5. Al terminar
docker compose down
```

---

## Errores frecuentes

**`Error: .env file not found`**
→ Copia el fichero de ejemplo: `cp .env.example .env` y añade tu API key.

**Puerto 8000 o 8501 ya en uso**
→ Otro proceso ocupa ese puerto. Para encontrarlo:
```bash
lsof -i :8000   # o :8501
kill -9 <PID>
```

**Cambié `pyproject.toml` pero el contenedor no instala las nuevas dependencias**
→ Necesitas rebuild: `docker compose up --build`
