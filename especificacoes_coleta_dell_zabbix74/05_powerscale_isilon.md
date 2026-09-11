# PowerScale / Isilon — especificação de coleta

## 1. Decisão

**Mínimo recomendado:** OneFS REST API pela interface de gerenciamento, usando HTTPS e RBAC de leitura.  
**Complemento:** eventos/traps para baixa latência de notificação; polling REST permanece como reconciliação.

O OneFS expõe inventário, configuração, capacidade, estatísticas, eventos e SyncIQ em uma API estruturada e autodocumentada. Não fixar a versão `14` vista nos exemplos da documentação: primeiro descobrir a versão oferecida pelo cluster.

## 2. Escopo mínimo

| Critério | Entrega mínima |
|---|---|
| Disponibilidade | Cluster, nós, drives/componentes essenciais, jobs e grupos de eventos ativos. |
| Capacidade | Filesystem total/usado/livre; node pools ou quotas somente conforme escopo. |
| Performance | CPU, disco, rede, protocolos, IOPS, throughput e latência disponíveis nas statistics keys. |
| Proteção | SyncIQ policies/reports, snapshots e saúde de jobs de proteção. |
| Segurança observável | Versão, TLS, auditoria/configuração, antivírus/ICAP/SmartLock quando configurados e autorizados. |

## 3. Pré-requisitos

- Modelo/nós e versão exata do OneFS.
- Endereço de administração do cluster e TCP 8080 do coletor para o PowerScale.
- Conta dedicada com privilégios RBAC mínimos para todos os recursos `GET` usados.
- CA/certificado confiável e hostname correspondente.
- NTP consistente, especialmente para relatórios SyncIQ e séries históricas.
- Inventário de licenças: SyncIQ, SnapshotIQ, SmartLock, InsightIQ/recursos de performance etc.
- Definição do nível: cluster, nó, node pool, protocolo, quota, share/export.

## 4. Autenticação

Para poucas requisições independentes, o OneFS aceita HTTP Basic conforme o RBAC do usuário. Para várias requisições ao mesmo nó, pode-se usar sessão/cookie e proteção CSRF conforme a versão.

Validação inicial somente leitura:

```bash
export ONEFS_HOST='powerscale-gerencia.exemplo'
export ONEFS_CA_FILE='/etc/pki/ca-trust/source/anchors/onefs-ca.pem'
export ONEFS_USER='usuario_monitor'
read -r -s -p 'Senha OneFS: ' ONEFS_PASS
```

```bash
curl --fail-with-body --silent --show-error \
  --cacert "$ONEFS_CA_FILE" \
  --user "$ONEFS_USER:$ONEFS_PASS" \
  --header 'Accept: application/json' \
  "https://$ONEFS_HOST:8080/platform/latest" \
  --output onefs_platform_latest.json
```

As credenciais na linha de comando são aceitáveis apenas para teste protegido. A implementação deve usar o armazenamento de segredos aprovado. Para sessão, seguir o `Session resource` da release, guardar cookie e token CSRF em memória e encerrar a sessão; não copiar URI/payload de versão diferente.

## 5. Descoberta antes da coleta

### Versão da API

Consultar `/platform/latest` e registrar a versão da API utilizável. Definir a variável documental `ONEFS_API` com esse número; ela não é uma macro Zabbix.

### Autodocumentação

Para qualquer recurso, acrescentar `?describe`:

```bash
curl --fail-with-body --silent --show-error \
  --cacert "$ONEFS_CA_FILE" \
  --user "$ONEFS_USER:$ONEFS_PASS" \
  "https://$ONEFS_HOST:8080/platform/ONEFS_API/cluster/statfs?describe" \
  --output onefs_statfs_schema.json
```

O resultado informa argumentos, métodos e estrutura JSON. Repetir para todos os recursos usados e guardar os arquivos como parte do contrato.

### Identidade do cluster e dos nós

```http
GET /platform/ONEFS_API/cluster/config
GET /platform/ONEFS_API/cluster/nodes
```

Seguir os IDs/LNNs devolvidos e nunca presumir que posição do array seja o número do nó.

## 6. Recursos mínimos

### Capacidade do filesystem

```http
GET /platform/ONEFS_API/cluster/statfs
```

