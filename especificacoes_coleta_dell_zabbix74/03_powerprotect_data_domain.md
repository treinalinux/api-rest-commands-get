# PowerProtect Data Domain — especificação de coleta

## 1. Decisão

**Mínimo recomendado:** SNMPv3 `authPriv`, usando simultaneamente a DDOS MIB baixada do próprio sistema e a MIB-II padrão, mais traps SNMP.  
**Complemento:** API oficial da versão ou CLI somente para campos comprovadamente ausentes na MIB.

Para a entrega rápida, não começar por scraping SSH. A Dell documenta que a cobertura SNMP requer a DDOS MIB para dados específicos e MIB-II para informações gerais, como rede. A MIB da instalação é o contrato da versão.

## 2. Escopo mínimo

| Critério | Entrega mínima |
|---|---|
| Disponibilidade | Acesso SNMP, uptime, filesystem/serviços, HA quando existente, hardware e alertas. |
| Capacidade | Total, usado, disponível e percentual do filesystem; Active Tier/Cloud Tier quando configurados; capacidade de MTree se exposta. |
| Performance | CPU, rede, disco/filesystem, throughput e taxas expostas pela DDOS MIB. |
| Proteção | Estado de replicação, atrasos/falhas, estado de RAID/discos e alertas de risco. |
| Segurança observável | Versão, SNMPv3, criptografia/Cloud Tier quando exposta, validade TLS e alertas de segurança. |

## 3. Pré-requisitos

- Modelo e DDOS exatos.
- Topologia: standalone, HA, DDVE, tiers e expansões.
- DDOS MIB baixada em `Administration > Settings > SNMP` no sistema monitorado.
- Usuário SNMPv3 somente leitura com autenticação e privacidade.
- UDP 161 para polling e UDP 162 para traps.
- NTP consistente.
- Inventário dos recursos habilitados: filesystem, DD Boost, replication, MTrees, Cloud Tier, encryption e SupportAssist.

## 4. Como habilitar

No DD System Manager:

1. Abrir `Administration > Settings > SNMP`.
2. Habilitar SNMP.
3. Criar usuário SNMPv3 somente leitura.
4. Selecionar autenticação e privacidade conforme política.
5. Criar o trap host/receptor quando traps fizerem parte do escopo.
6. Baixar a MIB da própria tela.

Não habilitar comunidade `public`/`private`. Não conceder leitura/escrita quando a monitoração só precisa consultar.

## 5. Descoberta da MIB

Instalar ferramentas no RHEL:

```bash
sudo dnf install net-snmp-utils
```

Guardar a MIB em diretório controlado e identificar o nome do módulo declarado no arquivo. Um nome comum é `DATA-DOMAIN-MIB`, mas deve ser confirmado na MIB baixada.

```bash
snmptranslate \
  -M +/usr/local/share/snmp/mibs-dd \
  -m +DATA-DOMAIN-MIB \
  -Tz | sort > ddos_mib_symbols.txt
```

```bash
snmptranslate \
  -M +/usr/local/share/snmp/mibs-dd \
  -m +DATA-DOMAIN-MIB \
  -Tp > ddos_mib_tree.txt
```

Procurar candidatos pelas descrições:

```bash
rg -i 'file.?system|space|capacity|used|avail|status|alert|replication|mtree|tier|disk|cpu|network|throughput|temperature|ha|encryption' \
  ddos_mib_symbols.txt ddos_mib_tree.txt
```

Para cada objeto selecionado:

```bash
snmptranslate \
  -M +/usr/local/share/snmp/mibs-dd \
  -m +DATA-DOMAIN-MIB \
  -Td 'DATA-DOMAIN-MIB::SIMBOLO_VALIDADO'
```

A descrição deve confirmar unidade, acesso, índice e enumeração. Só então registrar o OID numérico:

```bash
snmptranslate \
  -M +/usr/local/share/snmp/mibs-dd \
  -m +DATA-DOMAIN-MIB \
  -On 'DATA-DOMAIN-MIB::SIMBOLO_VALIDADO'
```

## 6. Validação de polling

Teste padrão:

