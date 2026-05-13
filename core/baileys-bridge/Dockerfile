FROM node:20-alpine

WORKDIR /app

# Install deps first to leverage Docker layer cache.
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund

# App source
COPY server.js ./
COPY src ./src

# Auth dir is mounted from a Docker volume; create it empty so the
# container can write even if the volume is fresh.
RUN mkdir -p /app/auth_info

EXPOSE 7755

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget -q -O - http://localhost:7755/healthz || exit 1

CMD ["node", "server.js"]
