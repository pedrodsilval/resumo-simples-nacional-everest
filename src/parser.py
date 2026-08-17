"""
Parser do relatorio de apuracao do Simples Nacional (PDF gerado pelo sistema
contabil da Everest).

O texto extraido do PDF perde acentos (fonte sem ToUnicode CMap completo:
"Emissao" vira "Emiss?o"), tanto via pdfplumber quanto via PyMuPDF. Por isso
os regexes abaixo usam "." no lugar de vogais acentuadas dos rotulos fixos do
relatorio -- isso casa tanto com o acento correto quanto com o caractere
substituto. Os *valores* extraidos (empresa, datas, numeros) nao dependem
disso.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pdfplumber

# Valores de "Situação" com mais de uma palavra (ex.: "Não incidência",
# "Substituição Tributária") quebram o split() por espaço nas linhas da
# partilha. Protegemos qualquer ocorrência trocando o espaço interno por um
# caractere que nunca aparece no relatório antes de separar por espaço, e
# desfazemos a troca depois -- assim funciona para qualquer frase de duas
# palavras conhecida, sem precisar mapear cada uma manualmente de volta.
_SITUACAO_MULTIPALAVRA_RE = re.compile(
    r"N.o\s+incid.ncia|Substitui..o\s+Tribut.ria|Retido\s+na\s+Fonte",
    re.IGNORECASE,
)
_SEPARADOR_PROTEGIDO = "␟"  # caractere de controle, não aparece em texto normal

# Nomes oficiais dos anexos do Simples Nacional (texto fixo, correto e sem
# acentos corrompidos) -- usados no resumo do cliente em vez do texto
# extraído do PDF, que perde acentuação em trechos longos (só o rótulo do
# anexo, não os valores). Mantemos o texto bruto no campo `descricao_completa`
# para referência interna.
ANEXO_NOME_CANONICO = {
    "I": "Anexo I - Comércio",
    "II": "Anexo II - Indústria",
    "III": "Anexo III - Locação de Bens Móveis e Prestação de Serviços",
    "IV": "Anexo IV - Prestação de Serviços",
    "V": "Anexo V - Prestação de Serviços",
}

_ANEXO_NUMERO_RE = re.compile(r"Anexo\s+(I{1,3}|IV|V)\b")


def _anexo_nome_canonico(nome_bruto: str) -> str:
    m = _ANEXO_NUMERO_RE.search(nome_bruto)
    if not m:
        return nome_bruto
    return ANEXO_NOME_CANONICO.get(m.group(1), nome_bruto)


def parse_brl(value: str) -> float:
    """Converte '1.234,56' -> 1234.56. Converte '10,50' (alíquota) -> 10.50."""
    value = value.strip()
    if not value:
        return 0.0
    value = value.replace(".", "").replace(",", ".")
    return float(value)


@dataclass
class Tributo:
    nome: str
    situacao: str
    base_calculo: float
    aliquota: float
    valor: float


@dataclass
class Anexo:
    nome: str
    descricao_completa: str
    secao: str
    tabela: str
    estabelecimento_cnpj: str
    receita_tributada: float
    aliquota_efetiva: float
    simples_nacional_total: float
    tributos: list[Tributo] = field(default_factory=list)
    municipios: list[tuple[str, str, float]] = field(default_factory=list)
    aliquota_proximo_periodo: float | None = None


@dataclass
class ApuracaoSimplesNacional:
    empresa: str
    cnpj: str
    periodo: str
    inicio_atividades: str
    rpa_competencia: float
    rpa_caixa: float | None
    rbt12: float
    faixa_enquadramento_interno: str
    faixa_enquadramento_externo: str
    rba_corrente: float
    rba_anterior: float
    folha_12m: float
    fator_r: float
    anexos: list[Anexo]
    outros_acrescimos: float
    outras_deducoes: float
    valor_diferido: float
    valor_fixo_icms: float
    valor_fixo_iss: float
    total_a_recolher: float
    rbt12_proximo_periodo: float | None = None

    @property
    def receita_tributada_total(self) -> float:
        return sum(a.receita_tributada for a in self.anexos)

    @property
    def aliquota_media_efetiva(self) -> float:
        """Alíquota efetiva combinada do período: total a recolher / receita tributada total."""
        base = self.receita_tributada_total
        if base == 0:
            return 0.0
        return (self.total_a_recolher / base) * 100


def _split_pages_by_tipo(pdf_path: str) -> dict[str, list[str]]:
    """Agrupa o texto de cada página do PDF por tipo de seção do relatório."""
    grupos: dict[str, list[str]] = {
        "apuracao": [],
        "periodo_seguinte": [],
        "memoria": [],
        "anexo_historico": [],
        "outro": [],
    }
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if re.search(r"AL.QUOTA EFETIVA DO PER.ODO SEGUINTE", text, re.IGNORECASE):
                grupos["periodo_seguinte"].append(text)
            elif re.search(r"MEM.RIA DE C.LCULO SIMPLES NACIONAL", text, re.IGNORECASE):
                grupos["memoria"].append(text)
            elif re.search(r"SIMPLES NACIONAL - ANEXO", text, re.IGNORECASE):
                grupos["anexo_historico"].append(text)
            elif re.search(r"^SIMPLES NACIONAL\s*$", text, re.IGNORECASE | re.MULTILINE):
                grupos["apuracao"].append(text)
            else:
                grupos["outro"].append(text)
    return grupos


_ESTABELECIMENTO_RE = re.compile(r"Estabelecimento:\s*\d+\s+.+?CNPJ:\s*([\d./-]+)")


def _parse_anexo_blocks(text: str, with_proximo: bool = False) -> list[Anexo]:
    """Extrai todos os blocos 'Anexo: ... Tabela: ...' de uma página de
    apuração, agrupados por 'Estabelecimento:' -- empresas com matriz e
    filial (ou mais de um estabelecimento) repetem o bloco 'Estabelecimento:
    NN ... CNPJ: X' antes dos anexos de cada um. Sem separar por
    estabelecimento primeiro, dois anexos idênticos de estabelecimentos
    diferentes ficam indistinguíveis no resumo.
    """
    anexos: list[Anexo] = []
    pedacos_estabelecimento = re.split(r"(?=Estabelecimento:\s*\d+\s)", text)
    for pedaco in pedacos_estabelecimento:
        m_estab = _ESTABELECIMENTO_RE.search(pedaco)
        cnpj_estab = m_estab.group(1).strip() if m_estab else ""
        anexos.extend(_parse_anexo_blocks_do_estabelecimento(pedaco, cnpj_estab, with_proximo))
    return anexos


def _parse_anexo_blocks_do_estabelecimento(
    text: str, cnpj_estab: str, with_proximo: bool = False
) -> list[Anexo]:
    """Extrai os blocos 'Anexo: ... Tabela: ...' dentro do texto de um único
    estabelecimento (ver `_parse_anexo_blocks`)."""
    blocos_raw = re.split(r"(?=Anexo:\s)", text)
    anexos: list[Anexo] = []

    for bloco in blocos_raw:
        if not bloco.startswith("Anexo:"):
            continue

        m_nome = re.match(r"Anexo:\s*(.+)", bloco)
        nome = m_nome.group(1).strip() if m_nome else ""

        m_secao = re.search(r"Se..o:\s*(.+?)\nTabela:", bloco, re.DOTALL)
        secao = re.sub(r"\s+", " ", m_secao.group(1)).strip() if m_secao else ""

        m_tabela = re.search(
            r"Tabela:\s*(.+?)(?:\nReceita Tributada Total:|\nC.lculo da al.quota efetiva)",
            bloco,
            re.DOTALL,
        )
        tabela = re.sub(r"\s+", " ", m_tabela.group(1)).strip() if m_tabela else ""

        if with_proximo:
            # Página "Alíquota efetiva do período seguinte": não existe mais
            # "Receita Tributada Total: X Alíquota: Y" (não há receita ainda
            # apurada para o período seguinte). O rótulo "Alíquota efetiva: X%"
            # que aparece antes da repartição é uma taxa federal intermediária
            # -- quando o ISS tem "não incidência" (ex.: locação de bens
            # móveis) a repartição não soma 100% e essa taxa NÃO bate com a
            # taxa final aplicada à receita (a que aparece na página 1). A
            # taxa comparável é a soma da linha "Alíquota efetiva por
            # imposto", que é como a página 1 calcula a coluna "Alíquota".
            m_por_imposto = re.search(r"Al.quota efetiva por imposto:\s*(.+)", bloco)
            aliquota_proximo = None
            if m_por_imposto:
                valores = m_por_imposto.group(1).split()
                try:
                    aliquota_proximo = sum(parse_brl(v) for v in valores)
                except ValueError:
                    aliquota_proximo = None
            anexos.append(
                Anexo(
                    nome=_anexo_nome_canonico(nome),
                    descricao_completa=nome,
                    secao=secao,
                    tabela=tabela,
                    estabelecimento_cnpj=cnpj_estab,
                    receita_tributada=0.0,
                    aliquota_efetiva=0.0,
                    simples_nacional_total=0.0,
                    aliquota_proximo_periodo=aliquota_proximo,
                )
            )
            continue

        m_totais = re.search(
            r"Receita Tributada Total:\s*([\d.,]+)\s+Al.quota:\s*([\d.,]+)\s+"
            r"Simples Nacional Total:\s*([\d.,]+)",
            bloco,
        )
        if not m_totais:
            continue
        receita_tributada = parse_brl(m_totais.group(1))
        aliquota_efetiva = parse_brl(m_totais.group(2))
        simples_nacional_total = parse_brl(m_totais.group(3))

        municipios: list[tuple[str, str, float]] = []
        m_mun_bloco = re.search(
            r"Munic.pio\s+Estado\s+Valor\n(.+?)\nPartilha:", bloco, re.DOTALL
        )
        if m_mun_bloco:
            for linha in m_mun_bloco.group(1).splitlines():
                linha = linha.strip()
                if not linha:
                    continue
                m_linha = re.match(r"(.+?)\s{2,}([\d.,]+)\s*$", linha)
                if not m_linha:
                    # fallback: último token é o valor, penúltimo "bloco" é o estado
                    partes = linha.rsplit(None, 2)
                    if len(partes) == 3:
                        municipios.append((partes[0], partes[1], parse_brl(partes[2])))
                    continue
                nome_valor = m_linha.group(1).strip()
                valor = parse_brl(m_linha.group(2))
                partes_nome = nome_valor.rsplit(None, 1)
                if len(partes_nome) == 2:
                    municipios.append((partes_nome[0], partes_nome[1], valor))

        tributos: list[Tributo] = []
        m_partilha = re.search(
            r"Partilha:\s*(.+)\nSitua..o:\s*(.+)\nBase de C.lculo:\s*(.+)\n"
            r"Al.quota:\s*(.+)\nValor:\s*(.+)",
            bloco,
        )
        if m_partilha:
            # Os nomes de tributo (ex.: IRPJ, ICMS, INSS/CPP) são sempre um
            # token sem espaço -- é a lista mais confiável para descobrir
            # quantos tributos existem neste anexo (varia por anexo: I/II
            # têm ICMS/IPI, III/IV/V têm ISS, nenhum é fixo).
            nomes = m_partilha.group(1).split()
            n = len(nomes)

            # Base/Alíquota/Valor são sempre números "limpos"; extrair via
            # regex numérico é mais robusto que split() a espaçamento
            # irregular no PDF de origem.
            bases = re.findall(r"[\d.,]+", m_partilha.group(3))
            aliquotas = re.findall(r"[\d.,]+", m_partilha.group(4))
            valores = re.findall(r"[\d.,]+", m_partilha.group(5))

            def protege(m: re.Match) -> str:
                return m.group(0).replace(" ", _SEPARADOR_PROTEGIDO)

            situacoes_raw = _SITUACAO_MULTIPALAVRA_RE.sub(protege, m_partilha.group(2))
            situacoes = situacoes_raw.split()
            if len(situacoes) != n:
                # Situação com frase de 2+ palavras que não reconhecemos --
                # não é usada em nenhum cálculo nem exibida no resumo, então
                # não vale travar a extração dos valores por causa dela.
                situacoes = ["Tributado"] * n

            if n == len(bases) == len(aliquotas) == len(valores):
                for i in range(n):
                    situacao = situacoes[i].replace(_SEPARADOR_PROTEGIDO, " ")
                    tributos.append(
                        Tributo(
                            nome=nomes[i],
                            situacao=situacao,
                            base_calculo=parse_brl(bases[i]),
                            aliquota=parse_brl(aliquotas[i]),
                            valor=parse_brl(valores[i]),
                        )
                    )

        anexos.append(
            Anexo(
                nome=_anexo_nome_canonico(nome),
                descricao_completa=nome,
                secao=secao,
                tabela=tabela,
                estabelecimento_cnpj=cnpj_estab,
                receita_tributada=receita_tributada,
                aliquota_efetiva=aliquota_efetiva,
                simples_nacional_total=simples_nacional_total,
                tributos=tributos,
                municipios=municipios,
            )
        )

    return anexos


def _extrair_cabecalho_memoria(texto_memoria: str) -> tuple[str | None, str | None, str | None]:
    """Extrai empresa/CNPJ/período do cabeçalho da página 'Memória de Cálculo'.

    Usado como fallback: quando o nome da empresa é muito longo, ele se
    sobrepõe fisicamente ao rótulo "Página:" no cabeçalho da página de
    apuração, e o pdfplumber intercala os caracteres dos dois textos
    sobrepostos (ex.: "TECNOLOGPI�Ag iLnTaD:A 0001"), tornando o valor
    irrecuperável ali. O cabeçalho da página de memória de cálculo tem o
    mesmo nome da empresa mas não sofre essa sobreposição.
    """
    m_empresa = re.search(r"^(.+?)\s+P.gina:", texto_memoria)
    m_cnpj = re.search(r"CNPJ:\s*([\d./-]+)\s+Emiss.o:", texto_memoria)
    m_periodo = re.search(r"Compet.ncia:\s*(\d{2}/\d{4})", texto_memoria)
    return (
        m_empresa.group(1).strip() if m_empresa else None,
        m_cnpj.group(1).strip() if m_cnpj else None,
        m_periodo.group(1).strip() if m_periodo else None,
    )


def _parse_apuracao_page(text: str, texto_memoria: str = "") -> ApuracaoSimplesNacional:
    m_empresa = re.search(r"Empresa:\s*(.+?)\s+P.gina:", text)
    m_cnpj = re.search(r"CNPJ:\s*([\d./-]+)\s+Emiss.o:", text)
    m_inicio = re.search(r"In.cio das atividades:\s*(\d{2}/\d{2}/\d{4})", text)
    m_periodo = re.search(r"\nPer.odo:\s*(\d{2}/\d{4})", text)

    empresa_fallback = cnpj_fallback = periodo_fallback = None
    if texto_memoria and not (m_empresa and m_cnpj and m_periodo):
        empresa_fallback, cnpj_fallback, periodo_fallback = _extrair_cabecalho_memoria(
            texto_memoria
        )

    m_rpa_comp = re.search(
        r"Regime de Compet.ncia\s+([\d.,]+)\s+[\d.,]+\s+([\d.,]+)", text
    )
    m_rpa_caixa = re.search(r"Regime de Caixa\s+([\d.,]+)\s+[\d.,]+\s+([\d.,]+)", text)
    m_rbt12 = re.search(r"\(RBT12\)\s+([\d.,]+)\s+[\d.,]+\s+([\d.,]+)", text)
    m_faixa = re.search(
        r"Faixa de Enquadramento:\s*([\d.,]+ a [\d.,]+)\s+([\d.,]+ a [\d.,]+)", text
    )
    m_rba_corrente = re.search(r"corrente \(RBA\)\s+([\d.,]+)\s+[\d.,]+\s+([\d.,]+)", text)
    m_rba_anterior = re.search(r"anterior \(RBA\)\s+([\d.,]+)\s+[\d.,]+\s+([\d.,]+)", text)
    m_folha = re.search(r"Valor da Folha nos .ltimos 12 meses:\s*([\d.,]+)", text)
    m_fator_r = re.search(r"Fator r:\s*([\d.,]+)", text)

    m_acrescimos = re.search(r"Outros Acr.scimos:\s*([\d.,]+)", text)
    m_deducoes = re.search(r"Outras Dedu..es:\s*([\d.,]+)", text)
    m_diferido = re.search(r"Valor Diferido:\s*([\d.,]+)", text)
    m_icms = re.search(r"Valor Fixo ICMS:\s*([\d.,]+)", text)
    m_iss = re.search(r"Valor Fixo ISS:\s*([\d.,]+)", text)
    m_total = re.search(r"Simples Nacional a recolher:\s*([\d.,]+)", text)

    empresa = m_empresa.group(1).strip() if m_empresa else empresa_fallback
    cnpj = m_cnpj.group(1).strip() if m_cnpj else cnpj_fallback
    periodo = m_periodo.group(1).strip() if m_periodo else periodo_fallback

    if not (empresa and cnpj and periodo and m_total):
        raise ValueError(
            "Não foi possível identificar os campos básicos (empresa/CNPJ/período/total) "
            "nesta página. O layout pode ser diferente do esperado."
        )

    anexos = _parse_anexo_blocks(text, with_proximo=False)

    return ApuracaoSimplesNacional(
        empresa=empresa,
        cnpj=cnpj,
        periodo=periodo,
        inicio_atividades=m_inicio.group(1).strip() if m_inicio else "",
        rpa_competencia=parse_brl(m_rpa_comp.group(2)) if m_rpa_comp else 0.0,
        rpa_caixa=parse_brl(m_rpa_caixa.group(2)) if m_rpa_caixa else None,
        rbt12=parse_brl(m_rbt12.group(2)) if m_rbt12 else 0.0,
        faixa_enquadramento_interno=m_faixa.group(1).strip() if m_faixa else "",
        faixa_enquadramento_externo=m_faixa.group(2).strip() if m_faixa else "",
        rba_corrente=parse_brl(m_rba_corrente.group(2)) if m_rba_corrente else 0.0,
        rba_anterior=parse_brl(m_rba_anterior.group(2)) if m_rba_anterior else 0.0,
        folha_12m=parse_brl(m_folha.group(1)) if m_folha else 0.0,
        fator_r=parse_brl(m_fator_r.group(1)) if m_fator_r else 0.0,
        anexos=anexos,
        outros_acrescimos=parse_brl(m_acrescimos.group(1)) if m_acrescimos else 0.0,
        outras_deducoes=parse_brl(m_deducoes.group(1)) if m_deducoes else 0.0,
        valor_diferido=parse_brl(m_diferido.group(1)) if m_diferido else 0.0,
        valor_fixo_icms=parse_brl(m_icms.group(1)) if m_icms else 0.0,
        valor_fixo_iss=parse_brl(m_iss.group(1)) if m_iss else 0.0,
        total_a_recolher=parse_brl(m_total.group(1)),
    )


def _aplicar_periodo_seguinte(apuracao: ApuracaoSimplesNacional, textos: list[str]) -> None:
    """Preenche a alíquota efetiva do período seguinte, quando o relatório traz essa página."""
    if not textos:
        return
    texto = "\n".join(textos)

    m_rbt12 = re.search(r"\(RBT12\)\s+([\d.,]+)\s+[\d.,]+\s+([\d.,]+)", texto)
    if m_rbt12:
        apuracao.rbt12_proximo_periodo = parse_brl(m_rbt12.group(2))

    anexos_proximo_bruto = _parse_anexo_blocks(texto, with_proximo=True)
    # O relatório repete o bloco de um anexo quando ele ocupa mais de uma
    # página (ex.: página 2/2 reimprime o último anexo da página 1/2) --
    # deduplicamos por (nome, tabela) mantendo a primeira ocorrência.
    vistos: set[tuple[str, str, str]] = set()
    anexos_proximo: list[Anexo] = []
    for a in anexos_proximo_bruto:
        chave = (a.estabelecimento_cnpj, a.nome, a.tabela)
        if chave in vistos:
            continue
        vistos.add(chave)
        anexos_proximo.append(a)

    # Casa por posição: mesma ordem de anexos costuma se repetir de um período
    # para o outro. Se a contagem não bater, não arriscamos casar errado.
    if len(anexos_proximo) == len(apuracao.anexos):
        for atual, proximo in zip(apuracao.anexos, anexos_proximo):
            atual.aliquota_proximo_periodo = proximo.aliquota_proximo_periodo


def parse_relatorio(pdf_path: str) -> ApuracaoSimplesNacional:
    """Ponto de entrada: recebe o caminho do PDF de apuração e devolve os dados extraídos."""
    grupos = _split_pages_by_tipo(pdf_path)

    if not grupos["apuracao"]:
        raise ValueError(
            "Não encontrei a página de apuração ('SIMPLES NACIONAL') neste PDF. "
            "Confirme se é o relatório de apuração do Simples Nacional."
        )

    # Empresas com mais de um estabelecimento (matriz + filial) ou vários
    # anexos podem ter a apuração espalhada por mais de uma página -- os
    # blocos de Anexo ficam nas primeiras páginas e o rodapé (Outros
    # Acréscimos/Deduções, Simples Nacional a recolher) só cabe na última.
    # Juntamos todas as páginas de apuração antes de parsear.
    texto_apuracao = "\n".join(grupos["apuracao"])
    texto_memoria = "\n".join(grupos["memoria"])
    apuracao = _parse_apuracao_page(texto_apuracao, texto_memoria)
    _aplicar_periodo_seguinte(apuracao, grupos["periodo_seguinte"])
    return apuracao