```bash
snmpget -v3 -l authPriv \
  -u 'USUARIO_SNMP' \
  -a SHA-256 -A 'SEGREDO_AUTH' \
  -x AES -X 'SEGREDO_PRIV' \
  DD_FQDN \
  SNMPv2-MIB::sysUpTime.0 \
  SNMPv2-MIB::sysName.0
```

Rede de 64 bits:

```bash
snmpwalk -v3 -l authPriv \
  -u 'USUARIO_SNMP' \
  -a SHA-256 -A 'SEGREDO_AUTH' \
  -x AES -X 'SEGREDO_PRIV' \
  DD_FQDN \
  IF-MIB::ifXTable > dd_ifx_walk.txt
```

Árvore do fabricante:

```bash
snmpwalk -v3 -l authPriv \
  -u 'USUARIO_SNMP' \
  -a SHA-256 -A 'SEGREDO_AUTH' \
  -x AES -X 'SEGREDO_PRIV' \
  -M +/usr/local/share/snmp/mibs-dd \
  -m +DATA-DOMAIN-MIB \
  DD_FQDN \
  'DATA-DOMAIN-MIB::SIMBOLO_RAIZ' > dd_vendor_walk.txt
```

Os segredos dos exemplos são marcadores. Não armazená-los em script, histórico, documento ou payload.

## 7. Mapeamento a fechar com a MIB real

| Critério | Objeto funcional | Onde procurar | Interpretação |
|---|---|---|---|
| Disponibilidade | Uptime | `sysUpTime.0` | Detecta reinicialização do agente/sistema. |
| Disponibilidade | Estado do filesystem | DDOS MIB | Preservar enumeração; diferenciar disabled, not running, degraded e unknown. |
| Disponibilidade | HA e controladores | DDOS MIB, se HA | Guardar papel e estado de cada membro; não apenas resumo. |
| Disponibilidade | Alertas atuais | DDOS MIB + traps | Separar ativo, reconhecido e resolvido conforme a MIB. |
| Disponibilidade | Hardware | DDOS MIB | Discos, shelves, PSU, fan, temperatura e componentes presentes na versão. |
| Capacidade | Filesystem total/usado/livre | DDOS MIB | Usar campos com mesma unidade/base; não somar tiers incompatíveis. |
| Capacidade | Active/Cloud Tier | DDOS MIB | Criar objetos separados apenas se configurados. |
| Capacidade | MTree | DDOS MIB, se disponível | Descobrir por ID/nome estável; distinguir quota de ocupação física. |
| Performance | CPU | DDOS MIB | Gauge em percentual; confirmar janela da medição. |
| Performance | Rede | IF-MIB ou DDOS MIB | Preferir `ifHC*Octets`, calcular delta e separar interfaces de dados/gerência. |
| Performance | Throughput/streams | DDOS MIB | Confirmar unidade e se é instantâneo ou acumulado. |
| Performance | Disco/filesystem | DDOS MIB | Confirmar semântica; não chamar operação cumulativa de IOPS. |
| Proteção | Replicação | DDOS MIB | Estado, origem/destino, último sucesso, fila/lag se disponíveis. |
| Proteção | RAID/discos em reconstrução | DDOS MIB/traps | Manter componente, estado e progresso quando expostos. |
| Segurança | Versão | DDOS MIB | Coleta diária para inventário/correlação de CVEs por outra ferramenta. |
| Segurança | Criptografia/serviços | DDOS MIB ou API validada | Apenas estado documentado; ausência de OID não significa desabilitado. |
| Segurança | Certificado | Handshake HTTPS | Dias para expirar, cadeia e hostname. |

### Cuidados de capacidade

- Confirmar se a capacidade é decimal ou binária.
- Não misturar capacidade lógica pré-deduplicação com capacidade física.
- Guardar separadamente total, usado e disponível informados pelo DDOS.
- Se calcular percentual, usar `100 × usado / total` e tratar total igual a zero como inválido.
- Deduplication/compression ratio é indicador de eficiência, não capacidade livre.

### Cuidados de performance

- `Counter32/Counter64` exige delta; `Gauge` não.
- Se `sysUpTime` recuar, descartar o primeiro delta.
- Usar interfaces de dados e excluir loopback/gerência da agregação, salvo requisito explícito.
- Registrar o intervalo real entre amostras.

