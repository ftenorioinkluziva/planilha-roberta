# Hetzner Deploy Runbook

Este documento registra o processo operacional usado nos projetos migrados para o servidor Hetzner principal. Nao incluir chaves privadas, tokens, senhas ou valores de `.env` neste arquivo.

## Servidores

- Servidor principal: `root@135.181.47.220`
- Chave SSH local padrao: `~/.ssh/hetzner`
- Servidor antigo migrado/desativado: `root@89.167.106.38`

Comando padrao:

```bash
ssh -i ~/.ssh/hetzner root@135.181.47.220
```

No Windows/PowerShell:

```powershell
ssh -i $HOME\.ssh\hetzner root@135.181.47.220
```

## Padrao De Deploy

Para projetos simples com Docker Compose:

- Diretorio remoto padrao: `/root/<nome-do-projeto>`
- Rede Docker compartilhada com Nginx Proxy Manager: `npm_default`
- O compose do projeto deve declarar:

```yaml
networks:
  npm_default:
    external: true
```

O container deve entrar na rede `npm_default` para que o Nginx Proxy Manager consiga encaminhar trafego usando o nome do container.

## Projeto Planilha Roberta / Gerador XML

Estado validado no servidor principal:

- Diretorio: `/root/planilha-roberta`
- Compose: `/root/planilha-roberta/docker-compose.yml`
- Container: `gerador-xml-app`
- Host NPM: `xml.blackboxinovacao.com.br`
- Porta interna: `8501`

O GitHub Actions deste projeto deve usar:

```bash
APP_DIR="/root/planilha-roberta"
```

Secrets esperados no GitHub:

```text
HETZNER_HOST=135.181.47.220
HETZNER_USER=root
HETZNER_SSH_KEY=<private key, nao registrar em arquivo>
```

## GitHub Actions

Fluxo usado:

1. Rodar checks/testes.
2. Gerar pacote `.tar.gz` ignorando `.git`, `.venv` e caches.
3. Enviar pacote por `scp`.
4. Extrair no `APP_DIR`.
5. Garantir rede Docker `npm_default`.
6. Rodar `docker compose up -d --build`.

Trecho base:

```bash
APP_DIR="/root/<nome-do-projeto>"
mkdir -p "$APP_DIR"

tar -xzf /tmp/<nome-do-projeto>.tar.gz -C "$APP_DIR"
rm -f /tmp/<nome-do-projeto>.tar.gz

cd "$APP_DIR"
docker network inspect npm_default >/dev/null 2>&1 || docker network create npm_default
docker compose up -d --build
```

## Nginx Proxy Manager

NPM roda no servidor principal e usa a rede `npm_default`.

Itens a validar para cada novo projeto:

- Container esta na rede `npm_default`.
- Nome do upstream no NPM e o nome do container batem.
- Porta interna configurada corretamente.
- SSL emitido apos DNS apontar para `135.181.47.220`.
- Teste HTTP/HTTPS com `curl -I`.

Comandos uteis:

```bash
docker ps
docker network inspect npm_default
docker exec npm-app-1 nginx -t
docker exec npm-app-1 nginx -s reload
```

## Checklist De Migracao

1. Inventariar containers no servidor origem.
2. Identificar compose, env files, volumes e portas.
3. Confirmar arquitetura do servidor destino:

```bash
uname -m
```

O servidor principal e ARM64. Imagens antigas apenas `linux/amd64` precisam ser rebuildadas no destino ou publicadas multi-arch.

4. Copiar codigo/configuracao sem expor segredos no chat/log.
5. Criar compose no destino usando `npm_default`.
6. Buildar no destino.
7. Subir primeiro sem cortar DNS.
8. Testar pelo NPM internamente:

```bash
docker exec npm-app-1 curl -fsS http://<container>:<porta>/
```

9. Criar proxy host no NPM.
10. Alterar DNS para `135.181.47.220`.
11. Emitir SSL.
12. Validar HTTPS publico.
13. Parar containers equivalentes no servidor antigo.
14. Manter servidor antigo por cerca de 24h antes de destruir.

## Cuidados Operacionais

- Nao rodar dois bots Telegram com o mesmo token ao mesmo tempo. Isso causa conflito `getUpdates`.
- Nao duplicar schedulers/cron durante corte, exceto fallback temporario consciente.
- Durante propagacao de DNS, se usuarios ainda cairem no IP antigo, podem ver `502` caso o upstream antigo esteja parado.
- Antes de destruir servidor antigo, pare os containers e observe por algumas horas.
- Para diagnostico de DNS:

```bash
getent ahostsv4 <dominio>
curl -I https://<dominio>
```

No PowerShell:

```powershell
Resolve-DnsName <dominio> -Type A
```

## Projetos Migrados No Corte

Dominios migrados do servidor `89.167.106.38` para `135.181.47.220`:

- `f1.blackboxinovacao.com.br` -> `f1-blog:3000`
- `sami.blackboxinovacao.com.br` -> `sami-app:3000`
- `hotels.blackboxinovacao.com.br` -> `omnibees-api:8000`

Servicos Omnibees:

- `omnibees-api`: pode rodar durante preparacao.
- `omnibees-bot` e `omnibees-cron`: subir apenas no corte para evitar duplicidade.

## Verificacoes Pos-Deploy

```bash
docker ps
docker logs --tail 100 <container>
docker compose ps
curl -I https://<dominio>
df -h /
free -h
docker system df
```

Build cache Docker pode ser limpo depois que tudo estiver estavel:

```bash
docker builder prune -af
```

Use esse comando com cuidado: ele remove cache de build, mas nao remove imagens/container ativos.
