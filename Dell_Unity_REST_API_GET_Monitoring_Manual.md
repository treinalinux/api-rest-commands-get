# Dell Unity REST API — Manual completo de GETs para monitoramento

**Saúde · capacidade · performance · segurança · proteção · conectividade**

Edição: 2026-09-02 · Baseline documental: Unity REST API 5.2 · Aplicação-alvo: validar no OE instalado

> Princípio: observar com conta de leitura mínima, TLS validado, payload reduzido e nenhuma alteração de configuração.

## Sumário de estudo

1. Fundamentos, autenticação e segurança TLS
2. Gramática de consultas, filtros e paginação
3. Normalização de saúde e severidade
4. Cartões de GET por domínio
5. Performance histórica e leitura de consultas existentes
6. Arquitetura Zabbix, cadências e correlação
7. Catálogo integral de resource types 5.2
8. Diagnóstico de HTTP/API e fontes

## Como usar este manual

Este manual é uma referência operacional e uma trilha de aprendizagem. Leia primeiro os capítulos de fundamentos e segurança; depois implemente os cartões por domínio. Cada cartão contém o GET-base, campos sugeridos, sinais a observar, interpretação e desenho recomendado no Zabbix.

Escopo: Dell EMC Unity/Unity XT e Unity OE com REST API compatível. A lista de tipos toma a referência 5.2 como baseline. Em um Unity OE 5.4/API 16.0, valide cada campo no API Reference servido pelo próprio array, porque tipos e propriedades podem ter sido adicionados, alterados ou descontinuados.

Regra de segurança: todos os exemplos executáveis usam somente GET. Nenhum comando de criação, alteração ou remoção de objetos foi incluído.

## Modelo mental da API

Coleção: GET /api/types/<resourceType>/instances. Instância: GET /api/instances/<resourceType>/<id>. Alguns singletons, como basicSystemInfo, usam uma URI própria. O API Reference on-array é a autoridade para o seu OE.

Use fields para reduzir payload, filter para trazer apenas objetos relevantes, orderby para ordenação e page/per_page para paginação. Comece sem fields quando estiver descobrindo um tipo; depois selecione apenas propriedades confirmadas no seu array.

A resposta normalmente contém entries, e cada entrada contém content. Não assuma que uma coleção cabe em uma página. Monitore também o próprio coletor: duração, HTTP status, tamanho do payload e idade da última coleta bem-sucedida.

## Preparação segura da sessão curl

Use um certificado de CA confiável. `--insecure`/`-k` serve apenas para laboratório controlado. Não coloque senha em variável, argumento ou histórico; o exemplo deixa o curl solicitá-la. Em automação, use um secret store ou arquivo netrc com permissão 0600 e conta dedicada.

```bash
export UNITY_URL='https://unity.example'
export UNITY_USER='svc_unity_monitor'
export UNITY_CA='/etc/pki/ca-trust/source/anchors/unity-ca.pem'

COOKIE_JAR="$(mktemp)"
chmod 600 "$COOKIE_JAR"
trap 'rm -f "$COOKIE_JAR"' EXIT

# Primeiro GET autenticado: o curl solicita a senha sem gravá-la na linha de comando.
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --user "$UNITY_USER" \
  --cookie-jar "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  "$UNITY_URL/api/types/system/instances?compact=true" | jq .
```

O primeiro request envia Basic Authentication e recebe cookies de sessão. Os GETs seguintes reutilizam o cookie. O cabeçalho `X-EMC-REST-CLIENT: true` identifica o cliente REST. Os GETs desta biblioteca não exigem token CSRF.

## Campos, filtros, ordenação e paginação

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode 'fields=id,name,health' \
  --data-urlencode 'filter=health.value ne 5' \
  --data-urlencode 'orderby=name' \
  --data-urlencode 'page=1' \
  --data-urlencode 'per_page=200' \
  "$UNITY_URL/api/types/disk/instances" | jq .
```

Regras práticas:

- `fields`: peça apenas propriedades confirmadas no on-array API Reference.
- `filter`: use `--data-urlencode`; não concatene valores não confiáveis na URL.
- `orderby`: torna páginas e diffs reprodutíveis.
- `page`/`per_page`: percorra todas as páginas e imponha um limite de segurança.
- `compact=true`: ótimo para descoberta de IDs; não substitui a leitura de campos operacionais.
- Objetos aninhados podem ser filtrados/selecionados por notação de ponto quando o tipo oferece suporte.
- Operadores dependem do tipo/OE; os mais comuns incluem `eq`, `ne`, `gt`, `ge`, `lt`, `le`, `lk` e `in`. Confirme a sintaxe no seu array.

### GET de uma instância

```bash
curl --silent --show-error --fail-with-body --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" -H 'Accept: application/json' \
  -H 'X-EMC-REST-CLIENT: true' \
  "$UNITY_URL/api/instances/lun/<ID_DA_LUN>" | jq .
```

### Extração JSON robusta

```bash
# Conteúdo de todas as entradas da página
jq -c '.entries[]?.content' resposta.json

# Recursos cujo health não é OK (5); // evita falha quando o campo não existe
jq -c '.entries[]?.content | select((.health.value? // 5) != 5)' resposta.json
```

## Normalização de saúde

| Valor | Enum | Leitura operacional |
|---|---|---|
| 0 | UNKNOWN | Sem dados suficientes; trate nodata e duração. |
| 5 | OK | Operação normal. |
| 7 | OK_BUT | Operando, mas há condição que merece atenção. |
| 10 | DEGRADED | Degradação; investigar rapidamente. |
| 15 | MINOR | Falha menor; abrir investigação. |
| 20 | MAJOR | Impacto relevante ou redundância comprometida. |
| 25 | CRITICAL | Risco/impacto crítico; resposta imediata. |
| 30 | NON_RECOVERABLE | Condição não recuperável pelo sistema. |

Nunca trate `UNKNOWN` como OK. Em Zabbix, separe: valor de saúde, descrição, idade da última coleta e `nodata()`.

## Normalização de severidade de alertas/eventos

| Valor | Enum | Leitura operacional |
|---|---|---|
| 8 | OK | Informativo/normal. |
| 7 | INFORMATION | Registrar; normalmente sem pager. |
| 6 | NOTICE | Atenção operacional. |
| 5 | WARNING | Investigar em horário definido. |
| 4 | ERROR | Falha; resposta operacional. |
| 3 | CRITICAL | Alta prioridade. |
| 2 | ALERT | Ação imediata. |
| 1 | EMERGENCY | Condição máxima; incidente. |
| 0 | UNKNOWN | Valor desconhecido/compatibilidade. |

A escala de severidade é inversa à de health: números menores são mais graves. Não aplique a mesma expressão numérica aos dois enums.

## Cartões de GET por domínio

Cada comando é um ponto de partida. Se um campo não existir no seu OE, remova-o e consulte `/apidocs/index.html`; não converta erro de compatibilidade em alarme de infraestrutura.

## Identidade, versão e limites

Comece por esta camada. Ela prova que o array responde, identifica o modelo e fixa a compatibilidade real entre Unity OE e a documentação da API.

### GET-001 — Descoberta sem autenticação (`basicSystemInfo`)

**Objetivo.** Obter identidade e versões mínimas antes de abrir sessão.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=model,productName,softwareVersion,apiVersion" \
  "$UNITY_URL/api/instances/basicSystemInfo" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `model,productName,softwareVersion,apiVersion` |
| Observar | Mudança inesperada de versão, modelo ou API. |
| Interpretação / próxima ação | Revalidar campos e filtros após upgrade. |
| Cadência inicial | 1 h e após mudança |
| Zabbix | Item texto de inventário; trigger de mudança de versão. |

> **Nota.** É o único exemplo deliberadamente executado antes da autenticação. A disponibilidade exata dos campos varia por OE.

### GET-002 — Sistema (`system`)

**Objetivo.** Estado global, nome, modelo, serial e plataforma.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,model,serialNumber,platform,health" \
  "$UNITY_URL/api/types/system/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,model,serialNumber,platform,health` |
| Observar | health.value e descrição; identidade do array. |
| Interpretação / próxima ação | Qualquer valor diferente de OK exige correlação com alertas e hardware. |
| Cadência inicial | 1 min |
| Zabbix | Master item; dependentes para health.value, serial e modelo. |

### GET-003 — Informações do sistema (`systemInformation`)

**Objetivo.** Complementar inventário e informações operacionais.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,value" \
  "$UNITY_URL/api/types/systemInformation/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,value` |
| Observar | Alterações de identidade ou parâmetros expostos. |
| Interpretação / próxima ação | Confirmar mudanças planejadas; investigar deriva. |
| Cadência inicial | 6 h |
| Zabbix | Inventário texto/JSON; trigger nodata. |

### GET-004 — Limites do sistema (`systemLimit`)

**Objetivo.** Ler limites suportados pelo modelo/OE.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,value" \
  "$UNITY_URL/api/types/systemLimit/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,value` |
| Observar | Uso aproximando-se de limites de LUNs, filesystems, hosts e sessões. |
| Interpretação / próxima ação | Planejar expansão ou consolidação antes do limite suportado. |
| Cadência inicial | 24 h |
| Zabbix | Itens de referência usados por itens calculados de utilização. |

### GET-005 — Licenças (`license`)

**Objetivo.** Validar recursos licenciados e validade.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,state,expirationDate" \
  "$UNITY_URL/api/types/license/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,state,expirationDate` |
| Observar | Licença ausente, expirada ou perto de expirar. |
| Interpretação / próxima ação | Renovar ou ajustar o uso do recurso afetado. |
| Cadência inicial | 6 h |
| Zabbix | LLD por licença; triggers de estado e expiração. |

### GET-006 — Software instalado (`installedSoftwareVersion`)

**Objetivo.** Confirmar versão ativa e pacotes instalados.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,version,state" \
  "$UNITY_URL/api/types/installedSoftwareVersion/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,version,state` |
| Observar | Versão ativa diferente do inventário aprovado. |
| Interpretação / próxima ação | Validar janela de mudança e compatibilidade. |
| Cadência inicial | 6 h |
| Zabbix | Item de versão e trigger change(). |

### GET-007 — Software candidato (`candidateSoftwareVersion`)

**Objetivo.** Detectar imagem de upgrade carregada.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,version,state" \
  "$UNITY_URL/api/types/candidateSoftwareVersion/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,version,state` |
| Observar | Imagem candidata inesperada ou estagnada. |
| Interpretação / próxima ação | Validar change record e remover apenas por processo administrativo. |
| Cadência inicial | 6 h |
| Zabbix | Inventário; evento informativo quando surge candidato. |

### GET-008 — Sessão de upgrade (`softwareUpgradeSession`)

**Objetivo.** Acompanhar upgrade em andamento ou histórico recente.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,state,progress,startTime,endTime" \
  "$UNITY_URL/api/types/softwareUpgradeSession/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,state,progress,startTime,endTime` |
