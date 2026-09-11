# ECS — especificação de coleta

## 1. Decisão

**Mínimo recomendado:** combinação de Flux API para séries temporais, ECS Management REST API para inventário/estado e traps SNMPv3 para eventos.  
**Não recomendado como fonte única:** SNMP polling, pois a documentação do ECS concentra métricas detalhadas de capacidade e performance no sistema de monitoração/Flux, enquanto SNMP também cumpre papel importante de notificação.

ECS é a família mais trabalhosa deste pacote. A lista de measurements, buckets e campos mudou entre releases; por isso a documentação e a resposta da versão instalada precisam acompanhar o mapeamento.

## 2. Escopo mínimo

| Critério | Entrega mínima |
|---|---|
| Disponibilidade | VDC, nós, storage pools, processos essenciais, discos e alertas ativos. |
| Capacidade | Total/usado/livre por VDC e storage pool; namespace/bucket somente se aprovado e necessário. |
| Performance | Transações/s, latência, largura de banda, erros, CPU, memória, rede e disco em nível VDC; nó só para diagnóstico. |
| Proteção | Estado de replication groups, geo-replicação, recovery/rebalance e dados pendentes/em risco quando expostos. |
| Segurança observável | Versão, validade TLS, sessões/auditoria e eventos de segurança expostos ao perfil de monitoração. |

## 3. Pré-requisitos

- Versão exata do ECS e documentação dessa release.
- Topologia: VDCs, sites, nós, storage pools e replication groups.
- FQDN/IP de gerência ou balanceador aprovado.
- TCP 4443 do coletor para o ECS Management/Flux API.
- Conta dedicada com papel de leitura. O papel `System Monitor` é a primeira opção a testar por fornecer acesso de visualização sem permissão de provisionamento.
- Certificado/CA confiável.
- UDP 162 do ECS para o receptor de traps SNMPv3.
- NTP consistente entre VDCs e coletor.
- Autorização para expor nomes de namespace/bucket; eles podem conter informação sensível.

## 4. Autenticação da Management REST API

O login é feito em HTTPS na porta 4443 e retorna `X-SDS-AUTH-TOKEN`. Requisições seguintes enviam esse token no header.

Exemplo de homologação:

```bash
export ECS_HOST='ecs-gerencia.exemplo'
export ECS_CA_FILE='/etc/pki/ca-trust/source/anchors/ecs-ca.pem'
export ECS_USER='usuario_monitor'
```

Solicitar a senha de forma interativa e não gravá-la no arquivo:

```bash
read -r -s -p 'Senha ECS: ' ECS_PASS
```

Efetuar login salvando apenas headers em arquivo temporário protegido:

```bash
umask 077
curl --fail-with-body --silent --show-error \
  --cacert "$ECS_CA_FILE" \
  --user "$ECS_USER:$ECS_PASS" \
  --dump-header /tmp/ecs-login-headers.txt \
  --output /tmp/ecs-login-body.txt \
  "https://$ECS_HOST:4443/login"
```

Extrair o token sem imprimir no terminal:

```bash
ECS_TOKEN="$(awk 'tolower($1)=="x-sds-auth-token:" {gsub("\\r", "", $2); print $2}' /tmp/ecs-login-headers.txt)"
test -n "$ECS_TOKEN"
```

Em produção, a implementação deve usar o cofre/mecanismo de segredo da plataforma e apagar arquivos temporários. `401` ou redirecionamento de autenticação deve provocar renovação controlada do token, não repetição infinita de login.

## 5. Descobrir a API da versão

Obter o ECS REST API Reference correspondente à versão e registrar:

- URI e formato de inventário de VDC;
- URI de nós;
- URI de storage pools;
- URI de replication groups;
- URI de alertas/auditoria;
- recursos de metering/capacidade;
- paginação, filtros e privilégios.

A referência é gerada a partir da implementação do produto. Portanto, o pacote entregue à equipe Zabbix deve incluir a versão/Swagger ou um PDF/exportação da referência usada.

Para cada coleção, fazer uma chamada de leitura, salvar resposta sanitizada e localizar:

- ID imutável;
- nome de exibição;
- VDC/site pai;
- estado/saúde;
- timestamp;
- próximo cursor/página;
- unidade dos campos numéricos.

Não fixar uma URI de ECS 3.5 em um ambiente 3.8 sem validar a referência instalada.

## 6. Flux API

### Endpoint

```http
POST https://ECS_HOST:4443/flux/api/external/v2/query
X-SDS-AUTH-TOKEN: TOKEN
Content-Type: application/vnd.flux
Accept: application/csv
```

Exemplo de consulta de CPU não performática por nó, adaptando bucket/measurement à release:

