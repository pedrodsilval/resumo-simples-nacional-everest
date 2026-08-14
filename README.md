# Resumo Simples Nacional — Everest Contabilidade

## Objetivo

Ferramenta interna para a equipe da Everest Gestão Contábil e Empresarial transformar o
relatório de apuração do Simples Nacional (PDF gerado pelo sistema contábil) em um
resumo curto e formatado, pronto para ser repassado aos clientes.

## Contexto

- Todo mês a Everest precisa comunicar aos clientes optantes pelo Simples Nacional o
  resultado da apuração (quanto pagar e por quê).
- O relatório de origem é técnico, extenso (várias páginas com memória de cálculo) e não
  é adequado para envio direto ao cliente.
- Público final do resumo: o cliente PJ da Everest, que precisa entender rapidamente
  quanto vai pagar, sem precisar interpretar a memória de cálculo.

## Usuários

- **Equipe interna da Everest** (contadores/assistentes): fazem upload do PDF e geram o
  resumo para repassar ao cliente.
- **Cliente final**: não acessa a ferramenta nesta fase — recebe apenas o resumo pronto
  (por e-mail, WhatsApp etc., fora do escopo desta ferramenta).

## Entrada: relatório de origem

Baseado no exemplo de referência fornecido, o relatório de apuração do Simples Nacional
é um PDF de múltiplas páginas com esta estrutura:

1. **Apuração do Simples Nacional** (página principal)
   - Identificação: empresa, CNPJ, início de atividades, competência (mês/ano)
   - Receitas brutas: RPA regime de competência, RPA regime de caixa, RBT12 (receita
     acumulada 12 meses), faixa de enquadramento, RBA ano corrente e ano anterior
   - Valor da folha (12 meses) e Fator R (quando aplicável — define Anexo III vs V)
   - Detalhamento por **Anexo / Seção / Tabela** (a empresa pode ter receita enquadrada
     em mais de um anexo, ex.: III e IV): receita tributada, alíquota efetiva, valor do
     Simples Nacional por anexo
   - Partilha por tributo (IRPJ, CSLL, COFINS, PIS, INSS/CPP, ISS): situação, base de
     cálculo, alíquota, valor
   - Acréscimos, deduções, valores fixos de ICMS/ISS
   - **Total: Simples Nacional a recolher** (valor final do período)

2. **Memória de cálculo** (páginas seguintes)
   - Detalha a fórmula da alíquota efetiva por anexo — uso técnico/auditoria, não deve
     ir para o resumo do cliente

3. **Anexo — histórico de 12 meses**
   - Receita bruta acumulada mês a mês
   - Valor da folha e INSS/CPP mês a mês

4. **Alíquota efetiva do período seguinte**
   - Projeção da alíquota para a próxima competência — útil para avisar o cliente sobre
     tendência de aumento/redução da carga tributária

> Observação: o número de anexos e o conteúdo variam conforme a atividade de cada
> cliente (Comércio, Indústria, Serviços — Anexos I a V). O parser não pode assumir que
> só existe um anexo, nem que a estrutura deste exemplo é fixa.

## Dados a extrair (MVP)

Campos essenciais para o resumo do cliente:

- Empresa, CNPJ, competência (mês/ano)
- Receita bruta do período (competência e/ou caixa)
- Receita bruta acumulada 12 meses (RBT12) e faixa de enquadramento
- Fator R (quando aplicável)
- Alíquota efetiva por anexo
- **Valor total do Simples Nacional a recolher** (destaque principal do resumo)
- Valor total por tributo (IRPJ, CSLL, COFINS, PIS, INSS/CPP, ISS) — somado entre
  anexos, para manter o resumo simples

Fica de fora do resumo do cliente (uso interno apenas):

- Memória de cálculo detalhada (fórmulas de alíquota efetiva)
- Histórico mês a mês de receita e folha (pode virar gráfico opcional no futuro)

