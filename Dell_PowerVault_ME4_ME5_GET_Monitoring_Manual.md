# Dell PowerVault ME4/ME5 - Manual de monitoramento com cURL e GET

**Edição:** 2026-09-02  
**Escopo:** saúde, capacidade, performance, proteção, conectividade e segurança  
**Regra:** somente requisições HTTP GET e, na API nativa, somente o verbo CLI `show`.

> **Barreira de segurança importante:** na API nativa PowerVault ME, o método HTTP é o transporte do comando CLI. Portanto, GET por si só não garante leitura. Este guia usa uma allowlist fechada de `show` e nunca aceita uma URL arbitrária.

## 1. Modelo de API e compatibilidade

ME4 e ME5 expõem a API nativa da CLI por HTTPS. Espaços do comando são convertidos em `/`; por exemplo, `show system` vira `/api/show/system`. A resposta JSON contém objetos de dados e uma coleção `status`; considere a coleta válida somente quando o HTTP for bem-sucedido e `status[0].return-code` for zero.

O ME5 também oferece Redfish/Swordfish. O catálogo principal deste manual usa a API nativa porque ela é a interseção operacional entre ME4 e ME5. A disponibilidade de cada `show` depende de modelo, protocolo e firmware; valide o catálogo com o CLI Guide correspondente ao equipamento.

## 2. Variáveis, TLS e login GET

```bash
export ME_URL='https://me-a.exemplo.local'
export ME_USER='monitor'
export ME_CA='/etc/pki/ca-trust/source/anchors/powervault-ca.pem'

LOGIN_JSON=$(curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --user "$ME_USER" \
  --header 'datatype: json' \
  "$ME_URL/api/login")
SESSION_KEY=$(jq -er '.status[0].response' <<<"$LOGIN_JSON")
jq -e '.status[0]["return-code"] == 0' <<<"$LOGIN_JSON" >/dev/null
```

A opção `--user "$ME_USER"` permite que o cURL solicite a senha sem gravá-la no histórico. Para automação, prefira um arquivo netrc protegido ou um cofre de segredos. Use `--cacert`; aceite certificado não validado apenas em laboratório isolado.

## 3. Validação padrão da resposta

```bash
PAYLOAD=$(curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/system")
jq -e '.status[0]["return-code"] == 0 and .status[0]["response-type"] == "Success"' <<<"$PAYLOAD" >/dev/null
```

Nunca confie apenas no código HTTP. Registre o comando, tempo de resposta e `status`, mas não registre senha nem session key. A sessão expira por inatividade; renove-a e repita uma única vez quando a API indicar sessão inválida.

## 4. Estratégia de monitoramento

- Consulte os dois IPs de gerenciamento para distinguir falha do array de falha de um controlador/caminho.
- Use master items por domínio e dependent items no Zabbix para reduzir sessões e carga.
- Calcule deltas para contadores cumulativos e descarte deltas negativos após reboot ou reset.
- Faça baseline de latência e throughput; picos isolados não bastam para classificar incidente.
- Para capacidade, combine percentual, bytes livres e previsão de esgotamento.
- Trate `Unsupported`, coleção ausente ou campo ausente como diferença de firmware, não como saúde OK.

## Fundamentos e inventário

### 1. `show system`

**Objetivo:** Estado global, identidade, saúde e capacidade resumida.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 1 min  
**Observar:** saúde global, modelo, serial, nomes e capacidade  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/system" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 2. `show versions`

**Objetivo:** Versões de firmware, CPLD e componentes.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 6 h  
**Observar:** versões divergentes e mudança após manutenção  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/versions" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 3. `show controllers`

**Objetivo:** Estado, papel, redundância e inventário dos controladores.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 1 min  
**Observar:** health, status, posição, serial e firmware  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/controllers" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 4. `show enclosures`

**Objetivo:** Inventário e saúde de chassis e gavetas.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 2 min  
**Observar:** health, posição, modelo, serial e componentes  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/enclosures" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 5. `show redundancy-mode`

**Objetivo:** Modo de redundância e estado operacional.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 1 min  
**Observar:** perda de redundância ou modo inesperado  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/redundancy-mode" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 6. `show service-tag-info`

