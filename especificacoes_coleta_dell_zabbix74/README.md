# Especificações de coleta Dell para a equipe Zabbix 7.4

Versão do documento: 1.1  
Objetivo: entrega rápida de uma monitoração mínima, reproduzível e expansível.

## 1. Limite desta entrega

Este pacote descreve **como obter os dados nos equipamentos**. Ele não define itens, chaves, macros, expressões de trigger, severidades ou nomes de templates do Zabbix. Essas decisões pertencem à equipe que construirá os templates.

O resultado esperado de cada homologação é um contrato de coleta contendo:

- fonte oficial do dado;
- versão do produto e da interface;
- comando ou requisição de leitura;
- resposta bruta sanitizada;
- caminho do campo ou OID;
- tipo, unidade e semântica;
- identidade estável do objeto descoberto;
- tratamento de erro e de ausência de dados.

## 2. Critérios usados

| Critério | O que deve responder | Observação |
|---|---|---|
| Disponibilidade | O sistema, controladores, nós, portas e componentes essenciais estão operacionais? | Inclui saúde e eventos ativos. |
| Capacidade | Quanto existe, quanto está usado e quanto está livre? | Em switches, significa ocupação e utilização das portas, não capacidade de armazenamento. |
| Performance | Qual é a carga, vazão, IOPS, latência e taxa de erros? | Coletar contadores brutos quando a fonte não fornece taxas. |
| Proteção | Réplicas, backups, RAID, snapshots ou mecanismos equivalentes estão íntegros? | Marcar como `não aplicável` quando o produto não protege dados. |
| Segurança observável | Há versão, certificado, autenticação, configuração de criptografia ou evento de segurança que a interface exponha? | Não equivale a varredura de vulnerabilidade ou auditoria de conformidade. |

Uma métrica só entra no mínimo quando é confiável, tem unidade conhecida e conduz a uma ação operacional. Não se deve fabricar um valor para preencher um critério que não se aplica.

## 3. Decisão resumida por família

| Família | Fonte principal recomendada | Complemento | Complexidade inicial |
|---|---|---|---|
| Avamar | SNMPv3 com `AVAMAR-MCS-MIB` | Traps; REST para atividades detalhadas | Baixa no SNMP; média/alta no REST |
| Connectrix B-Series/C-Series | SNMPv3 com MIBs da plataforma | Traps/informs e syslog | Baixa/média |
| PowerProtect Data Domain | SNMPv3 com DDOS MIB e MIB-II | Traps; CLI/API somente para lacunas | Baixa/média |
| ECS | Flux API + Management REST API | Traps SNMPv3 | Alta |
| PowerScale/Isilon | OneFS REST API | Traps/eventos | Média |
| PowerEdge/iDRAC | Redfish | Telemetria Redfish opcional; SNMP legado | Baixa/média |
| PowerSwitch OS10 | SNMPv3 | Traps/informs e syslog; gNMI depois | Baixa |
| PowerVault ME4 | HTTPS CLI API com JSON | Traps SNMP | Média |
| Unity XT | Unisphere Management REST API | Traps; métricas de performance REST | Média |

## 4. Arquivos

1. [Avamar](01_avamar.md)
2. [Connectrix B-Series e C-Series](02_connectrix.md)
3. [PowerProtect Data Domain](03_powerprotect_data_domain.md)
4. [ECS](04_ecs.md)
5. [PowerScale / Isilon](05_powerscale_isilon.md)
6. [PowerEdge / iDRAC](06_poweredge_idrac.md)
7. [PowerSwitch OS10](07_powerswitch_os10.md)
8. [PowerVault ME4](08_powervault_me4.md)
9. [Unity XT](09_unity_xt.md)
10. [Comparação: coleta direta versus servidor normalizador](10_comparacao_direto_vs_normalizador.md)
11. [Checklist de entrega para a equipe Zabbix](CHECKLIST_ENTREGA.md)

## 5. Processo padrão de homologação

### Passo 1 — Inventariar antes de escolher endpoint ou OID

Registrar, por equipamento:

- fabricante e família;
- modelo exato;
- versão de firmware/SO;
- número de nós, controladores ou membros;
- licenças relevantes;
- recursos realmente configurados, como replicação, HA e CloudIQ;
- FQDN/IP de gerenciamento e site;
- fonte de horário/NTP.

### Passo 2 — Criar acesso exclusivo de leitura

Usar uma conta de serviço dedicada, com o menor privilégio que permita todos os `GET` ou consultas SNMP necessários. Não usar conta pessoal, `root` ou senha colocada no arquivo Markdown.

### Passo 3 — Validar rede e TLS

