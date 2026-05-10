# ── Frontend — Vite dev server con hot-reload ────────────────────────────────
FROM node:22-alpine

WORKDIR /app

# Habilitar pnpm (gestor que usa el proyecto)
RUN corepack enable && corepack prepare pnpm@latest --activate

# Instalar dependencias primero (cacheable si package.json no cambia)
COPY package.json pnpm-lock.yaml ./
# pnpm 10 bloquea paquetes no aprobados aunque estén en onlyBuiltDependencies cuando
# el lockfile no tiene el resolution step. --ignore-scripts + rebuild de nativos es la
# solución más robusta para CI/Docker.
RUN pnpm install --frozen-lockfile --ignore-scripts
# Reconstruir paquetes que necesitan compilación nativa (esbuild lo usa Vite, oxide lo usa Tailwind v4)
RUN pnpm rebuild esbuild @tailwindcss/oxide || true

# Copiar el código fuente (será sobreescrito por el volumen en dev)
COPY . .

EXPOSE 5173

# Levantar Vite escuchando en todas las interfaces para ser accesible fuera del contenedor
CMD ["pnpm", "dev", "--host", "0.0.0.0"]
