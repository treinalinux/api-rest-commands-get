# PowerEdge / iDRAC — especificação de coleta

## 1. Decisão

**Mínimo recomendado:** iDRAC RESTful API com Redfish, usando descoberta por links `@odata.id`.  
**Complemento:** Redfish Telemetry quando modelo, geração e licença suportarem; SNMPv3 como fallback para iDRAC antigo ou notificações já padronizadas.

Redfish permite monitoração fora de banda, independente do sistema operacional do servidor. O template do hardware e o template do SO devem ser separados: CPU física saudável no iDRAC não substitui uso/processos/filesystem coletados no Linux ou Windows.

## 2. Escopo mínimo

| Critério | Entrega mínima |
|---|---|
| Disponibilidade | iDRAC, servidor, chassi, manager, PSU, fans, temperatura, memória, CPU, storage e logs de hardware. |
| Capacidade | Memória instalada, CPUs, discos e volumes locais; não representa capacidade de SAN/NAS. |
| Performance | Energia, temperatura, fan e métricas suportadas; CPU/I/O detalhados somente com Telemetry/licença ou agente de SO. |
| Proteção | RAID, controladores, virtual disks, physical disks, spare/predictive failure. Backup/replicação é não aplicável ao iDRAC. |
| Segurança observável | Firmware, certificado, estado de serviços/protocolos, logs de auditoria/segurança e Secure Boot/SPDM quando expostos. |

## 3. Pré-requisitos

- Modelo/generation PowerEdge e versão exata do firmware iDRAC.
- Edição/licença iDRAC; Telemetry em 14G+ pode exigir licença Datacenter.
- TCP 443 do coletor para cada iDRAC.
- Conta local ou diretório dedicada com privilégio mínimo `Login`/leitura.
- CA/certificado confiável.
- NTP e timezone corretos.
- Inventário do storage local: PERC, BOSS, HBA, discos/virtual disks.
- Definição se o servidor é standalone ou membro de chassis modular.

## 4. Descoberta Redfish

### ServiceRoot

```bash
export IDRAC_HOST='idrac-servidor.exemplo'
export IDRAC_CA_FILE='/etc/pki/ca-trust/source/anchors/idrac-ca.pem'
export IDRAC_USER='usuario_monitor'
read -r -s -p 'Senha iDRAC: ' IDRAC_PASS
```

```bash
curl --fail-with-body --silent --show-error \
  --cacert "$IDRAC_CA_FILE" \
  --user "$IDRAC_USER:$IDRAC_PASS" \
  --header 'Accept: application/json' \
  "https://$IDRAC_HOST/redfish/v1/" \
  --output idrac_service_root.json
```

No JSON, seguir os links de:

- `Systems.@odata.id`;
- `Chassis.@odata.id`;
- `Managers.@odata.id`;
- `SessionService.@odata.id`;
- `TelemetryService.@odata.id`, se presente;
- `UpdateService` e `AccountService` apenas para inventário de capacidade funcional, sem operações de alteração.

Não presumir IDs como `System.Embedded.1` ou `iDRAC.Embedded.1`. Eles são frequentes em iDRAC, mas o coletor deve descobrir os membros das coleções.

### Coleções

```bash
curl --fail-with-body --silent --show-error \
  --cacert "$IDRAC_CA_FILE" \
  --user "$IDRAC_USER:$IDRAC_PASS" \
  "https://$IDRAC_HOST/redfish/v1/Systems" \
  --output idrac_systems.json
```

Iterar `Members[].@odata.id`, repetir em `/redfish/v1/Chassis` e `/redfish/v1/Managers`, e então seguir os links existentes em cada membro.

## 5. Autenticação por sessão

Sessão é preferível quando HTTP Basic estiver desabilitado ou quando várias chamadas forem feitas. A criação é uma operação de autenticação, não alteração do servidor:

```http
POST /redfish/v1/SessionService/Sessions
Content-Type: application/json

{"UserName":"USUARIO","Password":"SEGREDO"}
```

A resposta fornece:

- header `X-Auth-Token`;
- header `Location` com a URI da sessão.

Enviar o token nas consultas:

```http
X-Auth-Token: TOKEN
Accept: application/json
```

Ao final, executar `DELETE` na URI de `Location` com o token. Nunca registrar token, payload de login ou headers de sessão em log. Limitar sessões simultâneas e recriar somente após expiração/erro de autenticação.