**Objetivo:** Service Tag e identidade de suporte.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 24 h  
**Observar:** mudança de identidade  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/service-tag-info" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 7. `show license`

**Objetivo:** Licenças e recursos habilitados.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 12 h  
**Observar:** recurso ausente ou alteração  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/license" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 8. `show configuration`

**Objetivo:** Resumo de configuração para inventário e auditoria.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 6 h  
**Observar:** deriva de configuração  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/configuration" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 9. `show controller-date`

**Objetivo:** Relógio e fuso dos controladores.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 5 min  
**Observar:** desvio de horário  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/controller-date" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 10. `show cli-parameters`

**Objetivo:** Parâmetros da sessão e unidades de apresentação.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 12 h  
**Observar:** timeout, locale e unidades  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/cli-parameters" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

## Saúde e componentes

### 11. `show sensor-status`

**Objetivo:** Sensores térmicos, tensão e condições ambientais.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 1 min  
**Observar:** status não nominal e temperatura  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/sensor-status" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 12. `show power-supplies`

**Objetivo:** Fontes e redundância elétrica.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 1 min  
**Observar:** health, status e posição  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/power-supplies" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 13. `show fan-modules`

**Objetivo:** Módulos de ventilação.

**Compatibilidade:** ME5/validar ME4  
**Cadência inicial:** 1 min  
**Observar:** health, posição e ausência  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/fan-modules" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 14. `show fans`

**Objetivo:** Ventiladores individuais quando expostos.

**Compatibilidade:** ME4/validar ME5  
**Cadência inicial:** 1 min  
**Observar:** health, velocidade e posição  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/fans" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 15. `show frus`

**Objetivo:** Field Replaceable Units e identidade de hardware.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 6 h  
**Observar:** health, part number, serial e revisão  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/frus" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 16. `show expander-status`

**Objetivo:** Estado dos expansores SAS.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 1 min  
**Observar:** health e caminhos degradados  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/expander-status" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 17. `show sas-link-health`

**Objetivo:** Saúde dos links SAS internos e de expansão.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 1 min  
**Observar:** erros e perda de caminho  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/sas-link-health" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 18. `show unwritable-cache`

**Objetivo:** Dados de cache que não puderam ser gravados.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 1 min  
**Observar:** qualquer objeto presente  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/unwritable-cache" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 19. `show shutdown-status`

**Objetivo:** Estado de desligamento ou preparação do sistema.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 1 min  
**Observar:** estado diferente do operacional  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/shutdown-status" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 20. `show events`

**Objetivo:** Eventos de falha, aviso e operação.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 1 min  
**Observar:** severidade, código, hora e componente  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/events" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

## Discos, grupos, pools e capacidade

### 21. `show disks`

**Objetivo:** Discos, posição, tipo, capacidade e saúde.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 2 min  
**Observar:** health, status, slot, uso e tamanho  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/disks" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 22. `show disk-groups`

**Objetivo:** Grupos de discos e RAID.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 2 min  
**Observar:** health, status, RAID, capacidade e owner  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/disk-groups" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 23. `show pools`

**Objetivo:** Pools, saúde, provisionamento e capacidade.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 2 min  
**Observar:** total, alocado, disponível e percentual  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/pools" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 24. `show volumes`

**Objetivo:** Volumes, saúde, tamanho e pool.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 5 min  
**Observar:** health, tamanho, alocação e owner  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/volumes" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 25. `show volume-groups`

**Objetivo:** Grupos de volumes.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 15 min  
**Observar:** membership e alterações  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/volume-groups" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 26. `show tiers`

**Objetivo:** Tiers e distribuição de capacidade.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 10 min  
**Observar:** health, total, alocado e disponível  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/tiers" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 27. `show snapshot-space`

**Objetivo:** Consumo reservado/real de snapshots.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 5 min  
**Observar:** uso, limite e crescimento  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/snapshot-space" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 28. `show snapshots`

**Objetivo:** Snapshots, idade, estado e volume pai.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 10 min  
**Observar:** status, idade e contagem  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/snapshots" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 29. `show provisioning`