| Observar | Falha, progresso parado ou duração anormal. |
| Interpretação / próxima ação | Correlacionar com jobs e alertas; acionar suporte se falhar. |
| Cadência inicial | 1 min durante mudança; 1 h fora |
| Zabbix | LLD; trigger por state de falha e duração. |

### GET-009 — Upgrade legado (`upgradeSession`)

**Objetivo.** Cobrir versões/OE que expõem o fluxo pelo tipo legado.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,state,progress,startTime,endTime" \
  "$UNITY_URL/api/types/upgradeSession/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,state,progress,startTime,endTime` |
| Observar | Mesmo critério da sessão de software. |
| Interpretação / próxima ação | Usar o tipo que existir no on-array API reference. |
| Cadência inicial | 1 h |
| Zabbix | Fallback de compatibilidade; não duplique triggers. |

### GET-010 — Advisories técnicos (`technicalAdvisory`)

**Objetivo.** Inventariar recomendações técnicas publicadas ao array.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,severity,state,description" \
  "$UNITY_URL/api/types/technicalAdvisory/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,severity,state,description` |
| Observar | Advisory aplicável ou de alta severidade. |
| Interpretação / próxima ação | Avaliar com Dell Support e gestão de mudanças. |
| Cadência inicial | 24 h |
| Zabbix | LLD; trigger por severidade/estado aplicável. |

### GET-011 — Contrato de serviço (`serviceContract`)

**Objetivo.** Acompanhar entitlement e datas de cobertura.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,state,startDate,endDate" \
  "$UNITY_URL/api/types/serviceContract/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,state,startDate,endDate` |
| Observar | Cobertura vencida ou próxima do vencimento. |
| Interpretação / próxima ação | Renovar antes de incidentes críticos. |
| Cadência inicial | 24 h |
| Zabbix | Trigger por dias restantes. |

## Saúde, alertas, eventos e operações

Esta camada responde primeiro à pergunta ‘o que está errado agora?’ e fornece a trilha para explicar quando e por que aconteceu.

### GET-012 — Alertas ativos (`alert`)

**Objetivo.** Listar condições ativas reportadas pelo Unity.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,severity,timestamp,description,messageId,resource,isAcknowledged" \
  --data-urlencode "filter=severity le 4" \
  "$UNITY_URL/api/types/alert/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,severity,timestamp,description,messageId,resource,isAcknowledged` |
| Observar | Severidade, idade, recurso, recorrência e reconhecimento. |
| Interpretação / próxima ação | Tratar primeiro CRITICAL/EMERGENCY; correlacionar pelo recurso e messageId. |
| Cadência inicial | 1 min |
| Zabbix | Master item com LLD; trigger por severity e recuperação quando o alerta desaparece. |

### GET-013 — Eventos (`event`)

**Objetivo.** Auditar eventos operacionais, de usuário e autenticação.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,creationTime,severity,category,message,user" \
  --data-urlencode "filter=creationTime gt '<ULTIMA_COLETA>'" \
  "$UNITY_URL/api/types/event/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,creationTime,severity,category,message,user` |
| Observar | Falhas, mudanças, logins e picos por categoria. |
| Interpretação / próxima ação | Correlacionar com alertas e change records. |
| Cadência inicial | 2–5 min |
| Zabbix | Master item; dependentes por category; retenção externa. |

> **Nota.** Categorias documentadas: User=0, Audit=1 e Authentication=2. Use janela com sobreposição para não perder eventos.

### GET-014 — Jobs (`job`)

**Objetivo.** Acompanhar tarefas assíncronas.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,state,progress,startTime,endTime,message" \
  "$UNITY_URL/api/types/job/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,state,progress,startTime,endTime,message` |
| Observar | Estado de falha, progresso parado, fila e duração. |
| Interpretação / próxima ação | Investigar recurso-alvo e alertas do mesmo período. |
| Cadência inicial | 1 min |
| Zabbix | LLD para jobs ativos; trigger por estado e tempo em execução. |

### GET-015 — Ações de serviço (`serviceAction`)

**Objetivo.** Observar ações de manutenção registradas.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,state,startTime,endTime" \
  "$UNITY_URL/api/types/serviceAction/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,state,startTime,endTime` |
| Observar | Ação não planejada, falha ou duração excessiva. |
| Interpretação / próxima ação | Confirmar janela e owner; escalar falha. |
| Cadência inicial | 5 min |
| Zabbix | Evento/trap lógico por novo objeto ou mudança de state. |

### GET-016 — Pacotes uDoctor (`udoctorPackage`)

**Objetivo.** Inventariar pacotes de diagnóstico disponíveis/aplicados.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,version,state" \
  "$UNITY_URL/api/types/udoctorPackage/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,version,state` |
| Observar | Pacote inesperado ou mudança sem registro. |
| Interpretação / próxima ação | Validar orientação de suporte. |
| Cadência inicial | 24 h |
| Zabbix | Inventário e change trigger. |

### GET-017 — Core dumps (`coreDump`)

**Objetivo.** Detectar dumps gerados por falha de software.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,creationTime,size,state" \
  "$UNITY_URL/api/types/coreDump/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,creationTime,size,state` |
| Observar | Novo dump ou crescimento recorrente. |
| Interpretação / próxima ação | Preservar evidência e abrir chamado quando associado a impacto. |
| Cadência inicial | 10 min |
| Zabbix | LLD; trigger por novo id. |

### GET-018 — Resultado de coleta de configuração (`configCaptureResult`)

**Objetivo.** Acompanhar coletas de configuração/diagnóstico.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,state,startTime,endTime,fileName" \
  "$UNITY_URL/api/types/configCaptureResult/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,state,startTime,endTime,fileName` |
| Observar | Falha ou coleta inesperada. |
| Interpretação / próxima ação | Confirmar ação de suporte ou auditoria. |
| Cadência inicial | 30 min |
| Zabbix | Evento informativo/falha. |

### GET-019 — Hora do sistema (`systemTime`)

**Objetivo.** Verificar hora e timezone do array.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,currentTime,timeZone" \
  "$UNITY_URL/api/types/systemTime/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,currentTime,timeZone` |
| Observar | Desvio de horário em relação ao monitoramento. |
| Interpretação / próxima ação | Corrigir NTP antes de analisar cronologia. |
| Cadência inicial | 5 min |
| Zabbix | Item timestamp; trigger por skew calculado. |

### GET-020 — Servidores NTP (`ntpServer`)

**Objetivo.** Validar fontes de tempo configuradas e estado.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,address,health" \
  "$UNITY_URL/api/types/ntpServer/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,address,health` |
| Observar | Fonte indisponível ou health degradado. |
| Interpretação / próxima ação | Corrigir rede/DNS/NTP e manter múltiplas fontes. |
| Cadência inicial | 5 min |
| Zabbix | LLD por servidor; trigger health. |

### GET-021 — Servidores DNS (`dnsServer`)

**Objetivo.** Validar resolvedores configurados.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,address,domain,health" \
  "$UNITY_URL/api/types/dnsServer/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,address,domain,health` |
| Observar | Falha de resolução ou health degradado. |
| Interpretação / próxima ação | Corrigir conectividade antes de LDAP, SMTP, suporte e replicação. |
| Cadência inicial | 5 min |
| Zabbix | LLD por DNS; trigger health. |

### GET-022 — SMTP (`smtpServer`)

**Objetivo.** Inspecionar configuração do relay de alertas.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,address,port,health" \
  "$UNITY_URL/api/types/smtpServer/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,address,port,health` |
| Observar | Relay indisponível ou configuração divergente. |
| Interpretação / próxima ação | Testar fora da API GET conforme processo autorizado. |
| Cadência inicial | 30 min |
| Zabbix | Inventário e health. |

### GET-023 — Syslog remoto (`remoteSyslog`)

**Objetivo.** Auditar destinos externos de logs.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,address,port,protocol,enabled,health" \
  "$UNITY_URL/api/types/remoteSyslog/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,address,port,protocol,enabled,health` |
| Observar | Destino desativado, alterado ou com falha. |
| Interpretação / próxima ação | Restaurar envio seguro e confirmar ingestão no SIEM. |
| Cadência inicial | 5 min |
| Zabbix | LLD; triggers de enabled, health e change. |

## Hardware e caminho de backend

Monitore do gabinete e SP até cada disco. Um health global OK não substitui a visibilidade de componentes redundantes.

### GET-024 — Storage processors (`storageProcessor`)

**Objetivo.** Saúde e identidade de SPA/SPB.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,model,serialNumber" \
  "$UNITY_URL/api/types/storageProcessor/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,model,serialNumber` |
| Observar | SP degradado, ausente ou em reboot. |
| Interpretação / próxima ação | Correlacionar portas, módulos e alertas; preservar redundância. |
| Cadência inicial | 1 min |
| Zabbix | LLD por SP; trigger health e nodata. |

### GET-025 — DPE (`dpe`)

**Objetivo.** Saúde do Disk Processor Enclosure.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,model,serialNumber" \
  "$UNITY_URL/api/types/dpe/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,model,serialNumber` |
| Observar | Gabinete degradado ou componente ausente. |
| Interpretação / próxima ação | Abrir a árvore de LCC, PSU, fan e discos. |
| Cadência inicial | 2 min |
| Zabbix | LLD; trigger health. |

### GET-026 — DAE (`dae`)

**Objetivo.** Saúde dos enclosures de expansão.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,model,serialNumber" \
  "$UNITY_URL/api/types/dae/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,model,serialNumber` |
| Observar | DAE degradado, inacessível ou removido. |
| Interpretação / próxima ação | Correlacionar LCC, SAS e alimentação. |
| Cadência inicial | 2 min |
| Zabbix | LLD; trigger health e contagem esperada. |

### GET-027 — LCC (`lcc`)

**Objetivo.** Saúde dos controladores de enclosure.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,parent" \
  "$UNITY_URL/api/types/lcc/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,parent` |
| Observar | Falha de LCC ou perda de redundância. |
| Interpretação / próxima ação | Verificar SAS, cabos e enclosure. |
| Cadência inicial | 2 min |
| Zabbix | LLD; trigger health. |

### GET-028 — Módulos I/O (`ioModule`)

**Objetivo.** Saúde e inventário de módulos de conectividade.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,model,slot" \
  "$UNITY_URL/api/types/ioModule/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,model,slot` |
| Observar | Módulo degradado, ausente ou divergente. |
| Interpretação / próxima ação | Correlacionar portas filhas e mudança física. |
| Cadência inicial | 2 min |
| Zabbix | LLD por slot; trigger health/change. |

### GET-029 — Memória (`memoryModule`)

