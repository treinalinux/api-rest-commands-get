# Connectrix B-Series e C-Series — especificação de coleta

## 1. Decisão

**Mínimo recomendado:** SNMPv3, polling de estado/contadores e traps ou informs.  
**Complemento:** syslog para autenticação e mudanças de configuração; SANnav/NDFC somente se a organização decidir centralizar a coleta nessas plataformas.

`Connectrix` é uma família comercial, não um único sistema operacional. O primeiro passo obrigatório é separar:

- **B-Series:** switches Brocade com Fabric OS;
- **C-Series:** switches Cisco MDS com NX-OS/SAN-OS.

Não misturar MIBs, enumerações ou índices das duas plataformas no mesmo mapeamento.

## 2. Escopo mínimo

| Critério | Entrega mínima |
|---|---|
| Disponibilidade | Uptime, saúde do chassi, PSU/fan/temperatura, estado operacional das portas FC, ISLs e componentes. |
| Capacidade | Portas instaladas, licenciadas/ativadas quando disponível, ocupadas, livres e velocidade negociada. |
| Performance | Bytes/frames, utilização, erros FC, descartes, perda de sincronismo/sinal e congestionamento/BB credit quando a MIB expuser. |
| Proteção | Não aplicável como backup/replicação. Monitorar redundância de fabric e ISLs como disponibilidade. |
| Segurança observável | Versão, estado de autenticação/AAA exposto, traps/syslog de login/configuração e validade do certificado de gerência. |

## 3. Identificação obrigatória

Antes de instalar MIB de fabricante:

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

Registrar:

- fabricante real;
- modelo/chassi;
- versão Fabric OS ou NX-OS;
- WWN do switch;
- fabric/VSAN;
- director ou switch fixo;
- quantidade de slots e portas;
- licenças que alteram métricas;
- `sysObjectID.0`.

O `sysObjectID` determina qual ramo de descoberta e quais MIBs usar.

## 4. Pré-requisitos comuns

- SNMPv3 com `authPriv`, conta somente leitura e view limitada às árvores necessárias.
- UDP 161 do Zabbix Server/Proxy para cada endereço de gerência.
- UDP 162 do switch para o receptor de traps/informs.
- MIBs exatamente correspondentes ao firmware.
- Sincronismo NTP.
- Relação porta física ↔ nome lógico ↔ WWN ↔ alias documentada.
- Para syslog, transporte TLS quando suportado e política de retenção aprovada.

## 5. Ramo B-Series — Fabric OS

### Fonte

Usar SNMPv3 e o pacote de MIBs publicado para a release instalada do Fabric OS. A Broadcom informa suporte a MIBs e SNMP para monitoração; a lista concreta e as revisões devem vir do pacote da release.

Gerar inventário de símbolos de cada módulo:

```bash
for modulo in MODULO_BROCADE_1 MODULO_BROCADE_2; do
  snmptranslate -M +/usr/local/share/snmp/mibs-connectrix-b \
    -m "+${modulo}" -Tz
done | sort -u > connectrix_b_mib_symbols.txt
```

Walk mínimo:

```bash
snmpwalk -v3 -l authPriv \
  -u 'USUARIO_SNMP' \
  -a SHA-256 -A 'SEGREDO_AUTH' \
  -x AES -X 'SEGREDO_PRIV' \
  -M +/usr/local/share/snmp/mibs-connectrix-b \
  -m +ALL \
  SWITCH_FQDN \
  'OID_RAIZ_BROCADE_VALIDADO' > connectrix_b_vendor_walk.txt
```

Além do walk, habilitar e enviar uma trap de teste pelo procedimento suportado pelo Fabric OS. SANnav pode ser usado como fonte de confirmação; não deve virar dependência do mínimo sem decisão arquitetural.

### Métricas a localizar nas MIBs do Fabric OS

- WWN, nome, domínio e fabric do switch;
- estado de chassi, FRUs, fontes, fans e sensores;
- inventário de portas, tipo, estado administrativo e operacional;
- velocidade configurada e negociada;
- bytes/frames transmitidos e recebidos;
- CRC, encoding/invalid word, link failure, loss of signal e loss of sync;
- descartes, congestionamento e BB-credit-zero, se suportados/licenciados;
- estado de ISLs e trunk;
- traps MAPS/fabric/eventos com severidade e recuperação.

