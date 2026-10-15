# 控制台前端：构建静态文件，由 nginx 提供，并把 /api 转发给控制台后端
FROM node:20-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
# npm 11 会在 lockfile 里留下一条没有版本号的跨平台可选依赖（rolldown 的 macOS x64 绑定），
# 镜像内的 npm 无法解析，安装前先剔除这类残缺条目
RUN node -e "const f='package-lock.json',l=require('./'+f);for(const[k,v]of Object.entries(l.packages))if(k&&!v.version&&!v.link)delete l.packages[k];require('fs').writeFileSync(f,JSON.stringify(l,null,2))" \
 && npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
