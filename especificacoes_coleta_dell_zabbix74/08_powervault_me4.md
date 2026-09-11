# PowerVault ME4 — especificação de coleta

## 1. Decisão

**Mínimo recomendado:** HTTPS CLI API do ME4 com resposta JSON, usando conta `monitor`, mais traps SNMP para eventos.  
**Importante:** esta interface é uma API de comandos CLI sobre HTTPS. Embora use URLs e JSON, não é uma REST API genérica de recursos.

A API oferece saída estruturada para saúde, configuração, pools, estatísticas, eventos e replicação. Ela é preferível a automatizar sessão SSH/console e parsear colunas.

## 2. Escopo mínimo

| Critério | Entrega mínima |
|---|---|
| Disponibilidade | Sistema, controladores, redundância, discos, enclosures, FRUs, portas, sensores, fontes/fans e eventos. |
| Capacidade | Pools, disk groups, tiers e volumes: total, livre, usado/alocado e overcommit quando aplicável. |
| Performance | CPU/cache dos controladores, IOPS, bytes/s, host ports, pools, volumes e discos conforme necessidade. |
| Proteção | RAID/disk groups, reconstrução, snapshots e replication sets quando configurados. |
| Segurança observável | Firmware, FDE, protocolos de gestão, certificado e SupportAssist quando expostos. |

## 3. Pré-requisitos

- Modelo ME4012/ME4024/ME4084 e firmware exato.
- Endereços dos dois controladores de gerenciamento.
- TCP 443 do coletor para ambos os controladores.
- Conta exclusiva com role `monitor`.
- CA/certificado confiável.
- NTP consistente.
- Configuração real: pools virtuais ou lineares, tiers, FC/iSCSI/SAS, replication sets, snapshots e FDE.
- SNMP trap receiver, se eventos assíncronos fizerem parte do mínimo.

## 4. Autenticação HTTPS

O método recomendado pela Dell para script calcula:

```text
hash = SHA256_hex(username + "_" + password)
```

E executa:

```http
GET https://ME4_CONTROLLER/api/login/HASH
datatype: json
```

A resposta JSON contém uma coleção `status`; o valor `status[0].response` é a session key. A chave tem timeout por inatividade e deve ser renovada após expirar.

Exemplo de geração do hash com Python nativo, mantendo o segredo apenas no processo de teste:

```bash
export ME4_USER='usuario_monitor'
read -r -s -p 'Senha ME4: ' ME4_PASS
ME4_HASH="$(ME4_USER="$ME4_USER" ME4_PASS="$ME4_PASS" python3 -c 'import hashlib, os; print(hashlib.sha256((os.environ["ME4_USER"] + "_" + os.environ["ME4_PASS"]).encode()).hexdigest())')"
```

Login:

```bash
export ME4_HOST='controladora-a.exemplo'
export ME4_CA_FILE='/etc/pki/ca-trust/source/anchors/me4-ca.pem'

curl --fail-with-body --silent --show-error \
  --cacert "$ME4_CA_FILE" \
  --header 'datatype: json' \
  "https://$ME4_HOST/api/login/$ME4_HASH" \
  --output me4_login.json
```

Extrair a session key sem biblioteca externa:

```bash
ME4_SESSION="$(python3 -c 'import json; print(json.load(open("me4_login.json", encoding="utf-8"))["status"][0]["response"])')"
test -n "$ME4_SESSION"
```

Não salvar `ME4_HASH`, `ME4_PASS`, login JSON ou session key nas evidências. Na implementação, preferir mecanismo de segredo e manter a chave somente em memória.

O ME4 também documenta Basic Authentication para `/api/login`; o método SHA256/session key é a preferência inicial. Ele não substitui TLS: hash na URL não torna aceitável desabilitar validação do certificado.

## 5. Executar comandos de leitura

Padrão:

```bash
curl --fail-with-body --silent --show-error \
  --cacert "$ME4_CA_FILE" \
  --header "sessionKey: $ME4_SESSION" \
  --header 'datatype: json' \
  "https://$ME4_HOST/api/show/system" \
  --output me4_show_system.json
```

O guia mostra que o ME4 converte comandos em caminhos sob `/api/`. Confirmar cada comando no CLI Guide da versão.

### Chamadas mínimas