```bash
curl --fail-with-body --silent --show-error \
  --cacert "$ECS_CA_FILE" \
  --request POST \
  --header "X-SDS-AUTH-TOKEN: $ECS_TOKEN" \
  --header 'Accept: application/csv' \
  --header 'Content-Type: application/vnd.flux' \
  --data 'from(bucket:"monitoring_op") |> range(start:-5m) |> filter(fn: (r) => r._measurement == "cpu")' \
  "https://$ECS_HOST:4443/flux/api/external/v2/query" \
  --output ecs_cpu.csv
```

Exemplo oficial de padrão para transações, cuja measurement precisa ser confirmada na release:

```bash
curl --fail-with-body --silent --show-error \
  --cacert "$ECS_CA_FILE" \
  --request POST \
  --header "X-SDS-AUTH-TOKEN: $ECS_TOKEN" \
  --header 'Accept: application/csv' \
  --header 'Content-Type: application/vnd.flux' \
  --data 'from(bucket:"monitoring_main") |> range(start:-5m) |> filter(fn: (r) => r._measurement == "statDataHead_performance_internal_transactions")' \
  "https://$ECS_HOST:4443/flux/api/external/v2/query" \
  --output ecs_transactions.csv
```

O endpoint usa `POST`, mas a consulta Flux acima é somente leitura.

### Buckets/documentação a avaliar

| Bucket documentado | Uso típico | Regra |
|---|---|---|
| `monitoring_main` | Performance bruta por nó/processo | Usar para diagnóstico ou agregar conscientemente. |
| `monitoring_vdc` | Métricas agregadas por VDC | Preferido para o mínimo operacional quando existir a métrica equivalente. |
| `monitoring_op` | Métricas não performáticas, incluindo sistema de nó | Consultar lista da release. |
| `monitoring_last` | Valores/configuração mais recentes em casos documentados | Não assumir que toda métrica está aqui. |

### Como selecionar measurements

1. Abrir `Monitoring list of metrics: Performance` e `Non-Performance` da versão.
2. Marcar a measurement, field, tags, bucket e unidade.
3. Executar uma janela curta, por exemplo cinco minutos.
4. Comparar o resultado com o dashboard ECS no mesmo instante.
5. Identificar cardinalidade por tags: VDC, host, node ID, namespace, protocol, method etc.
6. Definir se a equipe precisa de agregado VDC ou detalhe de nó.
7. Salvar consulta e resposta sanitizada.

Nunca extrair uma coluna CSV pela posição. Usar o nome do header, pois colunas/tags podem variar. Tratar linhas de metadados do formato Flux/CSV e timestamps em UTC.

## 7. Mapeamento funcional

| Critério | Métrica | Fonte preferida | Extração |
|---|---|---|---|
| Disponibilidade | VDC/storage pool/nó | Management API + Flux não performático | Descobrir IDs e estado; preservar valor original e timestamp. |
| Disponibilidade | Saúde de processos | Flux `monitoring_op`/lista da release | Agregar somente depois de manter nó e processo afetados. |
| Disponibilidade | Alertas | Management API + SNMP traps | Guardar ID, severidade, escopo, mensagem, criação e resolução. |
| Capacidade | Total/usado/livre | Métrica VDC/storage pool documentada | Preferir VDC/storage pool; confirmar unidade e política de reserved space. |
| Capacidade | Namespace/bucket | Metering API, se aprovado | Pode ter alta cardinalidade e dados sensíveis; não incluir automaticamente. |
| Performance | Operações/transações por segundo | Flux `monitoring_vdc` ou `monitoring_main` | Separar protocolo/método e erros; não somar médias. |
| Performance | Latência | Flux | Confirmar unidade e percentil/média; manter leitura e escrita separadas. |
| Performance | Bandwidth | Flux | Preservar bytes/s; separar read/write e VDC/nó. |
| Performance | CPU/memória/rede/disco | Flux não performático/performance | Nível VDC para visão, nó para diagnóstico. |
| Proteção | Replication group/geo | Management API + Flux | Estado, VDCs, pendência, recovery e rebalance quando documentados. |
| Proteção | Dados pendentes/recovery | Flux da release | Confirmar se é bytes, chunks ou objetos e se é gauge. |
| Segurança | Versão/certificado | API + TLS | Versão diária; certificado a cada 12–24 h. |
| Segurança | Auditoria/sessões/node lock | Management API/syslog | Somente eventos que o papel de monitoração pode ler; não expor usuários desnecessariamente. |

### Cardinalidade

O mínimo deve começar em VDC e storage pool. Descoberta por bucket, namespace, usuário, método e nó pode multiplicar os objetos. Só habilitar granularidade quando houver dono, ação e retenção definidos.

### Agregação