**Objetivo.** Saúde de DIMMs e módulos de memória.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,size,parent" \
  "$UNITY_URL/api/types/memoryModule/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,size,parent` |
| Observar | Degradação, tamanho inesperado ou ausência. |
| Interpretação / próxima ação | Escalar falha de hardware; evitar intervenção não coordenada. |
| Cadência inicial | 5 min |
| Zabbix | LLD; trigger health. |

### GET-030 — Baterias (`battery`)

**Objetivo.** Saúde de baterias/cache backup.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,parent" \
  "$UNITY_URL/api/types/battery/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,parent` |
| Observar | Falha, carga inadequada ou perda de proteção. |
| Interpretação / próxima ação | Prioridade alta: risco à proteção de cache. |
| Cadência inicial | 2 min |
| Zabbix | LLD; trigger health com severidade alta. |

### GET-031 — Ventiladores (`fan`)

**Objetivo.** Saúde dos fans.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,parent" \
  "$UNITY_URL/api/types/fan/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,parent` |
| Observar | Fan degradado/ausente e tendência de múltiplas falhas. |
| Interpretação / próxima ação | Verificar ambiente e abrir chamado. |
| Cadência inicial | 2 min |
| Zabbix | LLD; trigger health. |

### GET-032 — Fontes de alimentação (`powerSupply`)

**Objetivo.** Saúde e redundância de PSUs.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,parent" \
  "$UNITY_URL/api/types/powerSupply/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,parent` |
| Observar | PSU falha ou perda de feed. |
| Interpretação / próxima ação | Verificar alimentação A/B e hardware. |
| Cadência inicial | 2 min |
| Zabbix | LLD; trigger health e correlação por enclosure. |

### GET-033 — Discos (`disk`)

**Objetivo.** Saúde, posição, capacidade e tipo de cada disco.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,slotNumber,tierType,rawSize,rpm" \
  "$UNITY_URL/api/types/disk/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,slotNumber,tierType,rawSize,rpm` |
| Observar | Falha, rebuild, disco ausente ou capacidade divergente. |
| Interpretação / próxima ação | Correlacionar disk group/RAID e iniciar substituição autorizada. |
| Cadência inicial | 2 min |
| Zabbix | LLD por id/slot; trigger health; inventário de capacidade. |

### GET-034 — SSDs (`ssd`)

**Objetivo.** Saúde e inventário de SSDs onde exposto separadamente.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,slotNumber,rawSize" \
  "$UNITY_URL/api/types/ssd/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,slotNumber,rawSize` |
| Observar | Falha, desgaste ou ausência conforme campos do OE. |
| Interpretação / próxima ação | Correlacionar com pool/tier e suporte. |
| Cadência inicial | 5 min |
| Zabbix | LLD; trigger health; desgaste somente se o campo existir. |

### GET-035 — Disk groups (`diskGroup`)

**Objetivo.** Saúde e composição dos grupos de discos.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,totalSpace,freeSpace" \
  "$UNITY_URL/api/types/diskGroup/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,totalSpace,freeSpace` |
| Observar | Grupo degradado ou baixa folga. |
| Interpretação / próxima ação | Correlacionar discos e RAID groups. |
| Cadência inicial | 2 min |
| Zabbix | LLD; health e percentual livre. |

### GET-036 — RAID groups (`raidGroup`)

**Objetivo.** Saúde e progresso de operações RAID.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,state,rebuildProgress" \
  "$UNITY_URL/api/types/raidGroup/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,state,rebuildProgress` |
| Observar | Degraded/rebuilding por tempo excessivo. |
| Interpretação / próxima ação | Acompanhar discos; não fazer mudanças concorrentes. |
| Cadência inicial | 1 min |
| Zabbix | LLD; trigger state e duração do rebuild. |

### GET-037 — FAST Cache (`fastCache`)

**Objetivo.** Estado e capacidade de FAST Cache, se licenciado.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,state,totalSize" \
  "$UNITY_URL/api/types/fastCache/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,state,totalSize` |
| Observar | Desabilitado, degradado ou alteração de tamanho. |
| Interpretação / próxima ação | Validar discos e configuração licenciada. |
| Cadência inicial | 5 min |
| Zabbix | Itens state/health/capacidade. |

### GET-038 — FAST VP (`fastVP`)

**Objetivo.** Estado do serviço de tiering e movimentações.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,state" \
  "$UNITY_URL/api/types/fastVP/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,state` |
| Observar | Falha ou estado inesperado. |
| Interpretação / próxima ação | Correlacionar storage tiers e jobs. |
| Cadência inicial | 10 min |
| Zabbix | Item state/health. |

## Conectividade, portas, hosts e caminhos

A saúde de front-end precisa combinar porta, interface lógica, iniciador e caminho. Monitorar apenas a porta não detecta todos os problemas de multipath.

### GET-039 — Portas FC (`fcPort`)

**Objetivo.** Saúde, link, velocidade e SP das portas Fibre Channel.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,linkState,speed,storageProcessor" \
  "$UNITY_URL/api/types/fcPort/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,linkState,speed,storageProcessor` |
| Observar | Link down inesperado, velocidade negociada menor ou health degradado. |
| Interpretação / próxima ação | Correlacionar switch, SFP, zoning e host paths. |
| Cadência inicial | 1 min |
| Zabbix | LLD; triggers link/health/speed. |

### GET-040 — Portas Ethernet (`ethernetPort`)

**Objetivo.** Saúde, link, MTU e velocidade Ethernet.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,linkState,speed,mtu,storageProcessor" \
  "$UNITY_URL/api/types/ethernetPort/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,linkState,speed,mtu,storageProcessor` |
| Observar | Link down, erro de MTU ou velocidade divergente. |
| Interpretação / próxima ação | Correlacionar switch, LACP/FSN e interfaces IP. |
| Cadência inicial | 1 min |
| Zabbix | LLD; triggers link/health/speed. |

### GET-041 — Portas SAS (`sasPort`)

**Objetivo.** Saúde do backend SAS.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,linkState,parent" \
  "$UNITY_URL/api/types/sasPort/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,linkState,parent` |
| Observar | Link degradado ou perda de caminho para DAE. |
| Interpretação / próxima ação | Verificar cabos, LCC e enclosure. |
| Cadência inicial | 1 min |
| Zabbix | LLD; trigger health/link. |

### GET-042 — Portas IP (`ipPort`)

**Objetivo.** Relação entre portas físicas e serviços IP.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,ethernetPort" \
  "$UNITY_URL/api/types/ipPort/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,ethernetPort` |
| Observar | Health degradado ou vínculo inesperado. |
| Interpretação / próxima ação | Correlacionar interface e porta Ethernet. |
| Cadência inicial | 2 min |
| Zabbix | LLD; health e inventário. |

### GET-043 — Interfaces IP (`ipInterface`)

**Objetivo.** Endereços, papéis e estado de interfaces.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,ipAddress,netmask,gateway,vlanId" \
  "$UNITY_URL/api/types/ipInterface/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,ipAddress,netmask,gateway,vlanId` |
| Observar | Interface degradada, IP ou VLAN alterados. |
| Interpretação / próxima ação | Validar rede e change record. |
| Cadência inicial | 2 min |
| Zabbix | LLD; trigger health/change; dados sensíveis com acesso restrito. |

### GET-044 — Interface de gerenciamento (`mgmtInterface`)

**Objetivo.** Saúde e endereçamento do plano de gestão.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,ipAddress,linkState" \
  "$UNITY_URL/api/types/mgmtInterface/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,ipAddress,linkState` |
| Observar | Perda de link, health ou mudança de IP. |
| Interpretação / próxima ação | Preservar acesso OOB e validar rede. |
| Cadência inicial | 1 min |
| Zabbix | Trigger link/health e mudança. |

### GET-045 — Configuração de gerenciamento (`mgmtInterfaceSettings`)

**Objetivo.** Auditar parâmetros da interface de gestão.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,mtu,autoNegotiation,speed" \
  "$UNITY_URL/api/types/mgmtInterfaceSettings/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,mtu,autoNegotiation,speed` |
| Observar | Deriva de MTU, negociação ou velocidade. |
| Interpretação / próxima ação | Comparar com baseline aprovado. |
| Cadência inicial | 6 h |
| Zabbix | Inventário e change trigger. |

### GET-046 — Link aggregation (`linkAggregation`)

**Objetivo.** Saúde e membros de agregações.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,ports,linkState" \
  "$UNITY_URL/api/types/linkAggregation/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,ports,linkState` |
| Observar | Membro perdido, agregação degradada. |
| Interpretação / próxima ação | Correlacionar switch/LACP e portas. |
| Cadência inicial | 1 min |
| Zabbix | LLD; trigger por health e número de membros. |

### GET-047 — FSN ports (`fsnPort`)

**Objetivo.** Saúde de Fail-Safe Networks.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,ports,activePort" \
  "$UNITY_URL/api/types/fsnPort/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,ports,activePort` |
| Observar | Perda de membro ou failover recorrente. |
| Interpretação / próxima ação | Verificar portas e switch; acompanhar flapping. |
| Cadência inicial | 1 min |
| Zabbix | LLD; trigger health e change activePort. |

### GET-048 — Portas não comprometidas (`uncommittedPort`)

**Objetivo.** Detectar portas disponíveis ou não atribuídas.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,portType" \
  "$UNITY_URL/api/types/uncommittedPort/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,portType` |
| Observar | Mudança inesperada no inventário. |
| Interpretação / próxima ação | Validar expansão/reconfiguração. |
| Cadência inicial | 6 h |
| Zabbix | Inventário e change trigger. |

### GET-049 — VLANs (`vlanInfo`)

**Objetivo.** Inventariar VLANs associadas às interfaces.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,vlanId,name" \
  "$UNITY_URL/api/types/vlanInfo/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,vlanId,name` |
| Observar | VLAN ausente ou alterada. |
| Interpretação / próxima ação | Comparar com desenho de rede. |
| Cadência inicial | 6 h |
| Zabbix | LLD/inventário. |

### GET-050 — Rotas (`route`)

**Objetivo.** Auditar rotas estáticas.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,destination,gateway,interface" \
  "$UNITY_URL/api/types/route/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,destination,gateway,interface` |
| Observar | Rota ausente, duplicada ou alterada. |
| Interpretação / próxima ação | Validar conectividade e baseline. |
| Cadência inicial | 6 h |
| Zabbix | LLD; trigger de mudança. |

### GET-051 — Hosts (`host`)

**Objetivo.** Inventariar hosts e estado agregado.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,hostInitiators,osType" \
  "$UNITY_URL/api/types/host/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,hostInitiators,osType` |
| Observar | Host degradado, removido ou sem iniciadores esperados. |
| Interpretação / próxima ação | Correlacionar paths e mudança de zoning/masking. |
| Cadência inicial | 5 min |
| Zabbix | LLD por host; health e contagem de iniciadores. |

### GET-052 — Iniciadores (`hostInitiator`)

**Objetivo.** Inventariar WWPNs/IQNs e seus hosts.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,initiatorId,host" \
  "$UNITY_URL/api/types/hostInitiator/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,initiatorId,host` |
