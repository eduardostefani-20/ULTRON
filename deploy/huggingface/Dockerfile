# Inicializador do ULTRON para Hugging Face Spaces (Docker).
# Esta imagem NÃO contém o código do ULTRON: ele é baixado do repositório privado do GitHub quando o
# contêiner inicia (bootstrap.sh), usando o token guardado nos segredos do Space.
FROM node:22-bookworm-slim AS node

FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates util-linux \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
# dependências Python (lista pública, sem código do ULTRON)
COPY requirements.txt /opt/ultron-requirements.txt
RUN pip install --no-cache-dir -r /opt/ultron-requirements.txt
COPY bootstrap.sh /opt/bootstrap.sh
RUN chmod 755 /opt/bootstrap.sh
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ULTRON_ENV=production HOME=/tmp/home
EXPOSE 7860
CMD ["/opt/bootstrap.sh"]