## Saída: resumo para o cliente

Documento PDF/Word, curto (idealmente 1 página), com identidade visual da Everest,
contendo:

- Cabeçalho: nome do cliente, CNPJ, competência
- Destaque: valor total do Simples Nacional a recolher
- Resumo da receita do mês e acumulada 12 meses / faixa de enquadramento
- Tabela simples com valor por tributo
- Rodapé: contato da Everest / observações

## Stack técnica sugerida

Como é uma ferramenta de uso interno, com escopo bem definido (upload → extração →
geração de arquivo), a prioridade é simplicidade e velocidade de desenvolvimento, não
escalabilidade:

- **Python** — linguagem com melhor suporte para extração de PDF e geração de
  documentos, e fácil de manter/ajustar conforme o parser precisar evoluir
- **pdfplumber** — extração de texto e tabelas do PDF. O relatório de exemplo é PDF
  nativo (texto selecionável, não digitalizado/escaneado), o que torna a extração
  confiável sem precisar de OCR
- **Streamlit** — framework para montar a interface web (upload do PDF, prévia dos
  dados extraídos, botão de download do resumo) com pouquíssimo código, sem precisar
  separar front-end e back-end. Ideal para uma ferramenta interna de equipe pequena
- **Jinja2 + xhtml2pdf** — geração do resumo final: um template HTML/CSS com a
  identidade da Everest, convertido em PDF. Testamos o WeasyPrint primeiro (opção mais
  comum para HTML→PDF em Python), mas ele depende de bibliotecas nativas do GTK que não
  vêm instaladas no Windows; o xhtml2pdf é puro Python e funciona sem instalação extra

Essa combinação roda localmente (ex.: um `.exe`/atalho ou `streamlit run`) sem
depender de infraestrutura externa, o que facilita começar. Se no futuro for necessário
acesso remoto pela equipe ou pelos clientes, dá para hospedar o mesmo app Streamlit em
um servidor interno ou serviço de nuvem, sem reescrever a lógica de extração/geração.

## Status do protótipo

Protótipo funcional implementado e validado com 3 relatórios reais fornecidos pela
Everest (1 e 2 anexos, com e sem Fator R, ISS no próprio município e em outro
município):

- [`src/parser.py`](src/parser.py) — extrai empresa, CNPJ, competência, receitas,
  Fator R, alíquota efetiva por anexo, partilha por tributo e o total a recolher.
  Também lê a página "Alíquota efetiva do período seguinte" (quando presente no PDF)
  para mostrar a tendência da alíquota do próximo mês.
- [`src/generate.py`](src/generate.py) + [`src/template.html`](src/template.html) —
  monta o resumo em PDF (1 página), com destaque para o valor a recolher e a alíquota
  efetiva do período (conforme pedido: ênfase nas alíquotas). Layout segue o
  `Everest_Contabilidade_Manual_da_Marca.md` (v1.1, encontrado em
  `Documents/Projeto_Marketing_Grupo_Everest/Arquivos_atualizados/`): paleta oficial
  (Royal Blue `#1A4FAD`, Midnight Blue `#0D1B3E`, Dourado Solar `#D4AF37`) e tipografia
  oficial (Satoshi para títulos, Inter para corpo — fontes baixadas do Fontshare/Google
  Fonts e embutidas em [`assets/fonts/`](assets/fonts/)). A logo veio do arquivo oficial
  em alta resolução fornecido pelo usuário (substituiu uma primeira versão extraída de
  um PDF assinado, que tinha artefatos de compressão JPEG). O símbolo (montanha) e o
  wordmark ("Everest" + tagline) estavam empilhados numa única imagem; como o cabeçalho
  do resumo é horizontal, separei os dois em
  [`assets/everest_symbol.png`](assets/everest_symbol.png) e
  [`assets/everest_wordmark.png`](assets/everest_wordmark.png) e depois montei
  [`assets/everest_logo_header.png`](assets/everest_logo_header.png) — uma única imagem
  já com o ícone alinhado ao centro óptico do texto "Everest" (o xhtml2pdf não alinha
  bem conteúdo de células de tabela distintas, então compor tudo em uma imagem só evita
  esse problema).