## 6. Ramo C-Series — Cisco MDS

### Fonte

Usar SNMPv3 com os MIBs entregues para a release MDS NX-OS. A Cisco mantém uma referência específica dos MIBs MDS. A conta SNMP participa do modelo de usuários e roles do switch; criar role de leitura mínima.

Carregar primeiro os módulos padrão e depois os Cisco MDS requeridos. Exemplos de famílias a avaliar na referência da release:

- IF-MIB;
- ENTITY-MIB e ENTITY-SENSOR-MIB;
- MIBs Fibre Channel e FC management;
- MIBs Cisco de entidade, ambiente, VSAN, fabric e interfaces FC;
- módulos de notificações e Call Home aplicáveis.

Não declarar que um módulo é suportado apenas porque existe em outra release. Confirmar com o MIB locator/referência do NX-OS instalado.

Walk mínimo:

```bash
snmpwalk -v3 -l authPriv \
  -u 'USUARIO_SNMP' \
  -a SHA-256 -A 'SEGREDO_AUTH' \
  -x AES -X 'SEGREDO_PRIV' \
  -M +/usr/local/share/snmp/mibs-connectrix-c \
  -m +ALL \
  SWITCH_FQDN \
  ENTITY-MIB::entPhysicalTable > connectrix_c_entity_walk.txt
```

```bash
snmpwalk -v3 -l authPriv \
  -u 'USUARIO_SNMP' \
  -a SHA-256 -A 'SEGREDO_AUTH' \
  -x AES -X 'SEGREDO_PRIV' \
  -M +/usr/local/share/snmp/mibs-connectrix-c \
  -m +ALL \
  SWITCH_FQDN \
  IF-MIB::ifXTable > connectrix_c_ifx_walk.txt
```

Métricas FC específicas devem ser localizadas nos módulos MDS descritos pela referência oficial e conferidas com comandos `show interface fc...` e `show environment`, sem usar scraping de CLI como fonte principal.

## 7. Identidade e descoberta de portas

Uma porta não deve ser identificada só por `ifIndex`, pois o índice pode mudar após upgrade ou reinicialização.

O contrato de descoberta deve guardar:

- ID/índice retornado pela MIB;
- `ifName` ou nome equivalente;
- alias/descrição;
- WWN da porta, quando disponível;
- slot e porta física;
- tipo: F-Port, E-Port, ISL etc.;
- fabric/VSAN;
- velocidade nominal.

Na atualização, correlacionar pelo identificador mais estável disponível e tratar porta removida como fim de descoberta, não como valor zero eterno.

## 8. Mapeamento funcional

| Critério | Métrica | Fonte preferida | Regra de extração |
|---|---|---|---|
| Disponibilidade | Acesso e uptime | `sysUpTime.0` | TimeTicks; queda do uptime indica reboot. |
| Disponibilidade | Chassi/FRU/sensores | ENTITY e MIB do fabricante | Descobrir por índice físico e preservar enumerações. |
| Disponibilidade | Porta FC | MIB FC/fabric do fabricante | Separar admin state, oper state e motivo da transição. |
| Disponibilidade | ISL/trunk/fabric | MIB do fabricante | Descobrir todos os membros; não resumir antes de guardar o membro afetado. |
| Capacidade | Total de portas | Inventário físico/licenciamento | Distinguir instalada, licenciada, habilitada, conectada e livre. |
| Capacidade | Velocidade | MIB de interface/FC | Usar velocidade negociada e unidade documentada. |
| Performance | Tráfego | Contadores de 64 bits quando disponíveis | Calcular taxa por delta e tempo; separar RX/TX. |
| Performance | Utilização | Tráfego e velocidade | `% = 100 × bits/s ÷ velocidade_bits/s`; calcular por direção. |
| Performance | Erros FC | MIB FC | Calcular delta; manter tipo de erro separado. |
| Performance | Congestionamento/credits | MIB do fabricante/MAPS | Disponibilidade e licença variam; não inventar zero quando ausente. |
| Segurança | Versão/configuração | Inventário + traps/syslog | Versão diária; eventos com ID, usuário, origem e horário quando expostos. |
| Segurança | Certificado | TLS externo | Dias para expiração e erro de cadeia/hostname. |