## 6. Recursos a percorrer

### ComputerSystem

Seguir cada membro de `Systems` e coletar:

- `Id`, `Name`, `Model`, `Manufacturer`, `SerialNumber`/Service Tag;
- `PowerState`;
- `Status.State` e `Status.Health`/`HealthRollup`;
- `ProcessorSummary`;
- `MemorySummary`;
- links de `Processors`, `Memory`, `Storage`, `EthernetInterfaces`, `LogServices` quando presentes;
- BIOS/boot/security apenas como leitura e quando exigidos.

### Chassis

Seguir cada membro de `Chassis` e seus links:

- `Status` e tipo do chassi;
- `Sensors`, se implementado;
- `ThermalSubsystem`/`PowerSubsystem` nas versões novas;
- `Thermal`/`Power` nos modelos que usam recursos legados;
- fans, temperaturas, fontes, consumo e redundância;
- `LogServices` quando presente.

O código deve seguir o link oferecido pela resposta, não montar um caminho legado à força.

### Manager/iDRAC

Coletar:

- firmware do manager;
- `Status`;
- `DateTime` e offset;
- `NetworkProtocol` e certificado apenas se o privilégio permitir;
- `LogServices`/Lifecycle Log;
- atributos Dell OEM somente quando o dado não existir no schema padrão e estiver documentado para a versão.

### Storage

A partir de `ComputerSystem.Storage`, descobrir:

- controladores;
- drives;
- volumes/virtual disks;
- estado/health;
- capacidade em bytes;
- protocolo/media type;
- RAID/redundância;
- predictive failure e spare, quando expostos.

Manter o `@odata.id` como identidade técnica e atributos físicos para correlação. Não usar a posição do drive no array JSON.

### Logs

Descobrir `LogServices` no System, Chassis e Manager. Para cada serviço, seguir `Entries.@odata.id` e coletar apenas janela/paginação necessárias:

- ID do registro;
- severidade;
- `MessageId`;
- mensagem;
- criação;
- componente/origem;
- resolução/estado quando disponível.

Evitar recuperar todo o Lifecycle Log a cada minuto. Usar paginação/filtros oferecidos e checkpoint por ID/timestamp.

## 7. Mapeamento funcional

| Critério | Métrica | Caminho conceitual | Interpretação |
|---|---|---|---|
| Disponibilidade | Estado do servidor | `Systems -> Member -> Status` | Preservar `State`, `Health` e `HealthRollup` separadamente. |
| Disponibilidade | Estado do iDRAC | `Managers -> Member -> Status` | Distinguir manager inacessível de servidor desligado. |
| Disponibilidade | Chassi/sensores | `Chassis -> Sensors/Thermal/Power` | Descobrir cada sensor por `@odata.id`/ID. |
| Disponibilidade | Componentes | Processors, Memory, Storage | Contar estados ruins e preservar componente afetado. |
| Capacidade | Memória | `MemorySummary` + coleção Memory | Total instalado; slots individuais somente para diagnóstico. |
| Capacidade | Disco/volume local | Storage/Drives/Volumes | Bytes e RAID; não somar discos físicos e volumes como uma capacidade única. |
| Performance | Temperatura/fan/energia | Chassis/Telemetry | Gauge com unidade informada pelo schema. |
| Performance | CPU/storage detalhado | Telemetry, se suportado | Não prometer se licença/recurso não existir; SO pode ser fonte alternativa. |
| Proteção | RAID/controlador/drive | Storage | Health, estado, redundância, spare e predictive failure. |
| Segurança | Firmware | Manager/System | Inventário diário; correlação de vulnerabilidade é processo separado. |
| Segurança | Certificado/protocolos | Manager NetworkProtocol/Certificate ou TLS | Somente leitura; validar expiração, cadeia e hostname. |
| Segurança | Logs/auditoria | LogServices | MessageId/severidade/timestamp; filtrar dados sensíveis. |
| Segurança | Secure Boot/SPDM | System/OEM quando presente | Coletar estado documentado; recurso ausente é não suportado, não disabled. |

## 8. Telemetry opcional

Se `TelemetryService` estiver presente e licenciado:

1. Consultar `GET /redfish/v1/TelemetryService`.
2. Seguir `MetricReportDefinitions` e `MetricReports`.
3. Inventariar relatórios predefinidos disponíveis.
4. Preferir pull dos relatórios já existentes no primeiro ciclo.
5. Só habilitar serviço ou criar definição mediante mudança aprovada; a monitoração normal não deve emitir `PATCH`.

