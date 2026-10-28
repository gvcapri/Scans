# JudiFiles — frontend (React + Vite, build estático em Nginx)
#
# Construir e rodar:
#   docker build -t judifiles-frontend -f frontend/Dockerfile .
#   docker run -p 80:80 judifiles-frontend
#
FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --include=dev

COPY frontend/ .
RUN npm run build

FROM nginx:alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
