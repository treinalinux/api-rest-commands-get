# Unity XT — especificação de coleta

## 1. Decisão

**Mínimo recomendado:** Unisphere Management REST API em HTTPS/443.  
**Complemento:** métricas REST de performance com Statistics Logging habilitado e traps/eventos para notificação rápida.

Unity oferece recursos REST para sistema, pools, storage, alertas, proteção e métricas. O próprio array publica a referência correspondente à versão em:

```text
https://UNITY_FQDN/apidocs/index.html
```

Essa referência instalada tem precedência sobre qualquer exemplo deste documento.

## 2. Escopo mínimo

| Critério | Entrega mínima |
|---|---|
| Disponibilidade | Sistema, storage processors, discos, fontes/fans, portas, NAS/services e alertas ativos. |
| Capacidade | Pools total/usado/livre/subscribed; LUN/filesystem somente se houver ação e dono. |
| Performance | SP CPU, IOPS, bandwidth e latência agregados; detalhe por LUN/filesystem só quando necessário. |
| Proteção | Replication sessions, snapshots/schedules e último sync/estado. |
| Segurança observável | OE/API, certificado, ESRS/SupportAssist/CloudIQ conforme versão, protocolos e alertas de segurança. |

## 3. Pré-requisitos

- Modelo Unity XT e OE exato.
- Management IP/FQDN e TCP 443.
- Conta de serviço dedicada com menor role que permita todos os `GET` e as consultas temporárias de performance necessárias.
- CA/certificado confiável.
- Statistics Logging habilitado nos SPs para coleta de métricas de performance.
- NTP consistente.
- Inventário de pools, LUNs, filesystems, NAS servers, replicações e snapshots realmente usados.
- Política de cardinalidade: pool/SP no mínimo; LUN/filesystem sob demanda.

## 4. Descobrir versão antes de autenticar

O recurso `basicSystemInfo` pode ser consultado sem login:

```bash
export UNITY_HOST='unity-gerencia.exemplo'
export UNITY_CA_FILE='/etc/pki/ca-trust/source/anchors/unity-ca.pem'
```

```bash
curl --fail-with-body --silent --show-error \
  --cacert "$UNITY_CA_FILE" \
  --header 'Accept: application/json' \
  "https://$UNITY_HOST/api/types/basicSystemInfo/instances" \
  --output unity_basic_system_info.json
```

Extrair da resposta real:

- `model`;
- `name`;
- `softwareVersion`;
- `apiVersion`;
- `earliestAPIVersion`.

Guardar essa resposta junto às evidências. Ela decide qual documentação e quais campos podem ser usados.

## 5. Autenticação e sessão

O Unity usa HTTP Basic e requer:

```http
Accept: application/json
X-EMC-REST-CLIENT: true
```

O primeiro `GET` autenticado retorna cookies e `EMC-CSRF-TOKEN`. O token CSRF é necessário para `POST` e `DELETE`; cookies devem ser reutilizados.

```bash
export UNITY_USER='usuario_monitor'
read -r -s -p 'Senha Unity: ' UNITY_PASS
umask 077
```

```bash
curl --fail-with-body --silent --show-error --location \
  --cacert "$UNITY_CA_FILE" \
  --user "$UNITY_USER:$UNITY_PASS" \
  --cookie-jar /tmp/unity-cookie.txt \
  --dump-header /tmp/unity-headers.txt \
  --header 'Accept: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  "https://$UNITY_HOST/api/types/system/instances?compact=true&fields=id,name,model,serialNumber,health" \
  --output unity_system.json
```

Para chamadas somente `GET`, não é necessário enviar CSRF em cada requisição, mas é necessário manter autenticação/cookies conforme a versão. Para performance real-time que crie uma query temporária via `POST`, enviar também:

```http
EMC-CSRF-TOKEN: TOKEN_RECEBIDO
Content-Type: application/json
```

Nunca registrar senha, cookie ou CSRF token. Em produção, usar o mecanismo de segredos da equipe Zabbix e apagar arquivos temporários.

## 6. Padrão de consulta e extração

Uma coleção usa:

```text
/api/types/RECURSO/instances?compact=true&fields=CAMPO1,CAMPO2
```

O payload normalmente contém:

```text
entries[] -> content -> campos solicitados
```

Iterar todo `entries[]` e usar `content.id` como identidade. Não usar `entries[0]` como objeto permanente.

### Paginação

Usar:

```text
per_page=N&page=P&with_entrycount=true
```

Seguir a contagem/links até a última página. Definir limite máximo de segurança e detectar repetição de página.

## 7. Chamadas mínimas

### Pools/capacidade

