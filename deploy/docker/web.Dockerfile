# Web 前端构建 + nginx 运行镜像
#
# 前端与接口同源(浏览器访问 /api/v1),因此不需要 VITE_API_BASE,
# 用 web/src/api/http.ts 的默认值 /api/v1 即可。
FROM node:22-alpine AS build

# 国内服务器默认走 npmmirror;可用 --build-arg NPM_REGISTRY=... 覆盖
ARG NPM_REGISTRY=https://registry.npmmirror.com

WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm config set registry "${NPM_REGISTRY}" \
 && npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM nginx:1.27-alpine

# 只放静态产物;nginx 配置由 compose 把宿主机 conf.d 挂进来
COPY --from=build /web/dist /usr/share/nginx/html