| Finalidade | Comando CLI | URI de leitura a validar |
|---|---|---|
| Saúde consolidada | `show system` | `/api/show/system` |
| Inventário completo | `show configuration` | `/api/show/configuration` |
| Versão | `show versions` | `/api/show/versions` |
| Controladores | `show controllers` | `/api/show/controllers` |
| Redundância | `show redundancy-mode` | `/api/show/redundancy-mode` |
| Pools | `show pools` | `/api/show/pools` |
| Pool performance | `show pool-statistics` | `/api/show/pool-statistics` |
| Controlador performance | `show controller-statistics` | `/api/show/controller-statistics` |
| Portas de host | `show host-port-statistics` | `/api/show/host-port-statistics` |
| Discos | `show disks` | `/api/show/disks` |
| Disk groups | `show disk-groups` | `/api/show/disk-groups` |
| Sensores | `show sensor-status` | `/api/show/sensor-status` |
| Eventos | `show events` | `/api/show/events` |
| Replicação | `show replication-sets` | `/api/show/replication-sets` |
| Snapshots | `show snapshots`, `show snapshot-space` | caminhos equivalentes validados |
| FDE | `show fde-state` | `/api/show/fde-state` |
| SupportAssist | `show support-assist` | `/api/show/support-assist` |

Para comandos com parâmetros, cada token costuma compor o caminho. Não presumir a codificação: gerar a URI conforme a seção `Using a script to access the CLI` da release e testar somente leitura.

## 6. Como interpretar o JSON

A saída é organizada por **basetypes**, cada um normalmente em um array. Exemplo conceitual:

```json
{
  "system": [
    {
      "object-name": "system-information",
      "health": "OK"
    }
  ],
  "status": [
    {
      "response-type": "Success",
      "response-type-numeric": 0,
      "return-code": 0
    }
  ]
}
```

Regras obrigatórias:

1. Validar HTTP e depois `status[0]`.
2. Considerar sucesso somente quando o status da API indica comando concluído.
3. Iterar todos os elementos do basetype.
4. Usar `durable-id` quando fornecido; em alguns basetypes, usar `object-name` como indicado pelo guia.
5. Preferir propriedades `*-numeric` para cálculo, mas aplicar a unidade documentada.
6. Guardar texto/enumeração original de health/status.
7. Não interpretar array vazio como zero sem conferir inventário.

## 7. Mapeamento funcional

| Critério | Métrica | Comando/basetype | Extração |
|---|---|---|---|
| Disponibilidade | Saúde global | `show system` / `system[]` | `health` e motivo/health recommendation quando disponível. |
| Disponibilidade | Controladores | `show controllers` | ID A/B, health, status, papel e cache. |
| Disponibilidade | Redundância | `show redundancy-mode` / `redundancy[]` | Diferenciar redundant, failed over, down e single controller esperado. |
| Disponibilidade | Discos/enclosures/FRUs | `show configuration`, comandos específicos | Descobrir por durable ID/localização; preservar health. |
| Disponibilidade | Eventos | `show events` / events | ID A/B, código, severidade, timestamp, mensagem e resolved. |
| Capacidade | Pool | `show pools` / `pools[]` | `total-size-numeric` é em blocos; usar tamanho do bloco da resposta/documentação. Localizar disponível/usado/alocado. |
| Capacidade | Disk group/tier/volume | comandos específicos | Manter escopos separados; não somar volume provisionado com uso físico. |
| Performance | Controlador | `show controller-statistics` | `cpu-load`, `write-cache-used`, `bytes-per-second-numeric`, `iops`. |
| Performance | Port/pool/volume/disk | respectivos `*-statistics` | Usar valores por intervalo e campos numéricos; conferir sample times. |
| Proteção | RAID/disk group | `show disk-groups` | RAID, health, job/reconstruction e discos/spares. |
| Proteção | Replicação | `show replication-sets` | ID, status, `last-run-status`, `last-success-time`, progresso/queue se expostos. |
| Proteção | Snapshots | snapshot commands | Uso de snapshot space, schedules e falhas; não descobrir cada snapshot sem necessidade. |
| Segurança | FDE | `show fde-state`, disks | Estado do sistema e disco; não coletar passphrase/chave. |
| Segurança | Versão/protocolos | versions/protocols | Firmware diário e protocolos habilitados documentados. |
| Segurança | Certificado/SupportAssist | TLS + show support-assist | Validade e estado de conectividade; não expor detalhes sensíveis. |

### Capacidade em blocos

Alguns campos numéricos são apresentados em blocos, não bytes. O contrato deve registrar o tamanho do bloco/sector usado pela propriedade. Preferir um campo nativo em bytes se a versão oferecer; caso contrário:

```text
bytes = blocos * bytes_por_bloco
```

Não assumir 512 bytes sem confirmar no basetype/guia e na configuração do pool.

### Estatísticas por intervalo

O ME4 informa `start-sample-time` e `stop-sample-time` em basetypes de estatística. IOPS/bytes/s podem representar o intervalo desde a última solicitação ou reset. Por isso:

- manter cadência consistente;
- consultar as duas controladoras conforme orientação da Dell;
- não executar comandos `reset-*-statistics` pela monitoração;
- descartar valores cuja janela não seja válida;
- registrar restart/power-on time para explicar resets.

## 8. Controladoras A e B

Testar os dois IPs separadamente. Definir qual endereço será principal e como ocorrerá retry:

1. consultar A;
2. em falha de conexão, consultar B;
3. não ocultar que A falhou apenas porque B respondeu;
4. descartar session key vinculada à sessão/controladora quando inválida;
5. não duplicar a mesma lista de objetos ao unir respostas.

Estado `Single Controller` só é saudável em um modelo/configuração planejada como single-controller. Em dual-controller, `Operational but not redundant` ou `Failed Over` exige atenção.

## 9. SNMP traps

Usar traps para eventos de hardware, controladora, disco, porta, capacidade e replicação disponíveis. Capturar uma trap de teste e mapear pelo MIB da versão. O polling de `show events` deve reconciliar eventos ativos/resolvidos.

## 10. Frequência inicial

| Coleta | Frequência |
|---|---:|
| Saúde/sistema/redundância | 1 a 2 minutos |
| Componentes/sensores/eventos | 3 a 5 minutos |
| Estatísticas agregadas | 1 a 5 minutos |
| Pools/capacidade | 10 a 15 minutos |
| Replicação/jobs | 5 minutos |
| Inventário/versão/FDE | 12 a 24 horas |
| Traps | contínuo |

## 11. Tratamento de falhas

- HTTP `200` com `return-code` diferente de zero é falha da chamada.
- Sessão expirada exige novo login uma vez; não loop infinito.
- Resposta HTML no lugar de JSON deve falhar por content type/schema.
- Controladora A indisponível e B saudável são dois fatos, não um único OK.
- Campo `N/A`/ausente não é zero.
- Evento `RESOLVED` não permanece como problema ativo.
- Objeto removido requer redescoberta por durable ID.
- Firmware upgrade exige nova captura de basetypes.

## 12. Evidências obrigatórias

- modelo/firmware, controladoras e configuração single/dual.
- login sanitizado apenas com status, sem session key.
- JSON de todos os comandos mínimos.
- basetype/propriedades usados, unidades e enumerações.
- pool virtual e/ou linear real com conversão de capacidade validada.
- duas amostras de estatística e sample times.
- replication set saudável/degradado, se configurado.
- evento/trap de teste.
- comparação simultânea com PowerVault Manager.

## 13. Testes de aceitação

- [ ] Conta `monitor` executa todos os comandos e nenhum comando de alteração.
- [ ] TLS é validado.
- [ ] Session key expira e é renovada de forma controlada.
- [ ] `status/return-code` é validado antes dos dados.
- [ ] A e B são testadas sem duplicar objetos.
- [ ] Capacidade em blocos foi convertida com base comprovada.
- [ ] IOPS/bytes/s têm janela válida.
- [ ] Evento resolvido é correlacionado.
- [ ] Replicação ausente é não aplicável.

## 14. Referências oficiais

- [Dell PowerVault ME4 — usar script para acessar a CLI API](https://www.dell.com/support/manuals/en-us/powervault-me4024/me4_series_cli_pub/using-a-script-to-access-the-cli?guid=guid-9ae5ccd6-a207-42df-b2f3-1e02a487a354&lang=en-us)
- [Dell PowerVault ME4 — saída JSON](https://www.dell.com/support/manuals/en-us/powervault-me4024/me4_series_cli_pub/using-json-api-output?guid=guid-747cd3fc-073f-466d-9059-8f2df28b1768&lang=en-us)
- [Dell PowerVault ME4 — `show configuration`](https://www.dell.com/support/manuals/en-us/powervault-me4024/me4_series_cli_pub/show-configuration?guid=guid-0186b4a6-089c-4529-a6b4-07e0de8aec97&lang=en-us)
- [Dell PowerVault ME4 — controller statistics](https://www.dell.com/support/manuals/en-us/powervault-me4012/me4_series_cli_pub/controller-statistics?guid=guid-c2ce52aa-4598-4f97-9d9a-1f7f3d3ab9b3&lang=en-us)
- [Dell PowerVault ME4 — redundancy mode](https://www.dell.com/support/manuals/en-us/powervault-me4012/me4_series_cli_pub/show-redundancy-mode?guid=guid-a61254f3-07eb-4f20-9281-90999a10af12&lang=en-us)
- [Dell PowerVault ME4 — events](https://www.dell.com/support/manuals/en-us/powervault-me4024/me4_series_cli_pub/show-events?guid=guid-9179f911-1376-4d04-bb13-4ff02101d79b&lang=en-us)