```bash
curl --fail-with-body --silent --show-error --location \
  --cacert "$UNITY_CA_FILE" \
  --user "$UNITY_USER:$UNITY_PASS" \
  --cookie /tmp/unity-cookie.txt \
  --header 'Accept: application/json' \
  --header 'X-EMC-REST-CLIENT: true' \
  "https://$UNITY_HOST/api/types/pool/instances?compact=true&with_entrycount=true&fields=id,name,health,sizeTotal,sizeUsed,sizeFree,sizeSubscribed" \
  --output unity_pools.json
```

Os campos de tamanho são bytes na documentação da API utilizada, mas a equipe deve confirmar a unidade na referência da versão. Calcular:

```text
used_pct = 100 * sizeUsed / sizeTotal
free_pct = 100 * sizeFree / sizeTotal
subscribed_pct = 100 * sizeSubscribed / sizeTotal
```

Tratar `sizeTotal=0` como inválido. `sizeSubscribed` representa provisionamento lógico e pode ser maior que `sizeTotal`; não é erro de cálculo.

### Alertas

```http
GET /api/types/alert/instances?compact=true&fields=id,message,messageId,severity,timestamp,description,resolution,component
```

Confirmar nomes de campo no `/apidocs` instalado. Preservar ID, severidade numérica, descrição, resolução e timestamp. Usar o mapa de enumeração da versão; não presumir que o maior número seja sempre a maior severidade.

### Sistema e componentes

Consultar recursos existentes na referência da versão:

- `system`;
- `storageProcessor`;
- `disk`;
- `powerSupply`, `fan`, `battery`, `dae`/`dpe`;
- `fcPort`, `ethernetPort`, `iscsiPortal`;
- `nasServer` e serviços de arquivo, quando aplicável;
- `installedSoftwareVersion`;
- `supportService`/recursos de conectividade disponíveis.

Solicitar explicitamente `id`, `name`, `health` e os campos mínimos. O campo `health` é um objeto incorporado, geralmente com `value`, `description` e `resolution`; guardar os três.

### Proteção

```http
GET /api/types/replicationSession/instances?compact=true&with_entrycount=true&fields=CAMPOS_VALIDOS_DA_VERSAO
```

No `/apidocs`, selecionar:

- ID/nome e tipo da sessão;
- source/destination;
- health;
- operational/sync state;
- RPO;
- último sync/sucesso;
- transfer remaining/rate quando exposto;
- erro/resolução.

Consultar `snap` e `snapSchedule` apenas no nível necessário. Não descobrir milhares de snapshots individuais se o requisito é somente falha de schedule e consumo agregado.

## 8. Performance REST

### Passo 1 — Catálogo

```http
GET /api/types/metric/instances?compact=true&fields=id,name,path,isRealtimeAvailable,isHistoricalAvailable
```

Salvar o catálogo da versão e escolher caminhos que correspondam a:

- utilização de SP;
- IOPS read/write;
- bandwidth read/write;
- latência/response time;
- portas front-end, se necessário;
- LUN/filesystem somente quando exigido.

### Passo 2 — Escolher modo

- **Historical:** usar `metricValue` e filtros documentados quando a série histórica da métrica estiver disponível.
- **Real time:** criar uma `metricRealTimeQuery` temporária, obter seu ID e consultar `metricQueryResult` filtrado pelo `queryId`.

Recursos documentados:

```text
/api/types/metricValue/instances
/api/types/metricRealTimeQuery/instances
/api/types/metricQueryResult/instances
```

### Passo 3 — Real time

1. Fazer `GET` autenticado para obter cookie e CSRF token.
2. Consultar catálogo `metric` e selecionar somente paths `isRealtimeAvailable`.
3. Ler no `/apidocs` o schema exato de criação de `metricRealTimeQuery` da OE instalada.
4. Executar o `POST` com cookie, `EMC-CSRF-TOKEN` e JSON do schema.
5. Guardar o ID retornado, sem dados sensíveis.
6. Consultar `metricQueryResult` filtrando `queryId`.
7. Encerrar/remover a query conforme operação documentada ou deixar expirar, conforme a release.

Não fornecer um body universal de criação: paths e schema precisam ser validados na OE instalada. A equipe deve entregar o body sanitizado que efetivamente funcionou.

### Passo 4 — Unidade e escopo

Para cada métrica, guardar:

- path completo;
- ID do objeto representado no path;
- timestamp;
- intervalo;
- valor;
- unidade do catálogo/guia de performance;
- agregação: average, sum, rate etc.;
- disponibilidade realtime/historical.

Não somar latências nem médias simples entre SPs/LUNs sem ponderação documentada.

## 9. Mapeamento funcional

