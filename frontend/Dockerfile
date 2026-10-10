FROM node:26-alpine3.23

WORKDIR /app

RUN chown -R node:node /app

USER node

COPY --chown=node:node package*.json ./
RUN npm install

COPY --chown=node:node . .

EXPOSE 5173
