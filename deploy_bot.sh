#!/bin/bash

# Функция для проверки наличия команды
command_exists() {
    type "$1" &> /dev/null ;
}

# Установка jq, если он не установлен
if ! command_exists jq ; then
    sudo apt install -y jq
fi

# Читаем файл конфигурации
BOT_TOKEN=$(jq -r '.BOT_TOKEN' setup_config.json)
DOMAIN_OR_IP=$(jq -r '.DOMAIN_OR_IP' setup_config.json)
ADMINS=$(jq -r '.ADMINS | join(",")' setup_config.json)

# Устанавливаем режим noninteractive для установки пакетов
export DEBIAN_FRONTEND=noninteractive

# Обновляем пакеты
sudo apt update
sudo apt upgrade -y

# Устанавливаем необходимые пакеты
sudo apt install -y python3 python3-pip python3-venv nginx certbot

# Создаем виртуальное окружение и устанавливаем зависимости
python3 -m venv crabtash
source crabtash/bin/activate
pip install -r requirements.txt

# Обновляем конфигурацию бота
sed -i "s/BOT_TOKEN = .*/BOT_TOKEN = '$BOT_TOKEN'/g" /data/config.py
sed -i "s/WEBHOOK_HOST = .*/WEBHOOK_HOST = 'https:\/\/$DOMAIN_OR_IP'/g" /data/config.py
sed -i "s/ADMINS = .*/ADMINS = [$ADMINS]/g" /data/config.py

# Получаем SSL-сертификат
sudo certbot certonly --standalone --preferred-challenges http -d $DOMAIN_OR_IP

# Настраиваем Nginx
sudo tee /etc/nginx/sites-available/default <<EOF
server {
    listen 80;
    server_name $DOMAIN_OR_IP;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name $DOMAIN_OR_IP;

    ssl_certificate /etc/letsencrypt/live/$DOMAIN_OR_IP/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN_OR_IP/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/bot /etc/nginx/sites-enabled/
sudo systemctl restart nginx

# Запускаем бота
python3 main.py --port 8000