## 8. Traps

Configurar um receptor aprovado e capturar uma trap de teste. O mapeamento deve preservar:

- enterprise OID e trap OID;
- hostname/serial ou identificador do DD;
- ID/código do alerta;
- severidade;
- componente;
- mensagem;
- timestamp;
- indicação de recuperação, quando existir.

Uma trap não substitui a consulta da tabela de alertas atuais. A reconciliação periódica evita problema preso quando a recuperação não chega.

## 9. Quando usar API ou CLI

Somente abrir uma segunda fonte quando uma métrica obrigatória não existir na DDOS MIB da versão.

Processo:

1. Registrar a lacuna e a prova do walk/MIB.
2. Consultar o guia de API ou CLI da **mesma versão DDOS**.
3. Preferir API estruturada de leitura, se oficialmente disponível.
4. Criar conta exclusiva com privilégio mínimo.
5. Guardar resposta bruta e testar mudança de formato em upgrade.
6. Se só houver CLI, usar saída estruturada quando suportada; não parsear colunas alinhadas sem teste de versão/localidade.

Comandos como estado do filesystem, espaço, alertas e replicação podem servir para conferência humana, mas só viram fonte automatizada depois de validados no guia da release. Não executar comandos de configuração a partir da monitoração.

## 10. Frequência inicial

| Coleta | Frequência |
|---|---:|
| Uptime/estado/alertas | 1 a 2 minutos |
| Hardware | 3 a 5 minutos |
| Capacidade | 10 a 15 minutos |
| Performance | 1 a 5 minutos |
| Replicação | 5 minutos |
| Inventário/versão | 12 a 24 horas |
| Traps | contínuo |

## 11. Tratamento de falhas

- Timeout é falha do canal SNMP, não filesystem down.
- `noSuchObject` normalmente indica MIB/OID incompatível com a versão.
- `noSuchInstance` pode indicar recurso não configurado; validar no inventário.
- Valor `unknown` do equipamento deve permanecer `unknown`, não ser convertido em OK.
- Falha de uma interface de rede não deve tornar todas as interfaces indisponíveis.
- O objeto de replicação pode desaparecer quando a configuração é removida; tratar como fim de descoberta.

## 12. Evidências obrigatórias

- modelo, serial autorizado, DDOS e topologia HA/tier.
- DDOS MIB baixada do próprio sistema, com checksum.
- `ddos_mib_symbols.txt`, `ddos_mib_tree.txt` e walk sanitizado.
- `dd_ifx_walk.txt` e mapeamento das interfaces de dados.
- captura simultânea do DD System Manager para filesystem/capacidade/alertas.
- trap de teste decodificada.
- tabela de enumerações e unidades.
- lista de lacunas que exigiriam API/CLI.

## 13. Testes de aceitação

- [ ] SNMPv3 responde com conta somente leitura.
- [ ] DDOS MIB e MIB-II carregam sem erro.
- [ ] Total/usado/livre conferem com DD System Manager.
- [ ] Um alerta/trap de teste é recebido e decodificado.
- [ ] HA, tier ou replicação não configurados aparecem como não aplicáveis, não como falha.
- [ ] Reboot não gera pico artificial de throughput.
- [ ] Perda de SNMP é distinguida de filesystem parado.
- [ ] Nenhuma comunidade ou senha está nas evidências.

## 14. Referências oficiais

- [Dell Data Domain — gerenciamento de SNMP](https://www.dell.com/support/kbdoc/en-us/000204034/data-domain-managing-snmp)
- [DDOS 7.13 — gerenciamento SNMP](https://www.dell.com/support/manuals/en-us/dd-os-7.13/dd_p_ddos_7.13.1.30_ag/managing-snmp?guid=guid-7ffdceb8-effd-4213-8072-ee8fb45d06fc&lang=en-us)
- [DDOS — criação de usuário SNMPv3](https://www.dell.com/support/manuals/en-us/dd-os-7.13/dd_p_ddos_7.13.1.30_ag/creating-snmp-v3-users?guid=guid-b63d64d1-8527-478b-893c-1d043395d1e8&lang=en-us)