| Observar | Iniciador sem host, duplicado ou degradado. |
| Interpretação / próxima ação | Corrigir cadastro/zoning conforme processo. |
| Cadência inicial | 5 min |
| Zabbix | LLD; trigger health e associação. |

### GET-053 — Caminhos de iniciador (`hostInitiatorPath`)

**Objetivo.** Medir disponibilidade de paths host–SP–porta.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,health,state,hostInitiator,fcPort,iscsiPortal" \
  "$UNITY_URL/api/types/hostInitiatorPath/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,health,state,hostInitiator,fcPort,iscsiPortal` |
| Observar | Path down, degradação ou redução de redundância. |
| Interpretação / próxima ação | Prioridade alta: correlacionar fabric/rede e multipath do host. |
| Cadência inicial | 1 min |
| Zabbix | LLD por path; trigger state e item calculado de paths ativos por host. |

### GET-054 — Mapeamentos host–LUN (`hostLUN`)

**Objetivo.** Auditar visibilidade e IDs de LUN por host.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,host,lun,hostLUNId" \
  "$UNITY_URL/api/types/hostLUN/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,host,lun,hostLUNId` |
| Observar | Mapeamento removido/adicionado inesperadamente. |
| Interpretação / próxima ação | Comparar com baseline e change record. |
| Cadência inicial | 15 min |
| Zabbix | Inventário; trigger de mudança, não de performance. |

### GET-055 — Nós iSCSI (`iscsiNode`)

**Objetivo.** Inventariar IQNs e estado dos nós.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,iqn" \
  "$UNITY_URL/api/types/iscsiNode/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,iqn` |
| Observar | Health degradado ou IQN alterado. |
| Interpretação / próxima ação | Correlacionar portais e hosts. |
| Cadência inicial | 5 min |
| Zabbix | LLD; health/change. |

### GET-056 — Portais iSCSI (`iscsiPortal`)

**Objetivo.** Saúde e endereços dos portais.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,ipAddress,ipPort" \
  "$UNITY_URL/api/types/iscsiPortal/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,ipAddress,ipPort` |
| Observar | Portal down/degradado ou endereço alterado. |
| Interpretação / próxima ação | Verificar rede, VLAN, MTU e autenticação. |
| Cadência inicial | 1 min |
| Zabbix | LLD; health e mudança. |

## Capacidade, pools, block, file, snapshots e quotas

Use bytes como unidade de coleta e converta apenas na apresentação. Alertas de capacidade devem considerar percentual, bytes restantes e tendência de esgotamento.

### GET-057 — Capacidade do sistema (`systemCapacity`)

**Objetivo.** Resumo físico e utilizável do array.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,sizeFree,sizeUsed,sizeTotal" \
  "$UNITY_URL/api/types/systemCapacity/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,sizeFree,sizeUsed,sizeTotal` |
| Observar | Percentual livre, crescimento e inconsistência com pools. |
| Interpretação / próxima ação | Planejar expansão antes do ponto de exaustão. |
| Cadência inicial | 5 min |
| Zabbix | Itens bytes e percentual; forecast/timeleft. |

### GET-058 — Pools (`pool`)

**Objetivo.** Saúde e capacidade por pool.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,sizeTotal,sizeUsed,sizeFree,alertThreshold" \
  "$UNITY_URL/api/types/pool/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,sizeTotal,sizeUsed,sizeFree,alertThreshold` |
| Observar | Health, limite configurado, livre absoluto e velocidade de consumo. |
| Interpretação / próxima ação | Investigar top consumers e planejar expansão/migração. |
| Cadência inicial | 2 min |
| Zabbix | LLD por pool; triggers 70/80/90% ajustados ao ambiente e forecast. |

### GET-059 — Tiers (`storageTier`)

**Objetivo.** Capacidade e distribuição por tier.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,sizeTotal,sizeUsed,sizeFree,tierType" \
  "$UNITY_URL/api/types/storageTier/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,sizeTotal,sizeUsed,sizeFree,tierType` |
| Observar | Tier saturado ou distribuição anormal. |
| Interpretação / próxima ação | Correlacionar FAST VP e workload. |
| Cadência inicial | 10 min |
| Zabbix | LLD; percentual por tier. |

### GET-060 — Unidades de pool (`poolUnit`)

**Objetivo.** Visibilidade de unidades internas do pool.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,sizeTotal,sizeFree,pool" \
  "$UNITY_URL/api/types/poolUnit/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,sizeTotal,sizeFree,pool` |
| Observar | Unidade degradada ou desequilíbrio. |
| Interpretação / próxima ação | Correlacionar disks/disk groups. |
| Cadência inicial | 10 min |
| Zabbix | LLD; health e capacidade. |

### GET-061 — Consumidores de pool (`poolConsumer`)

**Objetivo.** Identificar entidades que consomem espaço.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,type,pool,sizeUsed" \
  "$UNITY_URL/api/types/poolConsumer/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,type,pool,sizeUsed` |
| Observar | Crescimento dos maiores consumidores. |
| Interpretação / próxima ação | Atribuir owner e investigar anomalias. |
| Cadência inicial | 10 min |
| Zabbix | LLD; top N e taxa de crescimento. |

### GET-062 — Alocações de consumidores (`poolConsumerAllocation`)

**Objetivo.** Detalhar alocação por consumidor/tier.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,poolConsumer,storageTier,sizeAllocated" \
  "$UNITY_URL/api/types/poolConsumerAllocation/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,poolConsumer,storageTier,sizeAllocated` |
| Observar | Mudança brusca ou tier inesperado. |
| Interpretação / próxima ação | Correlacionar política e performance. |
| Cadência inicial | 30 min |
| Zabbix | Itens dependentes; uso analítico. |

### GET-063 — LUNs (`lun`)

**Objetivo.** Saúde e capacidade lógica/alocada de LUNs.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,sizeTotal,sizeAllocated,pool,isThinEnabled" \
  "$UNITY_URL/api/types/lun/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,sizeTotal,sizeAllocated,pool,isThinEnabled` |
| Observar | Health, crescimento, thin allocation e LUN sem owner. |
| Interpretação / próxima ação | Correlacionar pool e host mappings. |
| Cadência inicial | 5 min |
| Zabbix | LLD por LUN; bytes, percentual alocado e health. |

### GET-064 — Filesystems (`filesystem`)

**Objetivo.** Saúde e capacidade de filesystems.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,sizeTotal,sizeUsed,sizeAllocated,pool,nasServer" \
  "$UNITY_URL/api/types/filesystem/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,sizeTotal,sizeUsed,sizeAllocated,pool,nasServer` |
| Observar | Livre baixo, crescimento e health. |
| Interpretação / próxima ação | Revisar quotas, snapshots e expansão. |
| Cadência inicial | 2 min |
| Zabbix | LLD; percentual, bytes livres e forecast. |

### GET-065 — Storage resources (`storageResource`)

**Objetivo.** Visão agregada de recursos de armazenamento.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,type,pool,sizeUsed" \
  "$UNITY_URL/api/types/storageResource/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,type,pool,sizeUsed` |
| Observar | Health e consumo agregado por recurso. |
| Interpretação / próxima ação | Usar para correlação, evitando soma dupla com LUN/filesystem. |
| Cadência inicial | 5 min |
| Zabbix | LLD; health e inventário. |

### GET-066 — Datastores (`datastore`)

**Objetivo.** Capacidade e saúde de datastores integrados.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,sizeTotal,sizeUsed" \
  "$UNITY_URL/api/types/datastore/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,sizeTotal,sizeUsed` |
| Observar | Baixo espaço, health e mudança de associação. |
| Interpretação / próxima ação | Correlacionar VMware, LUN/filesystem e hosts. |
| Cadência inicial | 5 min |
| Zabbix | LLD; capacidade/health. |

### GET-067 — Snapshots (`snap`)

**Objetivo.** Inventariar snapshots, estado, tamanho e expiração.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,state,creationTime,expirationTime,size,parent" \
  "$UNITY_URL/api/types/snap/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,state,creationTime,expirationTime,size,parent` |
| Observar | Snapshot antigo, sem expiração, falho ou crescimento excessivo. |
| Interpretação / próxima ação | Revisar política e owner; exclusão é ação separada e autorizada. |
| Cadência inicial | 10 min |
| Zabbix | LLD; idade, expiração, state e contagem por parent. |

### GET-068 — Tree quotas (`treeQuota`)

**Objetivo.** Capacidade e limites de diretórios quota tree.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,path,filesystem,hardLimit,softLimit,usedSpace" \
  "$UNITY_URL/api/types/treeQuota/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,path,filesystem,hardLimit,softLimit,usedSpace` |
| Observar | Uso perto do soft/hard limit. |
| Interpretação / próxima ação | Notificar owner e ajustar somente por processo. |
| Cadência inicial | 10 min |
| Zabbix | LLD; percentuais soft/hard. |

### GET-069 — User quotas (`userQuota`)

**Objetivo.** Uso e limites por usuário/grupo.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,user,filesystem,hardLimit,softLimit,usedSpace" \
  "$UNITY_URL/api/types/userQuota/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,user,filesystem,hardLimit,softLimit,usedSpace` |
| Observar | Usuário próximo do limite ou crescimento anômalo. |
| Interpretação / próxima ação | Notificar owner e revisar consumo. |
| Cadência inicial | 15 min |
| Zabbix | LLD com cuidado de cardinalidade; top N. |

### GET-070 — Configuração de quotas (`quotaConfig`)

**Objetivo.** Auditar habilitação e parâmetros de quota.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,filesystem,enabled,defaultHardLimit,defaultSoftLimit" \
  "$UNITY_URL/api/types/quotaConfig/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,filesystem,enabled,defaultHardLimit,defaultSoftLimit` |
| Observar | Quota desativada ou política alterada. |
| Interpretação / próxima ação | Comparar com baseline aprovado. |
| Cadência inicial | 6 h |
| Zabbix | Inventário e change trigger. |

### GET-071 — Virtual volumes (`virtualVolume`)

**Objetivo.** Capacidade e saúde de VVols.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,sizeTotal,sizeUsed,storageResource" \
  "$UNITY_URL/api/types/virtualVolume/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,sizeTotal,sizeUsed,storageResource` |
| Observar | Health, crescimento e objetos órfãos. |
| Interpretação / próxima ação | Correlacionar PE, datastore e VM. |
| Cadência inicial | 5 min |
| Zabbix | LLD; health e capacidade. |

## Serviços NAS e protocolos de arquivo

Combine saúde do NAS server, interfaces, servidores de protocolo, shares e dependências de identidade. Evite coletar listas de ACLs em alta frequência.

### GET-072 — NAS servers (`nasServer`)

**Objetivo.** Saúde, SP atual e mobilidade dos servidores NAS.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,currentSP,homeSP,pool" \
  "$UNITY_URL/api/types/nasServer/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,currentSP,homeSP,pool` |
