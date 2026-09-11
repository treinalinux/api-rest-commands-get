# PowerSwitch com SmartFabric OS10 — especificação de coleta

## 1. Decisão

**Mínimo recomendado:** SNMPv3 `authPriv` com MIBs padrão e Dell OS10, complementado por traps/informs e syslog.  
**Evolução futura:** gNMI/OpenConfig ou RESTCONF quando houver necessidade de streaming ou grande escala.

SNMPv3 é o caminho mais curto para um template mínimo: cobre inventário, portas, contadores, ambiente e protocolos sem instalar agente. gNMI é útil, mas adiciona cliente, certificados, subscriptions e desenho de pipeline que não são necessários para a primeira entrega.

## 2. Escopo mínimo

| Critério | Entrega mínima |
|---|---|
| Disponibilidade | Uptime, chassi, PSU/fan/temperatura, interfaces, LACP/VLT e vizinhança/protocolos relevantes. |
| Capacidade | Portas totais, habilitadas, conectadas, livres, velocidade e percentual de utilização. |
| Performance | Tráfego RX/TX, erros, descartes, utilização, CPU/memória quando expostos e ópticos DOM quando suportados. |
| Proteção | Não aplicável como backup. Redundância de VLT/LACP/rotas pertence à disponibilidade. |
| Segurança observável | Versão, estado de serviços de gerência, traps/syslog de autenticação/configuração e validade TLS. |

Confirmar que o equipamento realmente executa SmartFabric OS10. Hardware `-ON` pode executar outro NOS; nesse caso este documento não se aplica.

## 3. Pré-requisitos

- Modelo, `show version` e release exata do OS10.
- Função do switch: acesso, leaf/spine, storage, management etc.
- SNMPv3 com conta somente leitura e `authPriv`.
- UDP 161 para polling e UDP 162 para traps/informs.
- MIBs da release; no OS10 elas são armazenadas no equipamento em `/opt/dell/os10/snmp/mibs/` e também podem acompanhar o software.
- NTP consistente.
- Inventário de VLT, port-channels, BGP, VRF e transceivers a monitorar.
- Syslog remoto TLS se eventos de segurança/configuração fizerem parte do mínimo.

## 4. Exemplo de configuração no switch

A sintaxe varia por release. O administrador de rede deve confrontar este exemplo com o guia do OS10 instalado:

```text
snmp-server view ZABBIX-READ 1.3.6.1 included
snmp-server group ZABBIX-GROUP 3 priv read ZABBIX-READ
snmp-server user ZABBIX-USER ZABBIX-GROUP 3 auth sha SEGREDO_AUTH priv aes SEGREDO_PRIV
snmp-server host IP_RECEPTOR informs version 3 priv ZABBIX-USER
snmp-server location LOCAL_APROVADO
```

Em produção:

- limitar a view às árvores necessárias depois da descoberta;
- usar segredos aprovados, nunca os textos acima;
- preferir informs quando a política exigir confirmação, avaliando carga/retries;
- habilitar somente categorias de traps necessárias;
- não conceder escrita.

O OS10 possui categorias específicas, inclusive traps DOM de temperatura, tensão, RX power, TX power e bias em releases que suportam esse recurso.

## 5. Obter e carregar as MIBs

Copiar os arquivos correspondentes à release para um diretório controlado:

```text
/usr/local/share/snmp/mibs-os10/
```

Validar dependências e símbolos:

```bash
snmptranslate \
  -M +/usr/local/share/snmp/mibs-os10 \
  -m +ALL \
  -Tz | sort > os10_mib_symbols.txt
```

Módulos base a avaliar:

- SNMPv2-MIB;
- IF-MIB;
- ENTITY-MIB;
- ENTITY-SENSOR-MIB;
- LLDP-MIB;
- BRIDGE/Q-BRIDGE MIBs quando houver L2;
- LACP/IEEE MIBs aplicáveis;
- DELLEMC-OS10-CHASSIS-MIB;
- MIBs Dell OS10 para VLT, BGP e recursos realmente utilizados.

A lista exata deve ser retirada do guia da release, não de outro modelo.

## 6. Validação de polling

```bash
snmpget -v3 -l authPriv \
  -u 'USUARIO_SNMP' \
  -a SHA-256 -A 'SEGREDO_AUTH' \
  -x AES -X 'SEGREDO_PRIV' \
  SWITCH_FQDN \
  SNMPv2-MIB::sysDescr.0 \
  SNMPv2-MIB::sysObjectID.0 \
  SNMPv2-MIB::sysUpTime.0
```