Os relatórios podem incluir saúde, energia, temperatura e performance de servidor/storage. Registrar definição, unidade, intervalo e licença junto à amostra.

## 9. Paginação e schemas

- Seguir `Members@odata.nextLink` quando presente.
- Usar `@odata.id` e `@odata.type` para identificar recurso/schema.
- Aceitar propriedades opcionais ausentes.
- Propriedade OEM deve ficar isolada em adaptador específico de firmware.
- Não tratar `null` como zero.
- Guardar um ServiceRoot e amostras após cada upgrade de iDRAC para teste de regressão.

## 10. Frequência inicial

| Coleta | Frequência |
|---|---:|
| Acesso, System/Manager health | 1 a 2 minutos |
| Chassi, sensores, storage health | 3 a 5 minutos |
| Energia/temperatura | 1 a 5 minutos |
| Logs incrementais | 2 a 5 minutos |
| Inventário/capacidade/firmware | 12 a 24 horas |
| Telemetry | conforme definição, normalmente 1 a 5 minutos |

## 11. Tratamento de falhas

- `401`: sessão/credencial; `403`: privilégio; separar de iDRAC offline.
- Servidor `PowerState=Off` pode ser esperado; iDRAC deve continuar respondendo.
- Membro ausente pode indicar hardware removido; executar descoberta antes de alarmar.
- `Status.Health` ausente não equivale a OK.
- Log vazio não prova saúde; saúde vem dos recursos atuais.
- Redfish pode responder `200` com propriedades diferentes entre firmwares; validar schema.
- Timeout do iDRAC e timeout do sistema operacional são eventos independentes.

## 12. Evidências obrigatórias

- modelo PowerEdge, geração, Service Tag sanitizada e firmware iDRAC.
- licença iDRAC/Telemetry.
- ServiceRoot, coleções e um membro de System/Chassis/Manager.
- Storage com controlador, drive e volume sanitizados.
- Thermal/Power ou subsistemas/Sensors conforme a implementação.
- LogServices/Entries com um evento saudável e um de teste/histórico.
- `@odata.nextLink`, se houver.
- lista de propriedades OEM realmente necessárias.
- conta/privilégio mínimo validado.

## 13. Testes de aceitação

- [ ] ServiceRoot responde com TLS confiável.
- [ ] IDs são descobertos, não fixados.
- [ ] Sessão é encerrada e token não aparece em log.
- [ ] Estado do System, Manager e Chassis é armazenado separadamente.
- [ ] Um servidor desligado não é confundido com iDRAC indisponível.
- [ ] Drive/controlador degradado pode ser identificado pelo seu ID.
- [ ] Telemetry ausente/licença ausente é `não suportado`, não zero.
- [ ] Reinicialização/upgrade do iDRAC dispara redescoberta sem duplicar hardware.

## 14. Referências oficiais

- [Dell — iDRAC RESTful API baseada em Redfish](https://www.dell.com/support/manuals/en-us/poweredge-r760/smog_26.0/idrac-restful-apis-redfish-standards-based?guid=guid-476c6603-818e-4e2e-82f0-699bde0c3a3c&lang=en-us)
- [Dell — autenticação e autorização Redfish](https://www.dell.com/support/manuals/en-ae/idrac9-lifecycle-controller-v3.1-series/idrac_3.18.18.18_redfishapiguide/redfish-authentication-and-authorization?guid=guid-d572792f-afd2-499a-bf12-38a6778b9bbc&lang=en-us)
- [DMTF — Redfish Resource and Schema Guide](https://redfish.dmtf.org/)
- [Dell — visão geral da telemetria iDRAC](https://www.dell.com/support/manuals/en-us/poweredge-r760/idrac_telemetry_reference_guide_pub/Overview-of-iDRAC-Telemetry?guid=guid-37b2a1b2-d768-4c37-872a-f8b3694bc2b8&lang=en-us)
- [Dell — lista de relatórios predefinidos de telemetria](https://www.dell.com/support/manuals/en-us/poweredge-r760xd2/idrac_telemetry_reference_guide_pub/list-of-predefined-metric-reports-supported-in-telemetry?guid=guid-ae1f6dee-1010-4432-b54b-9233cc2faf72&lang=en-us)