| Observar | Health, failover/failback recorrente e SP inesperado. |
| Interpretação / próxima ação | Correlacionar interfaces, file systems e eventos. |
| Cadência inicial | 1 min |
| Zabbix | LLD; health e change currentSP. |

### GET-073 — Interfaces file (`fileInterface`)

**Objetivo.** Saúde e endereçamento de interfaces NAS.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,ipAddress,nasServer,ipPort" \
  "$UNITY_URL/api/types/fileInterface/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,ipAddress,nasServer,ipPort` |
| Observar | Interface down/degradada ou endereço alterado. |
| Interpretação / próxima ação | Correlacionar porta, VLAN, rota e NAS server. |
| Cadência inicial | 1 min |
| Zabbix | LLD; health/change. |

### GET-074 — CIFS/SMB servers (`cifsServer`)

**Objetivo.** Estado e identidade dos servidores SMB.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,nasServer,domain" \
  "$UNITY_URL/api/types/cifsServer/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,nasServer,domain` |
| Observar | Health, domínio ou nome alterado. |
| Interpretação / próxima ação | Correlacionar DNS, AD/Kerberos e eventos de autenticação. |
| Cadência inicial | 2 min |
| Zabbix | LLD; health e configuração. |

### GET-075 — SMB shares (`cifsShare`)

**Objetivo.** Inventariar shares e caminhos.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,path,filesystem,cifsServer,isReadOnly" \
  "$UNITY_URL/api/types/cifsShare/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,path,filesystem,cifsServer,isReadOnly` |
| Observar | Share ausente, novo ou modo alterado. |
| Interpretação / próxima ação | Comparar com baseline; revisar ACL por processo de auditoria. |
| Cadência inicial | 15 min |
| Zabbix | LLD/inventário; trigger change. |

### GET-076 — NFS servers (`nfsServer`)

**Objetivo.** Estado do serviço NFS.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,nasServer" \
  "$UNITY_URL/api/types/nfsServer/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,nasServer` |
| Observar | Health degradado ou serviço indisponível. |
| Interpretação / próxima ação | Correlacionar interfaces e exports. |
| Cadência inicial | 2 min |
| Zabbix | LLD; health. |

### GET-077 — NFS shares (`nfsShare`)

**Objetivo.** Inventariar exports, caminhos e opções.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,path,filesystem,nfsServer" \
  "$UNITY_URL/api/types/nfsShare/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,path,filesystem,nfsServer` |
| Observar | Export ausente, novo ou opções alteradas. |
| Interpretação / próxima ação | Comparar com baseline e hosts autorizados. |
| Cadência inicial | 15 min |
| Zabbix | LLD/inventário; trigger change. |

### GET-078 — DNS de arquivo (`fileDNSServer`)

**Objetivo.** Validar DNS usado pelos serviços NAS.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,address,domain,health,nasServer" \
  "$UNITY_URL/api/types/fileDNSServer/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,address,domain,health,nasServer` |
| Observar | DNS indisponível/degradado. |
| Interpretação / próxima ação | Corrigir antes de tratar AD/Kerberos como causa. |
| Cadência inicial | 5 min |
| Zabbix | LLD; health. |

### GET-079 — LDAP de arquivo (`fileLDAPServer`)

**Objetivo.** Saúde dos servidores LDAP usados por file.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,address,health,nasServer" \
  "$UNITY_URL/api/types/fileLDAPServer/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,address,health,nasServer` |
| Observar | Servidor indisponível ou health degradado. |
| Interpretação / próxima ação | Correlacionar rede, TLS e identidade. |
| Cadência inicial | 5 min |
| Zabbix | LLD; health. |

### GET-080 — NIS (`fileNISServer`)

**Objetivo.** Saúde de NIS quando utilizado.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,address,health,nasServer" \
  "$UNITY_URL/api/types/fileNISServer/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,address,health,nasServer` |
| Observar | Indisponibilidade ou configuração alterada. |
| Interpretação / próxima ação | Corrigir dependência ou descontinuar conforme arquitetura. |
| Cadência inicial | 5 min |
| Zabbix | LLD; health/change. |

### GET-081 — Kerberos (`fileKerberosServer`)

**Objetivo.** Saúde e configuração Kerberos para NAS.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,address,health,nasServer" \
  "$UNITY_URL/api/types/fileKerberosServer/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,address,health,nasServer` |
| Observar | Health, relógio ou servidor indisponível. |
| Interpretação / próxima ação | Correlacionar NTP, DNS e eventos de autenticação. |
| Cadência inicial | 5 min |
| Zabbix | LLD; health. |

### GET-082 — NDMP (`fileNDMPServer`)

**Objetivo.** Estado do serviço de backup NDMP.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,nasServer" \
  "$UNITY_URL/api/types/fileNDMPServer/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,nasServer` |
| Observar | Health degradado ou serviço inesperadamente desativado. |
| Interpretação / próxima ação | Correlacionar jobs de backup fora do array. |
| Cadência inicial | 5 min |
| Zabbix | LLD; health/state. |

### GET-083 — Antivírus (`virusChecker`)

**Objetivo.** Saúde dos servidores de varredura ICAP/antivírus.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,address,health,nasServer" \
  "$UNITY_URL/api/types/virusChecker/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,address,health,nasServer` |
| Observar | Checker indisponível ou baixa redundância. |
| Interpretação / próxima ação | Corrigir serviço/rede; avaliar política fail-open/fail-close. |
| Cadência inicial | 2 min |
| Zabbix | LLD; health e contagem disponível. |

### GET-084 — File events publisher (`fileEventsPublisher`)

**Objetivo.** Estado da publicação de eventos file.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,state" \
  "$UNITY_URL/api/types/fileEventsPublisher/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,state` |
| Observar | Publicador parado ou degradado. |
| Interpretação / próxima ação | Restaurar integração de auditoria/segurança. |
| Cadência inicial | 5 min |
| Zabbix | LLD; state/health. |

### GET-085 — File events pool (`fileEventsPool`)

**Objetivo.** Capacidade/estado da fila de eventos file.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,sizeUsed,sizeTotal" \
  "$UNITY_URL/api/types/fileEventsPool/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,sizeUsed,sizeTotal` |
| Observar | Fila crescendo ou perto do limite. |
| Interpretação / próxima ação | Investigar consumidor e conectividade. |
| Cadência inicial | 2 min |
| Zabbix | Percentual e tendência. |

### GET-086 — DHSM servers (`dhsmServer`)

**Objetivo.** Saúde de servidores DHSM.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,nasServer" \
  "$UNITY_URL/api/types/dhsmServer/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,nasServer` |
| Observar | Indisponibilidade ou health degradado. |
| Interpretação / próxima ação | Correlacionar tiering/backup externo. |
| Cadência inicial | 5 min |
| Zabbix | LLD; health. |

### GET-087 — DHSM connections (`dhsmConnection`)

**Objetivo.** Estado das conexões DHSM.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,state,dhsmServer" \
  "$UNITY_URL/api/types/dhsmConnection/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,state,dhsmServer` |
| Observar | Conexão down ou flapping. |
| Interpretação / próxima ação | Verificar rede e servidor externo. |
| Cadência inicial | 2 min |
| Zabbix | LLD; state/health. |

## Proteção, snapshots e replicação

A API GET mostra configuração e estado; ela não prova sozinha que uma cópia é recuperável. Combine status, RPO, última sincronização e testes de recuperação governados.

### GET-088 — Sessões de replicação (`replicationSession`)

**Objetivo.** Acompanhar estado, direção, RPO e sincronização.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,state,source,destination,rpo,lastSyncTime,syncProgress" \
  "$UNITY_URL/api/types/replicationSession/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,state,source,destination,rpo,lastSyncTime,syncProgress` |
| Observar | Sessão pausada/falha, atraso maior que RPO ou progresso parado. |
| Interpretação / próxima ação | Correlacionar interfaces, sistema remoto e alertas. |
| Cadência inicial | 1 min |
| Zabbix | LLD; state/health, atraso e violação de RPO. |

### GET-089 — Sistemas remotos (`remoteSystem`)

**Objetivo.** Saúde e conectividade dos peers.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,address,model,serialNumber" \
  "$UNITY_URL/api/types/remoteSystem/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,address,model,serialNumber` |
| Observar | Peer inacessível, health ou identidade alterada. |
| Interpretação / próxima ação | Verificar WAN, certificados e array remoto. |
| Cadência inicial | 1 min |
| Zabbix | LLD; health/nodata/change. |

### GET-090 — Interfaces de replicação (`replicationInterface`)

**Objetivo.** Saúde e endereço das interfaces locais de replicação.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,ipAddress,storageProcessor" \
  "$UNITY_URL/api/types/replicationInterface/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,ipAddress,storageProcessor` |
| Observar | Interface down/degradada ou endereço alterado. |
| Interpretação / próxima ação | Correlacionar porta/rede e peer. |
| Cadência inicial | 1 min |
| Zabbix | LLD; health/change. |

### GET-091 — Interfaces remotas (`remoteInterface`)

**Objetivo.** Inventariar interfaces anunciadas pelo sistema remoto.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,ipAddress,remoteSystem" \
  "$UNITY_URL/api/types/remoteInterface/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,ipAddress,remoteSystem` |
| Observar | Interface remota indisponível ou alterada. |
| Interpretação / próxima ação | Correlacionar com WAN e peer. |
| Cadência inicial | 2 min |
| Zabbix | LLD; health/change. |

### GET-092 — Interfaces preferidas (`preferredInterfaceSettings`)

**Objetivo.** Auditar preferências de caminho de replicação.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,sourceInterface,destinationInterface" \
  "$UNITY_URL/api/types/preferredInterfaceSettings/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,sourceInterface,destinationInterface` |
| Observar | Mudança ou preferência incompatível. |
| Interpretação / próxima ação | Comparar com desenho de rede. |
| Cadência inicial | 6 h |
| Zabbix | Inventário e change trigger. |

### GET-093 — Agendamentos de snapshot (`snapSchedule`)

**Objetivo.** Auditar horários, frequência e habilitação.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,enabled,interval,retention" \
  "$UNITY_URL/api/types/snapSchedule/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,enabled,interval,retention` |
| Observar | Schedule desativado, alterado ou sem recursos associados. |
| Interpretação / próxima ação | Comparar com política de proteção. |
| Cadência inicial | 6 h |
| Zabbix | LLD; enabled/change. |

### GET-094 — Sessões de movimentação (`moveSession`)

**Objetivo.** Acompanhar migrações/moves internos.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,state,progress,source,destination" \
  "$UNITY_URL/api/types/moveSession/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,state,progress,source,destination` |
| Observar | Falha, pausa ou duração excessiva. |
| Interpretação / próxima ação | Correlacionar jobs, capacidade e alertas. |
| Cadência inicial | 1 min |
| Zabbix | LLD; state/progress/duração. |

### GET-095 — Sessões de importação (`importSession`)