Usar `?describe` para localizar os campos de total, usado/disponível e unidade da versão. Guardar a resposta bruta. Se node pools entrarem no escopo, descobrir o recurso de storage pools da mesma versão e não somar total de cluster com total de pools como se fossem grandezas independentes.

### Estatísticas correntes

```http
GET /platform/ONEFS_API/statistics/keys
GET /platform/ONEFS_API/statistics/keys/CHAVE
GET /platform/ONEFS_API/statistics/current
```

O catálogo `statistics/keys` é obrigatório. Ele descreve as chaves disponíveis; a consulta `current?describe` mostra os filtros aceitos. Construir a requisição somente depois de verificar o parâmetro correto na versão.

Selecionar no catálogo chaves para:

- CPU agregada e por nó;
- memória, se operacionalmente necessária;
- IOPS/operações;
- bytes/s de disco e rede;
- latência/tempo de resposta;
- protocolos SMB, NFS, S3/HDFS quando aplicáveis;
- erros e filas;
- saúde/carga de drives e nós.

Não coletar todas as keys a cada minuto. Fazer uma lista mínima e medir tamanho/tempo da resposta.

### Eventos ativos

```http
GET /platform/ONEFS_API/event/eventgroup-occurrences
```

Esse recurso lista ocorrências de grupos de eventos. Localizar pelo `?describe` filtros para estado/severidade e campos de ID, mensagem, início, último evento e resolução. Preservar o ID do grupo para correlação.

### SyncIQ

```http
GET /platform/ONEFS_API/sync/policies
GET /platform/ONEFS_API/sync/reports
GET /platform/ONEFS_API/sync/target/reports
```

Descobrir políticas e relatórios separadamente. Uma policy configurada não prova que o último job foi bem-sucedido. Para cada política, localizar:

- ID e nome;
- enabled/disabled;
- origem/destino;
- último início/fim;
- resultado/estado;
- bytes/arquivos transferidos, quando disponível;
- duração;
- erro e último sucesso;
- próxima execução, se exposta.

### Snapshots e demais proteções

Avaliar, conforme licença e uso:

- snapshot summary/snapshots/schedules;
- HealthCheck evaluations;
- jobs/reports de manutenção;
- SmartLock domains/settings;
- antivírus/ICAP;
- configuração de auditoria.

Itens não licenciados/configurados devem ser marcados como `não aplicável`.

## 7. Mapeamento funcional

| Critério | Métrica | Recurso | Extração |
|---|---|---|---|
| Disponibilidade | Cluster/versão | `cluster/config`, versão | ID, nome, versão e estado documentado. |
| Disponibilidade | Nós | `cluster/nodes` | Descobrir por LNN/ID; manter modelo, estado e saúde por nó. |
| Disponibilidade | Eventos ativos | `event/eventgroup-occurrences` | ID estável, severidade, mensagem, timestamps e resolução. |
| Disponibilidade | HealthCheck/jobs | recursos `healthcheck`/`job` | Somente avaliações/jobs habilitados; separar running de failed. |
| Capacidade | Filesystem | `cluster/statfs` | Total/usado/livre conforme schema da versão. |
| Capacidade | Node pools/quotas | recursos específicos | Alta cardinalidade; incluir somente com requisito e ID estável. |
| Performance | CPU/IOPS/latência/bandwidth | `statistics/keys` + `statistics/current` | Selecionar keys documentadas e guardar nó/protocolo/escopo. |
| Proteção | SyncIQ | `sync/policies`, `sync/reports`, target reports | Correlacionar policy/report pelo ID; calcular idade do último sucesso. |
| Proteção | Snapshots | snapshot summary/schedules | Total, falhas e idade; não descobrir snapshots individuais sem necessidade. |
| Segurança | Versão/TLS | config + handshake | Versão diária; certificado e cadeia. |
| Segurança | Auditoria/SmartLock/AV | recursos da versão | Apenas se configurados e aprovados; preservar eventos sem conteúdo de arquivo. |

## 8. Extração JSON

Cada resposta deve ser inspecionada sem depender de formatação visual:

```bash
python3 -m json.tool onefs_platform_latest.json > onefs_platform_latest_pretty.json
```

O caminho final entregue à equipe deve nascer da amostra real, por exemplo:

```text
coleção[] -> objeto -> campo
```

