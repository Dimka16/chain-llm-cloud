#!/bin/bash
set -euxo pipefail

apt-get update
apt-get install -y git ca-certificates curl docker.io docker-compose-plugin

systemctl enable docker
systemctl start docker

usermod -aG docker ubuntu || true

cd /home/ubuntu
if [ ! -d chain-llm-cloud ]; then
  git clone https://github.com/Dimka16/chain-llm-cloud.git
else
  cd chain-llm-cloud && git pull || true
fi

cd /home/ubuntu/chain-llm-cloud/services/service-b
mkdir -p logs

docker compose up -d --build

docker exec -it ollama-b ollama pull phi3:mini || true
