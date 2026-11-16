# Web 前端构建 + nginx 运行镜像
#
# 前端与接口同源(浏览器访问 /api/v1),因此不需要 VITE_API_BASE,
# 用 web/src/api/http.ts 的默认值 /api/v1 即可。
# L-3:两个 base 都钉「补丁版本 + 多架构 index digest」,registry 上同名 tag 被重推也不影响构建
FROM node:22.23.5-alpine@sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a AS build

# 国内服务器默认走 npmmirror;可用 --build-arg NPM_REGISTRY=... 覆盖
ARG NPM_REGISTRY=https://registry.npmmirror.com

WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm config set registry "${NPM_REGISTRY}" \
 && npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# E-6①:非 root 运行。`nginx-unprivileged` 默认以 nginx(uid 101)启动,
# 因此**容器内监听 8080/8443**,由 compose 做 `80→8080`、`443→8443` 的宿主机映射
# (见 deploy/docker-compose.yml.tmpl 与 deploy/README.md)。
# 好处:即使 nginx 被拿下,也不是容器里的 uid 0,拿不到 NET_BIND_SERVICE。
FROM nginxinc/nginx-unprivileged:1.27.5-alpine@sha256:65e3e85dbaed8ba248841d9d58a899b6197106c23cb0ff1a132b7bfe0547e4c0

# 只放静态产物;nginx 配置由 compose 把宿主机 conf.d 挂进来
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080 8443