Inventário e interfaces:

```bash
snmpwalk -v3 -l authPriv \
  -u 'USUARIO_SNMP' \
  -a SHA-256 -A 'SEGREDO_AUTH' \
  -x AES -X 'SEGREDO_PRIV' \
  SWITCH_FQDN \
  ENTITY-MIB::entPhysicalTable > os10_entity_walk.txt
```

```bash
snmpwalk -v3 -l authPriv \
  -u 'USUARIO_SNMP' \
  -a SHA-256 -A 'SEGREDO_AUTH' \
  -x AES -X 'SEGREDO_PRIV' \
  SWITCH_FQDN \
  IF-MIB::ifXTable > os10_ifx_walk.txt
```

Sensores:

```bash
snmpwalk -v3 -l authPriv \
  -u 'USUARIO_SNMP' \
  -a SHA-256 -A 'SEGREDO_AUTH' \
  -x AES -X 'SEGREDO_PRIV' \
  SWITCH_FQDN \
  ENTITY-SENSOR-MIB::entPhySensorTable > os10_sensor_walk.txt
```

Se uma árvore retornar `noSuchObject`, confirmar suporte na MIB/release; não converter em zero.

## 7. Descoberta de interfaces

Para cada `ifIndex`, coletar e correlacionar:

- `ifName`;
- `ifAlias`;
- `ifDescr`;
- `ifType`;
- estado administrativo e operacional;
- `ifHighSpeed` ou velocidade equivalente;
- MTU;
- endereço físico quando aplicável;
- contadores de 64 bits RX/TX;
- erros e descartes;
- `ifLastChange`;
- vínculo com port-channel/VLT e vizinho LLDP, quando necessário.

Identidade recomendada: nome lógico estável mais atributos físicos. `ifIndex` continua necessário para polling, mas não deve ser a única identidade após redescoberta.

Filtrar conscientemente interfaces que não geram ação: loopback, internas, CPU/control plane e subinterfaces. Não filtrar apenas por texto sem validar no modelo.

## 8. Cálculo de performance

Usar `ifHCInOctets` e `ifHCOutOctets` quando disponíveis:

```text
rx_bits_s = (rx_atual - rx_anterior) * 8 / segundos
tx_bits_s = (tx_atual - tx_anterior) * 8 / segundos
```

```text
rx_util_pct = 100 * rx_bits_s / velocidade_bits_s
tx_util_pct = 100 * tx_bits_s / velocidade_bits_s
```

Regras:

- calcular RX e TX separadamente em full duplex;
- usar velocidade operacional/negociada quando documentada;
- descartar delta se `sysUpTime` diminuiu ou contador reiniciou;
- detectar wrap, especialmente em Counter32;
- erros e descartes também devem ser convertidos em delta/taxa;
- não somar links físicos e seu port-channel no mesmo total;
- não interpretar potência óptica sem unidade, escala e thresholds DOM da MIB.

## 9. Mapeamento funcional

| Critério | Métrica | Fonte | Extração |
|---|---|---|---|
| Disponibilidade | Uptime/reboot | `sysUpTime.0` | TimeTicks; queda indica reinicialização. |
| Disponibilidade | Chassi/FRUs | ENTITY + Dell chassis MIB | Descobrir todos os componentes e estado por índice. |
| Disponibilidade | Interface | IF-MIB | Admin, oper e last change separados. |
| Disponibilidade | VLT/LACP/BGP | MIB Dell/padrão da release | Somente protocolos configurados; manter peer/membro afetado. |
| Capacidade | Portas totais/livres | descoberta IF/ENTITY | Definir claramente física, breakout, licenciada e utilizável. |
| Capacidade | Utilização | HC octets + velocidade | Percentual por direção; `unknown` se velocidade não for confiável. |
| Performance | RX/TX | IF-MIB | Delta de Counter64 por segundo. |
| Performance | Erros/descartes | IF-MIB/MIB física | Delta; separar erros de descartes e direção. |
| Performance | CPU/memória | Dell OS10 MIB | Confirmar símbolo, unidade e intervalo na MIB instalada. |
| Performance | DOM | Dell/DOM MIB | Temperatura, tensão, potência RX/TX e bias com escala correta. |
| Segurança | Versão | `sysDescr` + Dell MIB | Texto diário; não é avaliação de patch. |
| Segurança | Login/configuração | traps/syslog | Código, usuário/origem quando permitido, resultado e horário. |
| Segurança | HTTPS | handshake TLS | Cadeia, hostname e expiração. |