Não escrever previamente `nodes[0]`. O índice `0` é posição transitória. A descoberta deve iterar todos os objetos e usar LNN/ID fornecido pelo OneFS.

Para paginação:

1. identificar no `?describe` os parâmetros e o indicador de continuação;
2. salvar o token/cursor ou próxima URI;
3. consultar até o fim;
4. deduplicar por ID;
5. detectar loop de cursor;
6. limitar páginas para proteger o cluster.

## 9. Frequência inicial

| Coleta | Frequência |
|---|---:|
| Acesso/cluster/eventos críticos | 1 a 2 minutos |
| Nós e saúde | 2 a 5 minutos |
| Estatísticas agregadas | 1 a 5 minutos |
| Capacidade | 15 minutos |
| SyncIQ em execução/falha | 5 minutos |
| Inventário/policies/versão | 12 a 24 horas |

## 10. Tratamento de falhas

- HTTP `401`: credencial/sessão; `403`: privilégio; não tratar como cluster down.
- `404`: recurso/versão incompatível ou licença ausente; conferir `/platform/latest` e `?describe`.
- HTTP `200` com coleção vazia pode ser legítimo.
- Timestamp antigo é telemetria atrasada, diferente de timeout.
- Um nó ausente da resposta exige nova descoberta antes de declarar removido.
- Estatística `0` é válida; key inexistente não deve virar zero.
- Se a sessão estiver presa a um nó, falha desse nó exige reautenticação no endereço recomendado, não reutilização infinita do cookie.

## 11. Evidências obrigatórias

- modelo, versão OneFS, nós/LNNs e licenças.
- resposta `/platform/latest`.
- `?describe` de cada recurso usado.
- JSON saudável/degradado/vazio para cluster, nodes e eventos.
- catálogo das statistics keys selecionadas e unidade/descrição.
- respostas SyncIQ de policy e report, se aplicável.
- tempos, tamanhos e paginação.
- comparação com a WebUI/CLI no mesmo instante.
- mapa de privilégios RBAC efetivamente necessários.

## 12. Testes de aceitação

- [ ] API é acessada em 8080 com TLS validado.
- [ ] Versão é descoberta e não fixada cegamente em `14`.
- [ ] `?describe` foi salvo para todos os recursos.
- [ ] Capacidade confere com o cluster.
- [ ] Uma key de performance confere com a interface oficial.
- [ ] Um evento ativo e sua resolução são correlacionados pelo mesmo ID.
- [ ] SyncIQ disabled é distinguido de job failed.
- [ ] Coleção vazia e timeout produzem resultados diferentes.
- [ ] Conta não possui privilégios de alteração.

## 13. Referências oficiais

- [Dell PowerScale — OneFS API Reference](https://www.dell.com/support/manuals/en-us/isilon-onefs/ifs_pub_onefs_api_reference/introduction-to-this-guide)
- [OneFS — arquitetura e autenticação](https://www.dell.com/support/manuals/en-us/isilon-onefs/ifs_pub_onefs_api_reference/onefs-api-architecture?guid=guid-db3f58e3-a564-4a3e-a55e-cba17dcbc271&lang=en-us)
- [OneFS — autodocumentação com `?describe`](https://www.dell.com/support/manuals/en-us/isilon-onefs/ifs_pub_onefs_api_reference/onefs-api-self-documentation?guid=guid-6a26bde5-592a-4064-9a12-4dde61526207&lang=en-us)
- [OneFS — estatísticas correntes](https://www.dell.com/support/manuals/en-us/isilon-onefs/ifs_pub_onefs_api_reference/statistics-current-resource?guid=guid-fb7c7796-3e27-45f1-8e0f-1f448555fb77&lang=en-us)
- [OneFS — capacidade do filesystem](https://www.dell.com/support/manuals/en-us/isilon-onefs/ifs_pub_onefs_api_reference/cluster-file-system-statistics-resource?guid=guid-404fe6e9-577a-4fde-9c0d-b707a7d28d15&lang=en-us)
- [OneFS — relatórios SyncIQ](https://www.dell.com/support/manuals/en-us/isilon-onefs/ifs_pub_onefs_api_reference/sync-reports-resource?guid=guid-4e959033-42f8-41a3-b856-79941397d7b7&lang=en-us)