**Objetivo:** Associações entre discos, grupos, pools, volumes e mappings.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 15 min  
**Observar:** deriva e objetos órfãos  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/provisioning" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 30. `show volume-names`

**Objetivo:** Relação de nomes de volumes.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 6 h  
**Observar:** mudança de nomenclatura  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/volume-names" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 31. `show volume-reservations`

**Objetivo:** Reservas de volumes.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 15 min  
**Observar:** reserva inesperada  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/volume-reservations" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 32. `show vdisks`

**Objetivo:** Visão legada de virtual disks em firmwares que a expõem.

**Compatibilidade:** legado/compatibilidade  
**Cadência inicial:** 10 min  
**Observar:** health, capacidade e owner  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/vdisks" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

## Performance e tendência

### 33. `show controller-statistics`

**Objetivo:** Carga e tráfego dos controladores.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 1 min  
**Observar:** CPU, operações e throughput  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/controller-statistics" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 34. `show disk-statistics`

**Objetivo:** I/O e erros por disco.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 1 min  
**Observar:** IOPS, bytes, latência e erros  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/disk-statistics" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 35. `show disk-group-statistics`

**Objetivo:** I/O agregado por disk group.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 1 min  
**Observar:** IOPS, throughput e latência  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/disk-group-statistics" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 36. `show pool-statistics`

**Objetivo:** I/O e atividade por pool.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 1 min  
**Observar:** IOPS, throughput e latência  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/pool-statistics" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 37. `show tier-statistics`

**Objetivo:** Atividade por tier.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 2 min  
**Observar:** IOPS, throughput e distribuição  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/tier-statistics" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 38. `show volume-statistics`

**Objetivo:** I/O por volume.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 1 min  
**Observar:** IOPS, throughput, latência e fila  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/volume-statistics" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 39. `show vdisk-statistics`

**Objetivo:** Estatísticas da visão vdisk legada.

**Compatibilidade:** legado/compatibilidade  
**Cadência inicial:** 2 min  
**Observar:** IOPS, throughput e latência  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/vdisk-statistics" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 40. `show host-port-statistics`

**Objetivo:** Tráfego e erros nas portas de host.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 1 min  
**Observar:** bytes, I/O, erros e link  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/host-port-statistics" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 41. `show host-phy-statistics`

**Objetivo:** Contadores PHY de host quando suportados.

**Compatibilidade:** depende do protocolo/firmware  
**Cadência inicial:** 1 min  
**Observar:** erros e resets  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/host-phy-statistics" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 42. `show refresh-counters`

**Objetivo:** Estado dos contadores atualizáveis, sem executar alteração.

**Compatibilidade:** depende do firmware  
**Cadência inicial:** 10 min  
**Observar:** escopo e disponibilidade  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/refresh-counters" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

## Conectividade e hosts

### 43. `show ports`

**Objetivo:** Portas FC, iSCSI ou SAS e seus links.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 1 min  
**Observar:** health, link, velocidade, protocolo e controller  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/ports" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 44. `show host-groups`

**Objetivo:** Grupos de hosts e membros.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 15 min  
**Observar:** membership e deriva  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/host-groups" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 45. `show initiators`

**Objetivo:** WWPNs/IQNs e associação a hosts.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 10 min  
**Observar:** iniciador novo, órfão ou alterado  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/initiators" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 46. `show maps`

**Objetivo:** Mapeamentos volume-host.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 15 min  
**Observar:** adição, remoção e LUN ID  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/maps" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 47. `show protocols`

**Objetivo:** Protocolos de gerenciamento e dados habilitados.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 30 min  
**Observar:** estado e protocolo inseguro  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/protocols" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 48. `show iscsi-parameters`

**Objetivo:** Parâmetros iSCSI globais.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 30 min  
**Observar:** autenticação, digest e sessões  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/iscsi-parameters" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 49. `show network-parameters`

**Objetivo:** Rede de gerenciamento IPv4.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 30 min  
**Observar:** IP, gateway, máscara e DHCP  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/network-parameters" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 50. `show ipv6-network-parameters`