**Objetivo.** Acompanhar importações de storage externo.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,state,progress,source,destination" \
  "$UNITY_URL/api/types/importSession/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,state,progress,source,destination` |
| Observar | Falha, pausa ou progresso parado. |
| Interpretação / próxima ação | Correlacionar fonte, rede e capacidade. |
| Cadência inicial | 1 min |
| Zabbix | LLD; state/progress/duração. |

## Performance e QoS

O fluxo de performance deste manual é integralmente GET: descubra os paths no catálogo metric, consulte metricValue e leia apenas objetos de consulta que já existam no array.

### GET-096 — Catálogo de métricas (`metric`)

**Objetivo.** Descobrir paths, unidades, intervalos e objetos suportados.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,path,name,unit,description,interval" \
  --data-urlencode "filter=path lk '<PADRAO>'" \
  "$UNITY_URL/api/types/metric/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,path,name,unit,description,interval` |
| Observar | Paths disponíveis e mudanças após upgrade. |
| Interpretação / próxima ação | Versionar o catálogo antes de criar itens Zabbix. |
| Cadência inicial | 24 h e após upgrade |
| Zabbix | Descoberta offline; não criar item por toda métrica sem necessidade. |

### GET-097 — Serviço de métricas (`metricService`)

**Objetivo.** Verificar estado global da coleta de métricas.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,health,state" \
  "$UNITY_URL/api/types/metricService/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,health,state` |
| Observar | Serviço parado ou health degradado. |
| Interpretação / próxima ação | Correlacionar alertas e capacidade do array. |
| Cadência inicial | 2 min |
| Zabbix | Item state/health. |

### GET-098 — Coleções de métricas (`metricCollection`)

**Objetivo.** Inventariar coleções configuradas e retenção.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,paths,interval,retention,state" \
  "$UNITY_URL/api/types/metricCollection/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,paths,interval,retention,state` |
| Observar | Coleção desativada, alterada ou excessiva. |
| Interpretação / próxima ação | Reduzir cardinalidade e ajustar retenção por processo administrativo. |
| Cadência inicial | 30 min |
| Zabbix | Inventário/change; não modificar pelo script GET. |

### GET-099 — Valores históricos (`metricValue`)

**Objetivo.** Ler séries históricas para paths selecionados.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=path,timestamp,value" \
  --data-urlencode "filter=path eq '<METRIC_PATH>'" \
  "$UNITY_URL/api/types/metricValue/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `path,timestamp,value` |
| Observar | IOPS, MB/s, latência, fila, CPU e cache conforme path. |
| Interpretação / próxima ação | Usar baseline e percentis; não alertar apenas por pico isolado. |
| Cadência inicial | 1–5 min |
| Zabbix | Master item por lote pequeno; trends no Zabbix. |

> **Nota.** O path é obrigatório; a referência 5.2 limita a no máximo cinco paths por página. Sempre use janela de tempo/paginação conforme o seu OE.

### GET-100 — Archives (`archive`)

**Objetivo.** Inventariar arquivos históricos de métricas.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,startTime,endTime,size,state" \
  "$UNITY_URL/api/types/archive/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,startTime,endTime,size,state` |
| Observar | Arquivo ausente, falho ou retenção inesperada. |
| Interpretação / próxima ação | Validar política de histórico e espaço. |
| Cadência inicial | 6 h |
| Zabbix | Inventário/state. |

### GET-101 — Políticas de I/O limit (`ioLimitPolicy`)

**Objetivo.** Auditar políticas QoS.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,state" \
  "$UNITY_URL/api/types/ioLimitPolicy/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,state` |
| Observar | Política desabilitada ou alterada. |
| Interpretação / próxima ação | Comparar com baseline e impacto de workload. |
| Cadência inicial | 15 min |
| Zabbix | LLD; state/change. |

### GET-102 — Regras de I/O limit (`ioLimitRule`)

**Objetivo.** Inventariar regras e seus alvos.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,policy,target,maxIOPS,maxBandwidth" \
  "$UNITY_URL/api/types/ioLimitRule/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,policy,target,maxIOPS,maxBandwidth` |
| Observar | Regra inesperada ou limite incompatível. |
| Interpretação / próxima ação | Validar owner e change record. |
| Cadência inicial | 15 min |
| Zabbix | LLD; configuração/change. |

### GET-103 — Configurações de I/O limit (`ioLimitSetting`)

**Objetivo.** Ler limites efetivos por recurso.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,resource,maxIOPS,maxBandwidth,burst" \
  "$UNITY_URL/api/types/ioLimitSetting/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,resource,maxIOPS,maxBandwidth,burst` |
| Observar | Limite efetivo divergente da política. |
| Interpretação / próxima ação | Correlacionar policy/rule e performance. |
| Cadência inicial | 15 min |
| Zabbix | LLD; change. |

### GET-104 — Queries de tempo real (`metricRealTimeQuery`)

**Objetivo.** Listar queries temporárias existentes.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,paths,interval,expirationTime,state" \
  "$UNITY_URL/api/types/metricRealTimeQuery/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,paths,interval,expirationTime,state` |
| Observar | Query abandonada ou inesperada. |
| Interpretação / próxima ação | Expirar/limpar apenas por fluxo autorizado. |
| Cadência inicial | 5 min quando usado |
| Zabbix | Inventário transitório. |

> **Nota.** Este cartão somente lista ou lê queries já existentes; ele não cria novas consultas.

### GET-105 — Resultados em tempo real (`metricQueryResult`)

**Objetivo.** Ler os resultados de uma query criada previamente.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,queryId,timestamp,values" \
  --data-urlencode "filter=queryId eq '<QUERY_ID>'" \
  "$UNITY_URL/api/types/metricQueryResult/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,queryId,timestamp,values` |
| Observar | Valores e perda de amostras. |
| Interpretação / próxima ação | Correlacionar com metricRealTimeQuery. |
| Cadência inicial | Conforme intervalo da query |
| Zabbix | Uso diagnóstico; para polling permanente prefira metricValue. |

## Segurança, identidade, criptografia e auditoria

A coleta deve usar uma conta dedicada de leitura mínima. Restrinja quem vê os dados exportados: usuários, endereços, certificados e topologia são informações sensíveis.

### GET-106 — Sessões de login (`loginSessionInfo`)

**Objetivo.** Observar sessões administrativas ativas quando expostas.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,user,sourceAddress,creationTime,lastActivityTime" \
  "$UNITY_URL/api/types/loginSessionInfo/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,user,sourceAddress,creationTime,lastActivityTime` |
| Observar | Sessão fora de horário, origem incomum ou duração excessiva. |
| Interpretação / próxima ação | Correlacionar com event category Authentication e SIEM. |
| Cadência inicial | 5 min |
| Zabbix | LLD de baixa retenção; triggers contextuais. |

### GET-107 — Usuários locais (`user`)

**Objetivo.** Inventariar contas, papéis e estado.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,role,enabled,locked" \
  "$UNITY_URL/api/types/user/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,role,enabled,locked` |
| Observar | Conta nova, habilitada, bloqueada ou papel alterado. |
| Interpretação / próxima ação | Comparar com IAM e change record. |
| Cadência inicial | 15 min |
| Zabbix | LLD; change/locked; nunca exportar segredos. |

### GET-108 — Papéis (`role`)

**Objetivo.** Auditar os papéis disponíveis e privilégios.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,description" \
  "$UNITY_URL/api/types/role/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,description` |
| Observar | Papel inesperado ou alteração. |
| Interpretação / próxima ação | Revisar RBAC e separação de funções. |
| Cadência inicial | 6 h |
| Zabbix | Inventário/change. |

### GET-109 — Mapeamento de papéis (`roleMapping`)

**Objetivo.** Auditar mapeamentos de grupos externos para RBAC.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,domain,group,role" \
  "$UNITY_URL/api/types/roleMapping/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,domain,group,role` |
| Observar | Grupo novo, removido ou elevado. |
| Interpretação / próxima ação | Validar IAM e aprovação. |
| Cadência inicial | 15 min |
| Zabbix | LLD; trigger de mudança com severidade alta para elevação. |

### GET-110 — LDAP administrativo (`ldapServer`)

**Objetivo.** Saúde e configuração de diretórios externos.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,address,port,protocol,health" \
  "$UNITY_URL/api/types/ldapServer/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,address,port,protocol,health` |
| Observar | Servidor indisponível, protocolo inseguro ou alteração. |
| Interpretação / próxima ação | Correlacionar DNS/TLS e manter acesso break-glass controlado. |
| Cadência inicial | 5 min |
| Zabbix | LLD; health/protocol/change. |

### GET-111 — Configurações de segurança (`securitySettings`)

**Objetivo.** Auditar controles globais suportados pelo OE.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,fipsMode,tlsMode,sessionTimeout" \
  "$UNITY_URL/api/types/securitySettings/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,fipsMode,tlsMode,sessionTimeout` |
| Observar | FIPS/TLS/session timeout divergente do baseline. |
| Interpretação / próxima ação | Tratar como configuração controlada; validar compatibilidade antes de mudar. |
| Cadência inicial | 15 min |
| Zabbix | Itens boolean/texto; change trigger. |

### GET-112 — Criptografia (`encryption`)

**Objetivo.** Verificar estado de Data at Rest Encryption.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,enabled,state,health,keyStatus" \
  "$UNITY_URL/api/types/encryption/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,enabled,state,health,keyStatus` |
| Observar | Desabilitada quando requerida, health ou keyStatus anormal. |
| Interpretação / próxima ação | Prioridade alta; correlacionar KMIP e alertas. |
| Cadência inicial | 2 min |
| Zabbix | Itens enabled/state/health; trigger crítico conforme política. |

### GET-113 — KMIP (`kmipServer`)

**Objetivo.** Saúde dos servidores externos de chaves.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,address,port,health,state" \
  "$UNITY_URL/api/types/kmipServer/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,address,port,health,state` |
| Observar | Servidor inacessível, certificado ou estado degradado. |
| Interpretação / próxima ação | Preservar redundância e acionar equipe de chaves. |
| Cadência inicial | 1 min |
| Zabbix | LLD; health/state e contagem saudável. |

### GET-114 — Certificados X.509 (`x509Certificate`)

**Objetivo.** Inventariar issuer, subject, validade e tamanho de chave.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,subject,issuer,validFrom,validTo,keyLength,signatureAlgorithm" \
  "$UNITY_URL/api/types/x509Certificate/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,subject,issuer,validFrom,validTo,keyLength,signatureAlgorithm` |
| Observar | Expiração próxima, issuer inesperado, chave fraca ou algoritmo legado. |
| Interpretação / próxima ação | Renovar com antecedência e validar cadeia. |
| Cadência inicial | 6 h |
| Zabbix | LLD; dias até validTo e change issuer/keyLength. |

### GET-115 — CRLs (`crl`)

**Objetivo.** Auditar listas de revogação e validade.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,issuer,thisUpdate,nextUpdate,state" \
  "$UNITY_URL/api/types/crl/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,issuer,thisUpdate,nextUpdate,state` |