- [`app.py`](app.py) — interface Streamlit: upload do PDF, prévia dos dados extraídos
  na tela e botão de download do resumo em PDF.

**App hospedado:** https://everest-simples-nacional.streamlit.app — qualquer pessoa com
o link acessa, sem login. Deploy automático via Streamlit Community Cloud a partir do
repositório [`pedrodsilval/resumo-simples-nacional-everest`](https://github.com/pedrodsilval/resumo-simples-nacional-everest)
(público — sem dados de cliente nele, ver `.gitignore`); todo `git push` na branch
`master` atualiza o app no ar. Repositório precisou ser público porque, com repositório
privado, o Streamlit Community Cloud exige login do visitante para ver o app — não tem
opção gratuita de "link público, código privado".

**Como rodar localmente (alternativa):**

```bash
pip install -r requirements.txt
streamlit run app.py
```

Depois é só abrir `http://localhost:8501`, subir um PDF de apuração do Simples
Nacional e baixar o resumo gerado.

**Hardening feito para rodar em produção (04/08/2026):** como o app agora fica no ar
recebendo uso repetido de várias pessoas, e não só uso local pontual, revisei e corrigi:
- `app.py` só capturava `ValueError` ao ler o PDF enviado — um PDF corrompido, com
  senha, ou que não é PDF de verdade gerava uma exceção não tratada (stack trace cru na
  tela). Agora qualquer erro de leitura cai numa mensagem amigável.
- O contorno do bug do Windows em `generate.py` (`delete=False` nos temporários do
  xhtml2pdf) nunca apagava os arquivos depois. Rodando local isso era irrelevante; num
  servidor contínuo, cada PDF gerado deixava ~6 arquivos temporários para trás para
  sempre. Agora limpa após cada geração.

**Correção: empresas com matriz e filial (10/08/2026):** a equipe reportou (relatório
real de um cliente) que o site não reconhecia o PDF de uma empresa com mais de um
estabelecimento (matriz + filial, cada um com seu CNPJ, apurados juntos no mesmo
relatório). Duas causas, corrigidas:
- Quando a apuração tem muitos blocos de Anexo (comum com mais de um estabelecimento),
  o rodapé com o total ("Simples Nacional a recolher") transborda para uma página
  seguinte, que o parser não olhava — só lia a primeira página da apuração. Agora junta
  todas as páginas antes de extrair os dados.
- Com mais de um estabelecimento, o mesmo Anexo pode aparecer repetido na tabela do
  resumo com valores diferentes e nenhuma explicação (ex.: "Anexo III" três vezes). Agora
  cada linha agora mostra o CNPJ do estabelecimento (quando há mais de um) e o texto da
  "Tabela" do próprio relatório como diferencial, sempre que o nome do anexo sozinho não
  for suficiente para distinguir as linhas.

**Observação sobre a pasta `samples/`:** contém os relatórios reais usados para validar
o parser. Como trazem dados sigilosos de clientes (CNPJ, receita, folha), não devem ser
compartilhados fora desta máquina/projeto.

**Limitações conhecidas do protótipo:**

- O parser foi validado com relatórios reais apenas do Anexo III e do Anexo IV. Os
  Anexos I, II e V (Comércio, Indústria e a variação de Serviços do Anexo V) ainda não
  foram testados com um exemplo real — testei o caminho do código com um bloco
  sintético simulando Anexo I + ICMS (ver auditoria abaixo) e funcionou, mas vale
  confirmar com um PDF real assim que aparecer um.
- O texto extraído do PDF perde acentuação em trechos longos (nome de empresa e
  números não são afetados). Por isso o resumo usa nomes oficiais fixos para os
  anexos ("Anexo III - Locação de Bens Móveis e Prestação de Serviços" etc.) em vez do
  texto cru extraído do PDF.

**Auditoria de robustez (04/08/2026):** revisão pedida explicitamente para achar
valores hardcoded que só funcionassem por coincidência com os 3 exemplos testados.
Achei e corrigi dois pontos reais:
- A tabela "Valor por Tributo" filtrava por uma lista fixa de 6 tributos
  (IRPJ/CSLL/COFINS/PIS/INSS-CPP/ISS); qualquer tributo fora dela — como ICMS ou IPI,
  que aparecem nos Anexos I e II (Comércio/Indústria) no lugar do ISS — era descartado
  em silêncio, sem erro. Agora qualquer tributo encontrado no relatório aparece na
  tabela (os conhecidos numa ordem preferencial, o resto depois, na ordem em que
  apareceu).
- A extração dos tributos por anexo dependia de "Situação" ter só valores de uma
  palavra (só tratava "Não incidência" como exceção); um valor de duas palavras não
  previsto (ex.: "Substituição Tributária") faria a extração inteira daquele anexo
  falhar silenciosamente. Agora a contagem de tributos vem dos nomes na linha
  "Partilha" (sempre tokens únicos) e dos valores numéricos (Base/Alíquota/Valor,
  extraídos por regex numérico em vez de `split()`); se a "Situação" não bater a
  contagem esperada, cai num valor padrão em vez de derrubar a extração — Situação não
  é usada em nenhum cálculo nem exibida no resumo.
- Sem autenticação — não é um problema enquanto o uso for local/interno, mas passa a
  ser relevante se um dia isso rodar em rede compartilhada.

## Fluxo do usuário (MVP)

1. Colaborador da Everest acessa a aplicação web interna
2. Faz upload do PDF do relatório de apuração (um cliente/competência por vez)
3. Sistema extrai os dados relevantes do PDF
4. Sistema gera o resumo formatado (PDF/Word)
5. Colaborador revisa e baixa o arquivo para enviar ao cliente

## Escopo do MVP

- Upload de 1 PDF por vez
- Extração automática dos campos listados acima
- Geração de 1 resumo por competência/cliente, que passa por revisão humana do
  colaborador da Everest antes de ser enviado ao cliente (o app não envia nada
  diretamente)
- Interface simples, **uso interno da Everest apenas** — hospedada (ver seção "App
  hospedado" acima), mas sem senha; pensada para a equipe usar, não para divulgação
  ampla

## Fora de escopo (por ora)

- Envio automático do resumo ao cliente (e-mail/WhatsApp)
- Acesso direto do cliente à ferramenta
- Suporte a outros relatórios (declaração anual/DEFIS) — considerar depois
- Dashboard ou histórico consolidado por cliente
- Autenticação/senha no app — avaliar se vira necessário mais pra frente

## Riscos e pontos de atenção

- O layout do PDF pode variar entre versões do sistema contábil — a extração precisa
  ser validada com mais exemplos (diferentes anexos, com e sem Fator R, mais de um
  anexo simultâneo, etc.) antes de confiar nela sem revisão
- Nomes de anexo/seção/tabela mudam conforme a atividade do cliente — o parser deve
  lidar com isso de forma genérica, não fixado no exemplo atual
- Conferência humana continua necessária antes do envio: o resumo é um apoio à equipe,
  não substitui a revisão do contador responsável
- Dados dos relatórios são sigilosos (receita, CNPJ, folha de pagamento) — tratar como
  informação sensível de cliente em qualquer ambiente/armazenamento usado

## Próximos passos

1. Validar o resumo gerado com o time da Everest (conteúdo, tom, o que falta/sobra)
2. Testar o parser com um exemplo real de Anexo I, II e V, se disponível
3. Avaliar se vale adicionar o histórico de 12 meses (receita/folha) como gráfico
   opcional no resumo
