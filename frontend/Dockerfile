# JudiFiles — frontend (React + Vite, build estático em Nginx)
#
# Build a partir da RAIZ do repositório (contexto raiz):
#   docker build -t judifiles-frontend -f frontend/Dockerfile .
#
# O nginx.conf entra como template (envsubst do próprio nginx): as vars
# CLIENT_MAX_BODY_SIZE e API_READ_TIMEOUT podem ser sobrevidas por
# --build-arg (compose faz isso).

FROM node:20-alpine AS build

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --include=dev

COPY frontend/ ./
RUN npm run build

FROM nginx:alpine AS runtime

ARG CLIENT_MAX_BODY_SIZE=100m
ARG API_READ_TIMEOUT=120s
ENV CLIENT_MAX_BODY_SIZE=${CLIENT_MAX_BODY_SIZE} \
    API_READ_TIMEOUT=${API_READ_TIMEOUT}

COPY --from=build /app/dist /usr/share/nginx/html
# /etc/nginx/templates/*.template -> envsubst -> /etc/nginx/conf.d/
COPY frontend/nginx.conf /etc/nginx/templates/default.conf.template

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