**Objetivo:** Rede de gerenciamento IPv6.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 30 min  
**Observar:** endereços, gateway e autoconfiguração  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/ipv6-network-parameters" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 51. `show ipv6-addresses`

**Objetivo:** Endereços IPv6 ativos.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 30 min  
**Observar:** mudança ou endereço inesperado  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/ipv6-addresses" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 52. `show dns-parameters`

**Objetivo:** DNS configurado.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 30 min  
**Observar:** servidores e domínio  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/dns-parameters" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 53. `show dns-management-hostname`

**Objetivo:** Hostname de gerenciamento publicado em DNS.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 30 min  
**Observar:** mudança de nome  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/dns-management-hostname" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 54. `show ntp-status`

**Objetivo:** Sincronização NTP.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 5 min  
**Observar:** estado, servidor e offset  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/ntp-status" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 55. `show peer-connections`

**Objetivo:** Conexões entre sistemas/peers.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 1 min  
**Observar:** health, status e latência aparente  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/peer-connections" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 56. `show remote-systems`

**Objetivo:** Arrays remotos conhecidos.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 2 min  
**Observar:** health, status e identidade  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/remote-systems" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

## Proteção e replicação

### 57. `show replication-sets`

**Objetivo:** Pares e estado das replicações.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 1 min  
**Observar:** health, status, direção, progresso e atraso  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/replication-sets" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 58. `show replication-snapshot-history`

**Objetivo:** Histórico de snapshots de replicação.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 10 min  
**Observar:** última cópia, falha e retenção  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/replication-snapshot-history" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 59. `show schedules`

**Objetivo:** Agendamentos de snapshots e replicação.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 30 min  
**Observar:** enabled, próxima execução e deriva  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/schedules" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 60. `show volume-copies`

**Objetivo:** Cópias de volume em andamento ou concluídas.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 2 min  
**Observar:** status, progresso, origem e destino  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/volume-copies" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 61. `show tasks`

**Objetivo:** Tarefas agendadas ou em execução.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 2 min  
**Observar:** status, progresso, falha e duração  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/tasks" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 62. `show fenced-data`

**Objetivo:** Dados isolados por proteção de integridade.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 2 min  
**Observar:** qualquer entrada ou crescimento  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/fenced-data" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

## Segurança e auditoria

### 63. `show users`

**Objetivo:** Contas, papéis e interfaces permitidas; sem solicitar segredos.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 15 min  
**Observar:** conta nova, papel e estado  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/users" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 64. `show sessions`

**Objetivo:** Sessões administrativas ativas.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 5 min  
**Observar:** usuário, origem, tipo e duração  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/sessions" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 65. `show certificate`

**Objetivo:** Certificado de gerenciamento e validade, quando suportado.

**Compatibilidade:** depende do firmware  
**Cadência inicial:** 6 h  
**Observar:** issuer, subject e expiração  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/certificate" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 66. `show chap-records`

**Objetivo:** Registros CHAP sem solicitar segredo.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 30 min  
**Observar:** nome, associação e alteração  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/chap-records" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 67. `show fde-state`

**Objetivo:** Estado de Full Disk Encryption e chaves.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 2 min  
**Observar:** enabled, health e key status  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/fde-state" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 68. `show snmp-parameters`

**Objetivo:** Parâmetros SNMP e destinos.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 30 min  
**Observar:** versão, enablement e deriva  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/snmp-parameters" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 69. `show syslog-parameters`

**Objetivo:** Destinos de syslog.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 15 min  
**Observar:** destino, protocolo, porta e alteração  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/syslog-parameters" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 70. `show email-parameters`

**Objetivo:** Destinos de alerta por e-mail.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 30 min  
**Observar:** servidor, recipients e deriva  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/email-parameters" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 71. `show support-assist`

**Objetivo:** Estado do SupportAssist/CloudIQ quando exposto.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 5 min  
**Observar:** health, conexão e última atividade  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/support-assist" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 72. `show cloud-iq`

**Objetivo:** Integração CloudIQ em firmwares compatíveis.

**Compatibilidade:** depende do firmware  
**Cadência inicial:** 5 min  
**Observar:** enabled, health e última conexão  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/cloud-iq" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 73. `show advanced-settings`