- Não somar percentuais ou médias entre nós.
- Para throughput e contagens compatíveis, somar séries da mesma janela e escopo.
- Para latência, usar agregado fornecido pelo ECS; não calcular média simples de médias com pesos desconhecidos.
- Para saúde, preservar o pior membro e sua identidade.

## 8. SNMPv3 e traps

Configurar o receptor em `Settings > Event Notification`. O ECS pode enviar traps do fabric para receptores cadastrados e possui ECS-MIB específica.

Capturar uma trap de teste e registrar:

- origem real, inclusive qual nó enviou;
- trap OID;
- VDC/nó/componente;
- ID do alerta;
- severidade;
- texto e timestamp;
- sinal de recuperação.

Como a origem pode ser um nó do fabric, firewall e correlação não devem aceitar apenas um endereço virtual sem testar o comportamento real.

## 9. Frequência inicial

| Coleta | Frequência |
|---|---:|
| Endpoint/login | sessão reutilizada; verificação a cada 1–2 minutos |
| Estado VDC/nós/processos | 2 a 5 minutos |
| Performance VDC | 1 a 5 minutos |
| Performance por nó | 5 minutos ou sob demanda |
| Capacidade | 15 minutos |
| Replication/recovery/rebalance | 5 minutos |
| Inventário/versão | 12 a 24 horas |
| Traps | contínuo |

Consultar janelas Flux com sobreposição pequena e deduplicar por timestamp/tags para não perder ponto na fronteira.

## 10. Tratamento de falhas

- `401` ou redirecionamento de login: renovar token uma vez e registrar falha se persistir.
- `403`: falta de privilégio, não indisponibilidade do ECS.
- `429`/limite: respeitar espera e reduzir consultas/cardinalidade.
- CSV vazio com resposta válida: pode não haver ponto na janela; ampliar janela antes de declarar falha.
- Measurement inexistente: incompatibilidade de versão, não valor zero.
- Ponto antigo: telemetria atrasada; comparar `_time` com relógio atual.
- Falha em um nó não deve apagar a série agregada do VDC nem esconder o nó afetado.
- Mudança de schema após upgrade deve bloquear parsing incorreto e preservar o payload para diagnóstico.

## 11. Evidências obrigatórias

- versão, VDCs, nós, storage pools e replication groups sanitizados.
- referência REST/Swagger da versão.
- lista de métricas Performance e Non-Performance da versão.
- consultas Flux e CSVs saudável/degradado/vazio.
- respostas da Management API para inventário, saúde, alertas e proteção.
- tabela de tags/cardinalidade e unidades.
- trap de teste decodificada.
- comparação com dashboards ECS no mesmo intervalo.
- tempo e tamanho de cada consulta.

## 12. Testes de aceitação

- [ ] Conta de leitura autentica sem permissão de provisionar.
- [ ] Token é renovado sem loop de login.
- [ ] TLS é validado sem `-k`.
- [ ] Flux retorna pontos com timestamp recente.
- [ ] Métricas VDC conferem com o dashboard.
- [ ] CSV é lido por nome de coluna, não posição.
- [ ] Coleção vazia é distinguida de erro.
- [ ] Trap de teste chega mesmo quando outro nó do fabric é a origem.
- [ ] Namespace/bucket não é coletado sem aprovação.

## 13. Referências oficiais

- [Dell ECS — autenticar na Management REST API](https://www.dell.com/support/manuals/en-us/ecs-appliance-/ecs_pub_data_access_guide_3_3_to_3_6/authenticate-with-the-ecs-management-rest-api?guid=guid-3e2a3f7a-53f1-488e-bed9-2642dee6e20c&lang=en-us)
- [Dell ECS — Flux API](https://www.dell.com/support/manuals/en-us/ecs-appliance-/ecs_p_adminguide_3_5_0_1/flux-api?guid=guid-48afcdc8-d89d-48b0-9b9d-7764bbc4d42b&lang=en-us)
- [Dell ECS — lista de métricas de performance](https://www.dell.com/support/manuals/en-us/ecs-appliance-/ecs_p_adminguide_3_5_0_1/monitoring-list-of-metrics-performance?guid=guid-261296f5-2e00-439a-9afe-a838db6672f4&lang=en-us)
- [Dell ECS — lista de métricas não performáticas](https://www.dell.com/support/manuals/en-us/ecs-appliance-/ecs_p_adminguide_3_5_0_1/monitoring-list-of-metrics-non-performance?guid=guid-3be973c3-9a3f-4cb1-b7b9-7003e77a0b49&lang=en-us)
- [Dell ECS — SNMP, queries e MIBs](https://www.dell.com/support/manuals/en-us/ecs-appliance-/ecs_p_adminguide_3_5_0_1/support-for-snmp-data-collection-queries-and-mibs-in-ecs?guid=guid-37a9f0d9-4eb6-4072-acf2-d2843b741df5&lang=en-us)

