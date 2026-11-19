#!/bin/bash
set -e

# InfoGuia - Script de despliegue para LXC
echo "🚀 Iniciando despliegue de InfoGuia..."

# Actualizar sistema
echo "📦 Actualizando sistema..."
apt update && apt upgrade -y

# Instalar dependencias
echo "📦 Instalando dependencias..."
apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    postgresql \
    redis-server \
    nginx \
    git \
    curl

# Configurar PostgreSQL
echo "🗄️ Configurando PostgreSQL..."
sudo -u postgres psql -c "CREATE USER infoguia WITH PASSWORD 'infoguia';" || echo "Usuario ya existe"
sudo -u postgres psql -c "CREATE DATABASE infoguia OWNER infoguia;" || echo "Base de datos ya existe"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE infoguia TO infoguia;"

# Configurar Redis
echo "🔴 Configurando Redis..."
systemctl enable redis-server
systemctl start redis-server

# Crear directorio de la aplicación
echo "📁 Configurando aplicación..."
APP_DIR="/opt/infoguia"
mkdir -p $APP_DIR
cp -r ./* $APP_DIR/
cd $APP_DIR

# Crear entorno virtual
echo "🐍 Creando entorno virtual..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Configurar variables de entorno
echo "⚙️ Configurando variables de entorno..."
if [ ! -f .env ]; then
    cp .env.example .env
    # Generar contraseña aleatoria para el panel
    PANEL_PASS=$(openssl rand -base64 12)
    sed -i "s/PANEL_PASSWORD=.*/PANEL_PASSWORD=$PANEL_PASS/" .env
    echo "📝 Contraseña del panel generada: $PANEL_PASS"
else
    echo "📝 Usando .env existente"
fi

# Crear directorios de datos
mkdir -p /data/raw

# Configurar permisos
chown -R www-data:www-data /data
chmod -R 755 /data

# Crear servicios systemd
echo "🔧 Configurando servicios systemd..."

# Servicio API
cat > /etc/systemd/system/infoguia-api.service << 'EOF'
[Unit]
Description=InfoGuia API Server
After=network.target postgresql.service redis-server.service
Requires=postgresql.service redis-server.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/infoguia
Environment="PATH=/opt/infoguia/venv/bin"
EnvironmentFile=/opt/infoguia/.env
ExecStart=/opt/infoguia/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Servicio Worker
cat > /etc/systemd/system/infoguia-worker.service << 'EOF'
[Unit]
Description=InfoGuia Worker
After=network.target postgresql.service redis-server.service
Requires=postgresql.service redis-server.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/infoguia
Environment="PATH=/opt/infoguia/venv/bin"
EnvironmentFile=/opt/infoguia/.env
ExecStart=/opt/infoguia/venv/bin/python -m app.worker
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Servicio Scheduler
cat > /etc/systemd/system/infoguia-scheduler.service << 'EOF'
[Unit]
Description=InfoGuia Scheduler
After=network.target postgresql.service redis-server.service
Requires=postgresql.service redis-server.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/infoguia
Environment="PATH=/opt/infoguia/venv/bin"
EnvironmentFile=/opt/infoguia/.env
ExecStart=/opt/infoguia/venv/bin/python -m app.scheduler
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Configurar Nginx
echo "🌐 Configurando Nginx..."
cat > /etc/nginx/sites-available/infoguia << 'EOF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    location /static/ {
        alias /opt/infoguia/app/static/;
        expires 1d;
    }
}
EOF

ln -sf /etc/nginx/sites-available/infoguia /etc/nginx/sites-enabled/infoguia
rm -f /etc/nginx/sites-enabled/default

# Recargar Nginx
nginx -t
systemctl restart nginx

# Inicializar base de datos
echo "🗄️ Inicializando base de datos..."
cd /opt/infoguia
source venv/bin/activate
python3 -c "from app import db; db.init_db()"

# Habilitar y iniciar servicios
echo "▶️ Iniciando servicios..."
systemctl daemon-reload
systemctl enable infoguia-api infoguia-worker infoguia-scheduler
systemctl start infoguia-api infoguia-worker infoguia-scheduler

# Obtener IP del contenedor
IP=$(hostname -I | awk '{print $1}')

# Mostrar información final
echo ""
echo "✅ Despliegue completado!"
echo ""
echo "📍 Acceso al panel:"
echo "   URL: http://$IP"
echo "   Usuario: admin"
echo "   Contraseña: $(grep PANEL_PASSWORD .env | cut -d'=' -f2)"
echo ""
echo "🔍 Estado de servicios:"
echo "   systemctl status infoguia-api"
echo "   systemctl status infoguia-worker"
echo "   systemctl status infoguia-scheduler"
echo ""
echo "📊 Logs:"
echo "   journalctl -u infoguia-api -f"
echo "   journalctl -u infoguia-worker -f"
echo "   journalctl -u infoguia-scheduler -f"
echo ""
echo "🎉 ¡Listo! InfoGuia está corriendo en tu LXC."