## 10. Traps/informs e syslog

Habilitar, conforme função do switch:

- cold/warm start;
- link up/down com política para evitar tempestade;
- fan/PSU/temperatura;
- DOM;
- VLT/LACP/BGP ou protocolos críticos;
- mudanças de configuração e autenticação por syslog.

Testar origem por management VRF e IPv4/IPv6. Registrar se a notificação sai pelo IP esperado; isso afeta firewall e identificação no receptor.

## 11. Frequência inicial

| Coleta | Frequência |
|---|---:|
| Uptime/estado de interfaces críticas | 1 minuto |
| Contadores HC/erros/descartes | 1 minuto |
| VLT/LACP/BGP | 1 a 2 minutos |
| Ambiente/DOM | 3 a 5 minutos |
| CPU/memória | 3 a 5 minutos |
| Inventário/versão/LLDP | 1 a 24 horas |
| Traps/informs/syslog | contínuo |

## 12. Quando considerar gNMI/RESTCONF

Considerar gNMI/OpenConfig depois do mínimo se houver:

- centenas de switches/portas com polling SNMP pesado;
- requisito de streaming de baixa latência;
- equipe capaz de operar certificados e subscriptions;
- caminhos OpenConfig confirmados na release;
- consumidor preparado para receber, normalizar e reenviar ao Zabbix.

Não habilitar gNMI apenas porque existe. Medir o benefício e documentar paths, encoding, sample interval, TLS e reconexão.

## 13. Evidências obrigatórias

- modelo, OS10, `sysObjectID` e função do switch.
- pacote de MIBs/checksum e lista de módulos usados.
- walks de ENTITY, sensores, IF-MIB e MIBs Dell selecionadas.
- correlação de portas, breakout e port-channels.
- duas amostras de contadores com intervalo conhecido.
- evento link/DOM ou trap de teste.
- syslog de teste sanitizado, se segurança entrar no mínimo.
- comparação com `show interface`, ambiente e VLT/LACP/BGP no mesmo instante.

## 14. Testes de aceitação

- [ ] Equipamento executa OS10, não outro NOS.
- [ ] SNMPv3 `authPriv` e view somente leitura funcionam.
- [ ] Interface é redescoberta sem depender apenas de `ifIndex`.
- [ ] RX/TX e utilização conferem aproximadamente com CLI.
- [ ] Reboot não cria pico de tráfego.
- [ ] Port-channel não duplica a soma dos membros.
- [ ] Sensor/DOM ausente é não suportado, não zero.
- [ ] Traps/informs chegam pelo IP/VRF previstos.
- [ ] Proteção de backup está marcada como não aplicável.

## 15. Referências oficiais

- [Dell SmartFabric OS10 — MIBs suportadas](https://www.dell.com/support/manuals/en-us/smartfabric-os10-emp-partner/smartfabric-os-user-guide-10-5-6/mibs?guid=guid-1521dfef-87fd-44d5-85f9-0b8813373278&lang=en-us)
- [Dell PowerSwitch OS10 — configuração SNMPv3](https://www.dell.com/support/kbdoc/en-us/000204282/configure-snmp-v3-on-os10-switches)
- [Dell OS10 — views SNMP](https://www.dell.com/support/manuals/en-us/smartfabric-os10-emp-partner/smartfabric-os-user-guide-10-5-6/configure-snmp-views?guid=guid-b1364dc9-421f-4509-9c38-d51180942b2c&lang=en-us)
- [Dell OS10 — traps DOM](https://www.dell.com/support/manuals/en-us/smartfabric-os10-emp-partner/smartfabric-os-user-guide-10-5-5/enable-dom-traps?guid=guid-5304b46a-5d87-4973-ad75-5321b066f4f8&lang=en-us)
- [Dell OS10 — gNMI/OpenConfig](https://www.dell.com/support/manuals/en-us/dell-emc-smartfabric-os10/smartfabric-os-user-guide-10-5-2-6/grpc-network-management-interface-agent?guid=guid-9d4c66d3-178d-4122-baed-6914977fe93e&lang=en-us)