| Critério | Métrica | Recurso | Extração |
|---|---|---|---|
| Disponibilidade | Sistema | `system` | `entries[].content.health.{value,description,resolution}`. |
| Disponibilidade | SP/componentes/portas | respectivos recursos | Descobrir por `id`; preservar health completo. |
| Disponibilidade | Alertas | `alert` | ID, severity, messageId, timestamp, description e resolution. |
| Capacidade | Pool | `pool` | sizeTotal/Used/Free/Subscribed em bytes confirmados. |
| Capacidade | LUN/filesystem | recursos específicos | Somente com ação definida; diferenciar provisionado e consumido. |
| Performance | SP/IO/latência/bandwidth | metric catalog/query/result | Path, timestamp, intervalo, valor e unidade. |
| Proteção | Replicação | `replicationSession` | health, sync/oper state, RPO, último sucesso e restante. |
| Proteção | Snapshots | `snap`, `snapSchedule` | schedules/estado/uso agregado conforme requisito. |
| Segurança | OE/API | `basicSystemInfo`, software | Versão diária e versão API. |
| Segurança | Certificado | `x509Certificate` se autorizado + TLS | Não coletar private key; validar cadeia/expiração. |
| Segurança | Suporte remoto | recursos support/ESRS disponíveis | Estado documentado; recurso ausente é não suportado. |

## 10. Frequência inicial

| Coleta | Frequência |
|---|---:|
| Endpoint/sistema/alertas | 1 a 2 minutos |
| SP/componentes/portas | 3 a 5 minutos |
| Performance agregada | 1 a 5 minutos |
| Pools/capacidade | 10 a 15 minutos |
| Replicação | 5 minutos |
| Inventário/OE/API | 12 a 24 horas |
| Certificado | 12 a 24 horas |

## 11. Tratamento de falhas

- `401`: credencial/cookie; `403`: role; separar de array indisponível.
- `422`: filtro/campo inválido ou incompatibilidade de API; não é métrica zero.
- `200` com `entries: []` pode ser legítimo.
- Campo ausente/`null` não é OK nem zero.
- CSRF expirado exige nova sessão controlada.
- Alertas resolvidos não devem permanecer ativos.
- Performance sem ponto recente é telemetria atrasada; comparar timestamp.
- Paginação incompleta deve invalidar apenas o inventário afetado, não fabricar total parcial.

## 12. Evidências obrigatórias

- `basicSystemInfo` com OE/API.
- cópia/exportação do `/apidocs` ou referência exata usada.
- JSON de system, pools, SPs, componentes e alertas.
- pool saudável e, se houver, degradado.
- catálogo de metrics selecionadas.
- body sanitizado e resposta de real-time query, se usada.
- replication session saudável/degradada, se configurada.
- teste de paginação.
- comparação com Unisphere no mesmo instante.
- role mínima e lista de endpoints autorizados.

## 13. Testes de aceitação

- [ ] `basicSystemInfo` identifica OE e API.
- [ ] TLS funciona sem `-k`.
- [ ] Conta de serviço lê todos os recursos necessários.
- [ ] Pools e bytes conferem com Unisphere.
- [ ] `entries[]` é iterado por ID, sem posição fixa.
- [ ] Paginação retorna o inventário completo.
- [ ] Health value/description/resolution são preservados.
- [ ] Uma métrica tem path, unidade, intervalo e timestamp validados.
- [ ] Replicação/snapshot não configurado é não aplicável.
- [ ] Cookie/CSRF/senha não aparecem em evidências.

## 14. Referências oficiais

- [Dell Unity — API Developer Portal 5.2 e tutoriais](https://developer.dell.com/apis/3028/versions/5.2.0/docs/TUTORIALS/tutorials.md)
- [Dell Unity — Unisphere Management REST API](https://www.dell.com/support/manuals/en-us/unity-500/unity_p_restapi_prog_guide/the-unisphere-management-rest-api?guid=guid-a2e37655-3818-489f-8305-27e73d93fdf5&lang=en-us)
- [Dell Unity — autenticação](https://www.dell.com/support/manuals/en-us/unity-600/unity_p_restapi_prog_guide/connecting-and-authenticating?guid=guid-0f797771-a25d-4c05-8faf-f06ce6633a61&lang=en-us)
- [Dell Unity — basicSystemInfo](https://www.dell.com/support/manuals/en-us/unity-400/unity_p_restapi_prog_guide/Retrieving-basic-system-information?guid=guid-4cacde9e-409e-4ece-9903-1405fc3ff011&lang=en-us)
- [Dell Unity — consulta de alertas](https://www.dell.com/support/manuals/en-us/unity-400/unity_p_restapi_prog_guide/retrieving-data-for-multiple-occurrences-in-a-collection?guid=guid-e736d8e2-5bed-4351-ae02-2d6f4d48435e&lang=en-us)
- [Dell Unity — paginação](https://www.dell.com/support/manuals/en-us/unity-300/unity_p_restapi_prog_guide/paginating-response-data?guid=guid-17a9e9ee-a766-4ecf-a00e-3cbc25a2435d&lang=en-us)