| Observar | CRL vencida, não atualizada ou issuer inesperado. |
| Interpretação / próxima ação | Restaurar distribuição/validação de revogação. |
| Cadência inicial | 6 h |
| Zabbix | LLD; dias até nextUpdate/state. |

### GET-116 — Configuração iSCSI (`iscsiSettings`)

**Objetivo.** Auditar parâmetros globais iSCSI.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,enabled,authenticationMode" \
  "$UNITY_URL/api/types/iscsiSettings/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,enabled,authenticationMode` |
| Observar | Autenticação ou estado alterado. |
| Interpretação / próxima ação | Comparar com baseline de segurança. |
| Cadência inicial | 6 h |
| Zabbix | Inventário/change. |

### GET-117 — CHAP remoto (`rpChapSettings`)

**Objetivo.** Auditar se CHAP está configurado sem coletar segredo.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,enabled,userName" \
  "$UNITY_URL/api/types/rpChapSettings/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,enabled,userName` |
| Observar | CHAP desabilitado onde requerido ou usuário alterado. |
| Interpretação / próxima ação | Corrigir por fluxo seguro; nunca registrar secret. |
| Cadência inicial | 15 min |
| Zabbix | Itens enabled/username; mascarar logs. |

### GET-118 — ESRS/SupportAssist parâmetros (`esrsParam`)

**Objetivo.** Auditar parâmetros de conectividade de suporte remoto.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,value" \
  "$UNITY_URL/api/types/esrsParam/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,value` |
| Observar | Mudança inesperada ou modo inseguro. |
| Interpretação / próxima ação | Validar com política de suporte e rede. |
| Cadência inicial | 6 h |
| Zabbix | Inventário/change; restrinja os dados. |

### GET-119 — ESRS policy manager (`esrsPolicyManager`)

**Objetivo.** Estado de políticas de suporte remoto.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,health,state" \
  "$UNITY_URL/api/types/esrsPolicyManager/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,health,state` |
| Observar | Serviço desativado/degradado. |
| Interpretação / próxima ação | Correlacionar supportService/proxy e políticas. |
| Cadência inicial | 5 min |
| Zabbix | State/health. |

### GET-120 — Serviço de suporte (`supportService`)

**Objetivo.** Saúde da conectividade Dell Support/SupportAssist.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,health,state,lastConnectTime" \
  "$UNITY_URL/api/types/supportService/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,health,state,lastConnectTime` |
| Observar | Sem conexão, health ou última conexão antiga. |
| Interpretação / próxima ação | Verificar proxy, DNS, firewall e contrato. |
| Cadência inicial | 5 min |
| Zabbix | Health/state/idade da última conexão. |

### GET-121 — Proxy de suporte (`supportProxy`)

**Objetivo.** Auditar proxy usado pelo suporte remoto.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,address,port,enabled,health" \
  "$UNITY_URL/api/types/supportProxy/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,address,port,enabled,health` |
| Observar | Proxy desabilitado/alterado ou health degradado. |
| Interpretação / próxima ação | Comparar com baseline; não exportar credenciais. |
| Cadência inicial | 15 min |
| Zabbix | Health/enabled/change. |

## Virtualização e integrações

Use estes GETs quando o array atende VMware/VVol. Eles complementam, mas não substituem, a telemetria do vCenter e dos hosts ESXi.

### GET-122 — Protocol endpoints VMware (`vmwarePE`)

**Objetivo.** Saúde e associação de PEs block.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,state,storageResource" \
  "$UNITY_URL/api/types/vmwarePE/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,state,storageResource` |
| Observar | PE degradado ou indisponível. |
| Interpretação / próxima ação | Correlacionar hosts, FC/iSCSI paths e datastore. |
| Cadência inicial | 2 min |
| Zabbix | LLD; health/state. |

### GET-123 — NAS protocol endpoints (`vmwareNasPEServer`)

**Objetivo.** Saúde dos PEs NAS.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,state,nasServer" \
  "$UNITY_URL/api/types/vmwareNasPEServer/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,state,nasServer` |
| Observar | PE NAS indisponível/degradado. |
| Interpretação / próxima ação | Correlacionar NAS server e file interfaces. |
| Cadência inicial | 2 min |
| Zabbix | LLD; health/state. |

### GET-124 — Host groups (`hostGroup`)

**Objetivo.** Inventariar grupos e membros.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,hosts" \
  "$UNITY_URL/api/types/hostGroup/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,hosts` |
| Observar | Grupo ou membership alterado. |
| Interpretação / próxima ação | Validar com cluster/vCenter e change record. |
| Cadência inicial | 15 min |
| Zabbix | LLD; health/change. |

### GET-125 — Host group LUNs (`hostGroupLUN`)

**Objetivo.** Auditar mapeamentos para grupos.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,hostGroup,lun,hostLUNId" \
  "$UNITY_URL/api/types/hostGroupLUN/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,hostGroup,lun,hostLUNId` |
| Observar | Mapeamento adicionado/removido. |
| Interpretação / próxima ação | Comparar com baseline de masking. |
| Cadência inicial | 15 min |
| Zabbix | Inventário/change. |

### GET-126 — VMware host group LUNs (`hostGroupVmwareLUN`)

**Objetivo.** Cobrir mapeamentos VMware específicos.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,hostGroup,lun,hostLUNId" \
  "$UNITY_URL/api/types/hostGroupVmwareLUN/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,hostGroup,lun,hostLUNId` |
| Observar | Mudança inesperada. |
| Interpretação / próxima ação | Correlacionar datastore e cluster. |
| Cadência inicial | 15 min |
| Zabbix | Inventário/change. |

### GET-127 — VVol datastores (`hostVVolDatastore`)

**Objetivo.** Associação host–VVol datastore.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,host,datastore,state" \
  "$UNITY_URL/api/types/hostVVolDatastore/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,host,datastore,state` |
| Observar | Associação ausente ou estado anormal. |
| Interpretação / próxima ação | Correlacionar PE, vCenter e host paths. |
| Cadência inicial | 5 min |
| Zabbix | LLD; state/change. |

### GET-128 — VMs (`vm`)

**Objetivo.** Inventariar VMs conhecidas pela integração.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,state,host" \
  "$UNITY_URL/api/types/vm/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,state,host` |
| Observar | Objeto órfão ou health anormal. |
| Interpretação / próxima ação | Usar vCenter como fonte principal e Unity para correlação. |
| Cadência inicial | 15 min |
| Zabbix | LLD seletiva; evitar cardinalidade desnecessária. |

### GET-129 — Discos de VM (`vmDisk`)

**Objetivo.** Relacionar discos virtuais a recursos do Unity.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,vm,storageResource,size" \
  "$UNITY_URL/api/types/vmDisk/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,vm,storageResource,size` |
| Observar | Disco órfão, health ou tamanho alterado. |
| Interpretação / próxima ação | Correlacionar VM/datastore/storage resource. |
| Cadência inicial | 15 min |
| Zabbix | LLD seletiva; inventário/capacidade. |

### GET-130 — SSC (`ssc`)

**Objetivo.** Inspecionar Storage System Connectivity/integration metadata.

```bash
curl --silent --show-error --fail-with-body \
  --cacert "$UNITY_CA" \
  --cookie "$COOKIE_JAR" \
  --header 'Accept: application/json' \
  --header 'Content-Type: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  --get \
  --data-urlencode "fields=id,name,health,state" \
  "$UNITY_URL/api/types/ssc/instances" | jq .
```

| Elemento | Orientação |
|---|---|
| Campos sugeridos | `id,name,health,state` |
| Observar | Integração degradada ou estado alterado. |
| Interpretação / próxima ação | Correlacionar vCenter/ESXi e suporte. |
| Cadência inicial | 10 min |
| Zabbix | State/health. |

## Performance por GET: histórico e consultas existentes

O desenho recomendado para monitoramento contínuo é: (1) descobrir paths com `metric`; (2) selecionar um conjunto pequeno que responda a perguntas operacionais; (3) consultar `metricValue` em janelas com sobreposição; (4) deduplicar por path+timestamp; (5) armazenar trends no Zabbix. Exemplos de famílias úteis são IOPS, throughput, latência, queue depth, utilização de SP/CPU e cache — os nomes exatos dos paths devem vir do catálogo do seu array.

Para diagnóstico, `metricRealTimeQuery` e `metricQueryResult` permitem ler consultas e amostras que já existam no array. Esta edição não cria consultas. Para polling permanente, prefira `metricValue` e não consulte centenas de métricas sem uma pergunta operacional definida.

## Arquitetura recomendada no Zabbix 7.4

- Um usuário Unity exclusivo, com privilégio mínimo de leitura e origem de rede restrita.
- Um item mestre por domínio e cadência, não um login por métrica. Ex.: health 60 s, capacidade 300 s, segurança 300–900 s, inventário 6–24 h.
- Itens dependentes extraem JSONPath; Low-Level Discovery cria entidades por `id` estável e usa `name` apenas como rótulo.
- Pré-processamento deve distinguir resposta vazia válida, endpoint incompatível, HTTP 401/403, 404 e timeout.
- Triggers devem ter histerese e dependências: pool crítico suprime alertas derivados redundantes; falha de SP/porta ajuda a explicar host paths.
- Para capacidade, combine percentual, bytes livres e `timeleft()`/forecast. Para performance, use percentis/baseline e duração; um pico isolado raramente é incidente.
- Guarde JSON bruto por tempo curto para troubleshooting; proteja dados de usuários, IPs, certificados e topologia.

### Matriz de cadência inicial

| Plano | Recursos típicos | Intervalo | Estratégia |
|---|---|---|---|
| Crítico | system, alert, SP, portas, paths, replicationSession | 60 s | Payload pequeno; falha após 2–3 coletas. |
| Saúde | hardware, NAS, KMIP, supportService | 2–5 min | LLD e health.value. |
| Capacidade | systemCapacity, pool, LUN, filesystem | 5–10 min | Bytes + percentual + tendência. |
| Performance | metricValue paths selecionados | 1–5 min | Lotes pequenos; deduplicação temporal. |
| Segurança | event, user, roleMapping, x509, syslog | 5–15 min | Mudança + SIEM; certificados a cada 6 h. |
| Inventário | versões, licenças, limites, shares | 6–24 h | Diff controlado. |

### Exemplo de mapa de triggers

| Sinal | Regra inicial | Cuidados |
|---|---|---|
| health.value | >=10 por 2 coletas | OK_BUT=7 pode ser aviso; UNKNOWN exige trigger separado. |
| alert.severity | <=4 enquanto alerta existir | Escala inversa; deduplicar messageId+resource. |
| Pool usado | >=80% aviso; >=90% alto | Ajustar por tamanho, thin provisioning e forecast. |
| Certificado | validTo < 30 dias | Criar faixas 60/30/14/7 dias conforme processo. |
| Replicação | atraso > RPO e state anormal | Considerar janelas, link e sessões pausadas aprovadas. |
| Host paths | ativos < mínimo esperado | Definir mínimo por host/protocolo; correlacionar manutenção. |