Registrar portas, origem autorizada e cadeia de certificados. Em produção, confiar na CA ou no certificado do equipamento. A opção `curl -k` aparece somente como diagnóstico temporário em ambiente isolado e nunca deve ser a configuração final.

### Passo 4 — Descobrir a interface instalada

Não copiar cegamente caminhos de outra versão. Primeiro consultar o catálogo da API, o `?describe`, o serviço Redfish ou a MIB baixada do próprio produto. Guardar essa descoberta como evidência.

### Passo 5 — Coletar amostras reais

Guardar no mínimo:

- uma resposta saudável;
- uma resposta com condição degradada real ou teste oficial;
- uma resposta vazia válida;
- um erro de autenticação;
- um erro de timeout/indisponibilidade;
- uma resposta paginada, quando houver.

Remover nomes de clientes, endereços sensíveis, tokens, cookies, seriais não autorizados e qualquer segredo antes de enviar à equipe Zabbix.

### Passo 6 — Fechar o contrato de cada métrica

Para cada campo, preencher:

| Campo do contrato | Exemplo |
|---|---|
| Nome funcional | Capacidade livre do pool |
| Critério | Capacidade |
| Escopo | Pool |
| Identificador estável | ID nativo do pool, não posição no array |
| Fonte | `GET .../pool/...` ou OID simbólico |
| Caminho de extração | caminho JSON ou nome do objeto MIB |
| Tipo | inteiro sem sinal |
| Unidade | bytes |
| Natureza | gauge, contador cumulativo, estado ou texto |
| Estado ausente | objeto removido, recurso não licenciado ou falha de coleta |
| Versões validadas | modelo, firmware e versão da API |
| Evidência | arquivo de resposta sanitizado |

### Passo 7 — Testar falhas sem alterar produção

Priorizar testes oficiais, retirada temporária de acesso em laboratório e eventos já existentes. Não desligar controladores, discos, portas ou replicações de produção para validar monitoração.

## 6. Regras que evitam falsos resultados

- Descobrir objetos por ID nativo; não usar a posição `0`, `1`, `2` de uma lista como identidade.
- Preservar valores brutos e unidades originais antes de qualquer conversão.
- Distinguir `0` válido de campo ausente, `null`, resposta vazia e erro HTTP/SNMP.
- Para contadores cumulativos, calcular delta por tempo e detectar reinicialização ou estouro de contador.
- Para APIs paginadas, continuar até o indicador oficial de fim; a primeira página não representa o inventário inteiro.
- Para clusters, coletar pelo endereço de gerenciamento recomendado e manter o ID do nó nos dados.
- Um HTTP `200` não prova que a coleta é válida: verificar tipo de conteúdo, estrutura, status da própria API e timestamp.
- Uma trap complementa polling; ela não substitui a reconciliação periódica do estado atual.
- Se a versão instalada não expõe uma métrica, registrar a lacuna. Não inferir capacidade, saúde ou proteção a partir de um campo sem documentação.

## 7. Cadência inicial sugerida

Estas frequências são orientação para homologação, não limites do template:

| Natureza | Frequência inicial |
|---|---:|
| Disponibilidade do endpoint | 1 minuto |
| Saúde consolidada e componentes | 2 a 5 minutos |
| Capacidade | 15 minutos |
| Performance agregada | 1 a 5 minutos |
| Inventário e versão | 1 a 24 horas |
| Replicação/backup em execução | 5 minutos |
| Eventos ativos | 1 a 5 minutos + trap |
| Certificado | 12 a 24 horas |

Antes de reduzir intervalos, medir tempo de resposta, tamanho do payload, concorrência e impacto no equipamento.

## 8. Definição de pronto

Uma família está pronta para a equipe de templates quando:

- todos os comandos de leitura foram executados no modelo e versão reais;
- as métricas mínimas foram marcadas como `disponível`, `não disponível` ou `não aplicável`;
- há amostras sanitizadas e documentação da versão;
- IDs e paginação foram entendidos;
- unidades e estados foram mapeados;
- timeout, autenticação inválida e fonte indisponível são distinguíveis;
- nenhuma credencial está em código, documentação ou payload;
- o responsável pelo equipamento aprovou frequência e método de acesso.

## 9. Nota sobre versões

Os caminhos e nomes apresentados nos arquivos são pontos de partida baseados na documentação oficial. A resposta do equipamento instalado é a fonte final da implementação. Cada documento mostra como descobrir e validar a versão para impedir que a equipe trate um exemplo de OneFS, Unity OE, ECS, DDOS, iDRAC, Fabric OS, NX-OS ou ME4 como universal.