**Objetivo:** Parâmetros avançados para auditoria de baseline.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 12 h  
**Observar:** qualquer alteração não planejada  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/advanced-settings" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 74. `show cache-parameters`

**Objetivo:** Políticas de cache para auditoria e risco.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 12 h  
**Observar:** write-back, auto-write-through e mudança  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/cache-parameters" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

### 75. `show disk-parameters`

**Objetivo:** Parâmetros globais de discos.

**Compatibilidade:** ME4 e ME5; validar firmware  
**Cadência inicial:** 12 h  
**Observar:** SMART, spin-down e deriva  
**Ação:** correlacionar com `show events`, redundância e mudança recente; escalar qualquer estado degradado, falho ou desconhecido persistente.

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --header "sessionKey: $SESSION_KEY" \
  --header 'datatype: json' \
  "$ME_URL/api/show/disk-parameters" | jq .
```

**Zabbix:** item mestre JSON; crie dependentes apenas para campos confirmados no seu firmware. Descoberta de baixo nível por identificador durável, slot ou nome; trigger por estado e `nodata()`.

## 5. Grupos prontos da biblioteca Bash

```bash
./powervault_me_get_curl_library.sh login
./powervault_me_get_curl_library.sh group health
./powervault_me_get_curl_library.sh group capacity
./powervault_me_get_curl_library.sh group performance
./powervault_me_get_curl_library.sh show sensor-status
./powervault_me_get_curl_library.sh catalog
```

A biblioteca rejeita comandos fora da allowlist e não oferece modo de URL livre. O arquivo da session key deve ter permissão 0600 e ser removido quando não for mais necessário.

## 6. ME5 Redfish/Swordfish - descoberta GET opcional

Use esta trilha apenas depois de confirmar que o serviço Redfish/Swordfish está habilitado no ME5. A raiz permite descobrir os recursos reais sem adivinhar URIs:

```bash
curl --silent --show-error --fail-with-body --request GET \
  --cacert "$ME_CA" \
  --user "$ME_USER" \
  "$ME_URL/redfish/v1/" | jq .
```

Siga somente links retornados pela service root e pelas coleções. Como schemas e membros variam por versão, não codifique IDs antes da descoberta. Para um pacote comum ME4/ME5, mantenha a API nativa `show` como fonte principal.

## 7. Checklist de produção

- Conta dedicada com papel de monitoramento e sem interfaces desnecessárias.
- CA confiável, hostname validado e segredo fora de argumentos persistentes.
- Allowlist local de comandos `show`; nenhuma entrada do usuário vira caminho sem validação.
- Validação do HTTP, `return-code`, `response-type`, schema e tempo de coleta.
- Timeout, retry com backoff e limite de concorrência por controlador.
- Baseline e testes após upgrade de firmware.
- Retenção externa dos eventos e proteção dos inventários exportados.

## 8. Fontes oficiais

- Dell Technologies Developer - PowerVault ME5 Series API, versão 1.0: https://developer.dell.com/apis/12038/versions/1.0/docs/Introduction.md
- Dell PowerVault ME5 Series Storage System CLI Guide - Using a script to access the CLI: https://www.dell.com/support/manuals/en-us/powervault-me5024/me5_series_cli/using-a-script-to-access-the-cli
- Dell PowerVault ME5 Series Storage System CLI Guide - Scripting guidelines: https://www.dell.com/support/manuals/en-us/powervault-me5012/me5_series_cli/scripting-guidelines
- Dell PowerVault ME4 Series Storage System CLI Guide - Using a script to access the CLI: https://www.dell.com/support/manuals/en-us/powervault-me4024/me4_series_cli_pub/using-a-script-to-access-the-cli
- Dell PowerVault ME4 Series Storage System CLI Guide - Scripting guidelines: https://www.dell.com/support/manuals/en-us/powervault-me4012/me4_series_cli_pub/scripting-guidelines
- Seagate SystemsRedfishPy - tutorial Redfish/Swordfish referenciado pelo portal Dell para ME5: https://github.com/Seagate/SystemsRedfishPy/blob/master/tutorial-redfish-service-v1.md