## Diagnóstico de HTTP e incompatibilidade

| Sintoma | Causa provável | Ação |
|---|---|---|
| TLS/certificate error | CA ausente, hostname divergente ou certificado expirado | Instalar cadeia correta; não normalizar `-k` em produção. |
| 401 | Credencial/cookie expirado | Reautenticar, revisar relógio e conta. |
| 403 | Privilégio insuficiente ou política | Revisar RBAC mínimo; não elevar sem necessidade. |
| 404 | Tipo/URI não existe no OE | Consultar on-array API Reference e a versão real. |
| 422/400 | Campo, filtro ou operador inválido | Remover `fields`, testar coleção e reintroduzir parâmetros. |
| 429/503 | Carga ou limite temporário | Backoff com jitter; reduzir cardinalidade/frequência. |
| 200 com entries vazio | Nenhum objeto/filtro muito restrito | Tratar como dado válido; conferir filtro e escopo. |
| Payload truncado | Paginação não percorrida | Ler page/per_page e metadados de paginação. |

## Catálogo integral de resource types — baseline 5.2

A tabela abaixo fecha o universo publicado pela referência 5.2. Para cada tipo, o GET-base é `GET /api/types/<tipo>/instances`; quando houver um objeto conhecido, use `GET /api/instances/<tipo>/<id>`. ‘Cartão’ significa que há orientação detalhada neste manual; ‘Referência/condicional’ significa endpoint válido, porém mais administrativo, raro, dependente de licença ou pouco útil para polling contínuo.

| Resource type | Cobertura |
|---|---|
| aclUser | Referência/condicional |
| alert | Cartão de monitoramento |
| alertConfig | Referência/condicional |
| alertConfigSNMPTarget | Referência/condicional |
| alertEmailConfig | Referência/condicional |
| archive | Cartão de monitoramento |
| autodownloadSoftwareVersion | Referência/condicional |
| basicSystemInfo | Cartão de monitoramento |
| battery | Cartão de monitoramento |
| candidateSoftwareVersion | Cartão de monitoramento |
| capabilityProfile | Referência/condicional |
| cifsServer | Cartão de monitoramento |
| cifsShare | Cartão de monitoramento |
| configCaptureResult | Cartão de monitoramento |
| coreDump | Cartão de monitoramento |
| crl | Cartão de monitoramento |
| dae | Cartão de monitoramento |
| dataCollectionResult | Referência/condicional |
| datastore | Cartão de monitoramento |
| dhsmConnection | Cartão de monitoramento |
| dhsmServer | Cartão de monitoramento |
| disk | Cartão de monitoramento |
| diskGroup | Cartão de monitoramento |
| dnsServer | Cartão de monitoramento |
| dpe | Cartão de monitoramento |
| encryption | Cartão de monitoramento |
| esrsParam | Cartão de monitoramento |
| esrsPolicyManager | Cartão de monitoramento |
| ethernetPort | Cartão de monitoramento |
| event | Cartão de monitoramento |
| fan | Cartão de monitoramento |
| fastCache | Cartão de monitoramento |
| fastVP | Cartão de monitoramento |
| fcPort | Cartão de monitoramento |
| feature | Referência/condicional |
| fileDNSServer | Cartão de monitoramento |
| fileEventsPool | Cartão de monitoramento |
| fileEventsPublisher | Cartão de monitoramento |
| fileInterface | Cartão de monitoramento |
| fileKerberosServer | Cartão de monitoramento |
| fileLDAPServer | Cartão de monitoramento |
| fileNDMPServer | Cartão de monitoramento |
| fileNISServer | Cartão de monitoramento |
| filesystem | Cartão de monitoramento |
| fsnPort | Cartão de monitoramento |
| ftpServer | Referência/condicional |
| host | Cartão de monitoramento |
| hostContainer | Referência/condicional |
| hostGroup | Cartão de monitoramento |
| hostGroupLUN | Cartão de monitoramento |
| hostGroupVmwareLUN | Cartão de monitoramento |
| hostIPPort | Referência/condicional |
| hostInitiator | Cartão de monitoramento |
| hostInitiatorPath | Cartão de monitoramento |
| hostLUN | Cartão de monitoramento |
| hostVVolDatastore | Cartão de monitoramento |
| importSession | Cartão de monitoramento |
| installedSoftwareVersion | Cartão de monitoramento |
| ioLimitPolicy | Cartão de monitoramento |
| ioLimitRule | Cartão de monitoramento |
| ioLimitSetting | Cartão de monitoramento |
| ioModule | Cartão de monitoramento |
| ipInterface | Cartão de monitoramento |
| ipPort | Cartão de monitoramento |
| iscsiNode | Cartão de monitoramento |
| iscsiPortal | Cartão de monitoramento |
| iscsiSettings | Cartão de monitoramento |
| job | Cartão de monitoramento |
| kmipServer | Cartão de monitoramento |
| lcc | Cartão de monitoramento |
| ldapServer | Cartão de monitoramento |
| license | Cartão de monitoramento |
| linkAggregation | Cartão de monitoramento |
| loginSessionInfo | Cartão de monitoramento |
| lun | Cartão de monitoramento |
| memoryModule | Cartão de monitoramento |
| metric | Cartão de monitoramento |
| metricCollection | Cartão de monitoramento |
| metricQueryResult | Cartão de monitoramento |
| metricRealTimeQuery | Cartão de monitoramento |
| metricService | Cartão de monitoramento |
| metricValue | Cartão de monitoramento |
| mgmtInterface | Cartão de monitoramento |
| mgmtInterfaceSettings | Cartão de monitoramento |
| moveSession | Cartão de monitoramento |
| nasServer | Cartão de monitoramento |
| nfsServer | Cartão de monitoramento |
| nfsShare | Cartão de monitoramento |
| ntpServer | Cartão de monitoramento |
| pool | Cartão de monitoramento |
| poolConsumer | Cartão de monitoramento |
| poolConsumerAllocation | Cartão de monitoramento |
| poolUnit | Cartão de monitoramento |
| powerSupply | Cartão de monitoramento |
| preferredInterfaceSettings | Cartão de monitoramento |
| quotaConfig | Cartão de monitoramento |
| raidGroup | Cartão de monitoramento |
| remoteInterface | Cartão de monitoramento |
| remoteSyslog | Cartão de monitoramento |
| remoteSystem | Cartão de monitoramento |
| replicationInterface | Cartão de monitoramento |
| replicationSession | Cartão de monitoramento |
| role | Cartão de monitoramento |
| roleMapping | Cartão de monitoramento |
| route | Cartão de monitoramento |
| rpChapSettings | Cartão de monitoramento |
| sasPort | Cartão de monitoramento |
| scheduleTimezone | Referência/condicional |
| securitySettings | Cartão de monitoramento |
| serviceAction | Cartão de monitoramento |
| serviceContract | Cartão de monitoramento |
| serviceInfo | Referência/condicional |
| smtpServer | Cartão de monitoramento |
| snap | Cartão de monitoramento |
| snapSchedule | Cartão de monitoramento |
| softwareUpgradeSession | Cartão de monitoramento |
| ssc | Cartão de monitoramento |
| ssd | Cartão de monitoramento |
| storageProcessor | Cartão de monitoramento |
| storageResource | Cartão de monitoramento |
| storageResourceCapabilityProfile | Referência/condicional |
| storageTier | Cartão de monitoramento |
| supportAsset | Referência/condicional |
| supportProxy | Cartão de monitoramento |
| supportService | Cartão de monitoramento |
| system | Cartão de monitoramento |
| systemCapacity | Cartão de monitoramento |
| systemInformation | Cartão de monitoramento |
| systemLimit | Cartão de monitoramento |
| systemTime | Cartão de monitoramento |
| technicalAdvisory | Cartão de monitoramento |
| tenant | Referência/condicional |
| treeQuota | Cartão de monitoramento |
| udoctorPackage | Cartão de monitoramento |
| uncommittedPort | Cartão de monitoramento |
| upgradeSession | Cartão de monitoramento |
| urServer | Referência/condicional |
| user | Cartão de monitoramento |
| userQuota | Cartão de monitoramento |
| virtualVolume | Cartão de monitoramento |
| virusChecker | Cartão de monitoramento |
| vlanInfo | Cartão de monitoramento |
| vm | Cartão de monitoramento |
| vmDisk | Cartão de monitoramento |
| vmwareNasPEServer | Cartão de monitoramento |
| vmwarePE | Cartão de monitoramento |
| x509Certificate | Cartão de monitoramento |

### Tipos condicionais que merecem decisão explícita

`alertConfig`, `alertConfigSNMPTarget`, `alertEmailConfig`, `ftpServer`, `autodownloadSoftwareVersion`, `supportAsset`, `tenant`, `urServer`, `feature`, `capabilityProfile`, `storageResourceCapabilityProfile`, `hostContainer`, `hostIPPort`, `aclUser`, `scheduleTimezone`, `serviceInfo` e `dataCollectionResult` são úteis para inventário, auditoria ou suporte, mas normalmente não justificam polling de alta frequência. Consulte-os com o padrão genérico e promova-os a itens permanentes somente quando houver uma pergunta operacional e um owner.

## Checklist de implantação

1. Confirmar Unity OE/API em `basicSystemInfo` e abrir o on-array API Reference.
2. Criar conta de leitura mínima, CA confiável e secret store; restringir origem.
3. Executar `system`, `alert`, `storageProcessor`, `pool` e `event` manualmente.
4. Validar `fields` e filtros no modelo/OE real; registrar incompatibilidades.
5. Implementar sessão/cookies, timeouts, backoff, paginação e telemetria do coletor.
6. Criar masters/dependentes/LLD no Zabbix; limitar cardinalidade.
7. Calibrar triggers com 2–4 semanas de baseline e janelas de manutenção.
8. Integrar eventos de autenticação/auditoria ao SIEM e testar retenção.
9. Testar falhas controladas: credencial inválida, timeout, página extra e endpoint ausente.
10. Revisar o catálogo após cada upgrade de Unity OE.

## Fontes

- Dell Developer — Dell EMC Unity REST API 5.2, tutorials e API reference: https://developer.dell.com/apis/3028/versions/5.2.0/docs/TUTORIALS/tutorials.md
- Documentação hospedada no array: https://<UNITY>/apidocs/index.html
- Programmer's Guide hospedado no array: https://<UNITY>/apidocs/programmers-guide/index.html
- Dell EMC Unity Family Version 5.2 Unisphere Management REST API Reference Guide, P/N 302-005-259 REV 08.

---

Este material é operacional, não substitui o procedimento de suporte ou mudança da organização. Todos os comandos entregues são GET; qualquer correção permanece fora de escopo e requer autorização separada.