## 9. Contadores e taxas

Para contadores cumulativos:

```text
taxa_por_segundo = (valor_atual - valor_anterior) / segundos_decorridos
```

Para octetos:

```text
bits_por_segundo = delta_octetos * 8 / segundos_decorridos
```

Descartar a amostra de delta quando:

- `sysUpTime` diminuiu;
- contador atual é menor por reset ou wrap;
- intervalo real é zero ou excessivamente grande;
- velocidade da porta é desconhecida;
- o estado operacional não permite interpretar tráfego.

Preferir contadores de 64 bits. Em portas de alta velocidade, contadores de 32 bits podem girar entre duas coletas.

## 10. Traps, informs e syslog

Coletar traps/informs para:

- mudança de estado de porta/ISL;
- falha/recuperação de fan, PSU, temperatura e módulo;
- mudança de fabric/VSAN;
- eventos MAPS ou OHMS relevantes;
- reinicialização;
- autenticação/configuração quando o fabricante expuser.

Manter polling porque notificações não garantem a fotografia completa do estado. Syslog deve ser usado para eventos de autenticação e configuração que não existam nas MIBs, com parsing pela identificação/código documentado da release.

## 11. Frequência inicial

| Coleta | Frequência |
|---|---:|
| Uptime e estado de porta/ISL | 1 minuto |
| Contadores de tráfego/erro | 1 minuto |
| Ambiente e chassi | 3 a 5 minutos |
| Inventário/licenças/versão | 12 a 24 horas |
| Traps/informs/syslog | contínuo |

## 12. Evidências obrigatórias

- `sysDescr`, `sysObjectID`, versão e modelo.
- Lista de MIBs com origem e checksum.
- Walk padrão de `entPhysicalTable`, sensores e `ifXTable`.
- Walk das árvores FC/fabric do fabricante.
- Uma tabela correlacionando índice, porta física, WWN, alias e fabric/VSAN.
- Captura da GUI/CLI no mesmo instante para uma porta online, uma offline e um ISL.
- Trap de teste decodificada.
- Amostras antes/depois para validar taxa de tráfego.
- Lista explícita de métricas dependentes de licença.

## 13. Testes de aceitação

- [ ] B-Series e C-Series foram classificados corretamente.
- [ ] SNMPv3 `authPriv` responde sem abrir árvore de escrita.
- [ ] O inventário SNMP confere com o switch.
- [ ] Um flap de porta em laboratório muda estado e gera notificação.
- [ ] Taxa calculada confere aproximadamente com o contador da CLI/GUI.
- [ ] Reboot não produz taxa negativa ou pico artificial.
- [ ] Porta sem óptico não é interpretada como sensor quebrado.
- [ ] Proteção de backup/replicação está marcada como não aplicável.

## 14. Referências oficiais

- [Broadcom — Fabric OS: suporte a SNMP e MIBs](https://docs.broadcom.com/doc/GA-DS-998)
- [Broadcom SANnav — coleta histórica por SNMPv3](https://docs.broadcom.com/htmldocs/SANnav111/SANnav111/v25274476.html)
- [Cisco MDS 9000 Release 9.x — configuração SNMP](https://www.cisco.com/c/en/us/td/docs/dcn/mds9000/sw/9x/configuration/system-management/cisco-mds-9000-nx-os-system-management-configuration-guide-9x/configuring_snmp.html)
- [Cisco MDS 9000 — referência de MIBs](https://www.cisco.com/c/en/us/td/docs/dcn/mds9000/mib/cisco-mds-9000-nx-os-MIB-quick-reference.html)
- [Cisco MDS 9000 — monitoração de estado do sistema](https://www.cisco.com/c/en/us/td/docs/dcn/mds9000/sw/9x/configuration/system-management/cisco-mds-9000-nx-os-system-management-configuration-guide-9x/monitoring_system_processes_and_logs.html)
