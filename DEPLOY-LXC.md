# Despliegue en LXC de Proxmox

## Requisitos previos

1. Crear un contenedor LXC en Proxmox:
   - **Template**: Ubuntu 22.04 o Debian 12
   - **Recursos mínimos**: 2 cores, 2GB RAM, 10GB disco
   - **Features**: Habilitar `nesting` si quieres usar Docker (opcional)

2. Conectar al contenedor:
   ```bash
   pct enter <ID_DEL_LXC>
   # o
   ssh root@<IP_DEL_LXC>
   ```

## Despliegue rápido

```bash
# 1. Clonar o copiar el proyecto al LXC
cd /root
git clone <tu-repo> infoguia
cd infoguia

# 2. Ejecutar el script de despliegue
chmod +x deploy-lxc.sh
./deploy-lxc.sh
```

El script automáticamente:
- ✅ Instala PostgreSQL, Redis, Nginx
- ✅ Crea la base de datos y usuario
- ✅ Configura entorno virtual de Python
- ✅ Crea servicios systemd
- ✅ Configura Nginx como reverse proxy
- ✅ Genera contraseña aleatoria para el panel

## Acceso al panel

Después del despliegue, accede desde tu navegador:
```
http://<IP_DEL_LXC>
```

Credenciales:
- **Usuario**: `admin`
- **Contraseña**: La que generó el script (ver output del despliegue)

## Comandos útiles

### Ver estado de servicios
```bash
systemctl status infoguia-api
systemctl status infoguia-worker
systemctl status infoguia-scheduler
```

### Ver logs en tiempo real
```bash
# API
journalctl -u infoguia-api -f

# Worker (scraper)
journalctl -u infoguia-worker -f

# Scheduler
journalctl -u infoguia-scheduler -f
```

### Reiniciar servicios
```bash
systemctl restart infoguia-api
systemctl restart infoguia-worker
systemctl restart infoguia-scheduler
```

### Acceder a la base de datos
```bash
sudo -u postgres psql -d infoguia
```

### Ver empresas scrapeadas
```bash
sudo -u postgres psql -d infoguia -c "SELECT count(*) FROM company;"
```

## Actualizaciones

```bash
cd /opt/infoguia
git pull
source venv/bin/activate
pip install -r requirements.txt
systemctl restart infoguia-api infoguia-worker infoguia-scheduler
```

## Configuración adicional

### HTTPS con Let's Encrypt (opcional)

```bash
apt install certbot python3-certbot-nginx
certbot --nginx -d tu-dominio.com
```

### Backup automático

Crear cron job:
```bash
crontab -e

# Agregar (backup diario a las 3 AM):
0 3 * * * sudo -u postgres pg_dump infoguia > /backups/infoguia-$(date +\%Y\%m\%d).sql
```

### Monitoreo

Ver consumo de recursos:
```bash
htop
iostat
df -h
```

## Troubleshooting

### El worker no procesa jobs
```bash
# Verificar que Redis está corriendo
redis-cli ping

# Verificar que no hay bloqueos
redis-cli GET "blocked:infoguia.com"

# Forzar ejecución de seeds
sudo -u postgres psql -d infoguia -c "UPDATE seed SET next_run_at = NOW();"
```

### La API no responde
```bash
# Ver logs
journalctl -u infoguia-api -n 50

# Verificar que PostgreSQL está corriendo
systemctl status postgresql

# Verificar conexiones
sudo -u postgres psql -d infoguia -c "SELECT 1;"
```

### Error de permisos
```bash
chown -R www-data:www-data /opt/infoguia
chown -R www-data:www-data /data
```

## Arquitectura

```
┌─────────────────────────────────────────┐
│           LXC Container                 │
│                                         │
│  ┌──────────┐      ┌──────────────┐    │
│  │  Nginx   │──────│   API (API)  │    │
│  │  :80     │      │    :8000     │    │
│  └──────────┘      └──────────────┘    │
│                            │           │
│                            ▼           │
│  ┌──────────────────────────────────┐  │
│  │         PostgreSQL               │  │
│  │         :5432                    │  │
│  └──────────────────────────────────┘  │
│                            ▲           │
│                            │           │
│  ┌──────────────────────────────────┐  │
│  │           Redis                  │  │
│  │           :6379                  │  │
│  └──────────────────────────────────┘  │
│                            ▲           │
│                            │           │
│  ┌──────────┐      ┌──────────────┐    │
│  │ Worker   │──────│  Scheduler   │    │
│  │(scraper) │      │  (cron-like) │    │
│  └──────────┘      └──────────────┘    │
└─────────────────────────────────────────┘
```

## Recursos recomendados

- **Mínimo**: 2 cores, 2GB RAM, 10GB disco
- **Recomendado**: 4 cores, 4GB RAM, 20GB disco
- **Producción**: 4 cores, 8GB RAM, 50GB SSD

El scraper usa ~200-300MB de RAM con 2 workers.
