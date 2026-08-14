"""Gera o resumo em PDF (identidade Everest) a partir dos dados extraídos do relatório."""

from __future__ import annotations

import base64
import io
import tempfile
from collections import Counter
from pathlib import Path

import xhtml2pdf.files as _x2p_files
from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa

from formatting import fmt_brl, fmt_pct, fmt_periodo_extenso
from parser import ApuracaoSimplesNacional

_SRC_DIR = Path(__file__).parent
_ASSETS_DIR = _SRC_DIR.parent / "assets"
_LOGO_HEADER_PATH = _ASSETS_DIR / "everest_logo_header.png"
_FONTS_DIR = _ASSETS_DIR / "fonts"

# Ordem preferencial de exibição para os tributos mais comuns (Anexos III/IV/V
# -- prestação de serviços). Não é uma lista fechada: Anexos I e II (Comércio
# e Indústria) usam ICMS/IPI em vez de ISS, e qualquer tributo que apareça no
# relatório mas não esteja nesta lista ainda é exibido -- só entra depois dos
# conhecidos, na ordem em que foi encontrado. Ver `_consolidar_tributos`.
_ORDEM_TRIBUTOS_PREFERENCIAL = ["IRPJ", "CSLL", "COFINS", "PIS", "INSS/CPP", "ICMS", "IPI", "ISS"]


def _patch_xhtml2pdf_windows_tempfile_bug() -> None:
    """xhtml2pdf carrega cada @font-face via um NamedTemporaryFile que mantém
    aberto e tenta reabrir pelo nome em seguida (xhtml2pdf/files.py,
    BaseFile.get_named_tmp_file). No Windows isso falha (TTFError: Can't open
    file ...) porque o Windows não permite reabrir por nome um arquivo
    temporário que ainda está aberto no mesmo processo -- diferente do
    Linux/Mac. Corrigimos fechando o arquivo (com delete=False) antes de
    devolver o caminho, para que possa ser reaberto normalmente.
    """
    def get_named_tmp_file_patched(self):
        data = self.get_data()
        tmp_file = tempfile.NamedTemporaryFile(suffix=self.suffix, delete=False)
        if data:
            tmp_file.write(data)
            tmp_file.flush()
        tmp_file.close()
        _x2p_files.files_tmp.append(tmp_file)
        if self.path is None:
            self.path = tmp_file.name
        return tmp_file

    _x2p_files.BaseFile.get_named_tmp_file = get_named_tmp_file_patched


_patch_xhtml2pdf_windows_tempfile_bug()


def _file_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _consolidar_tributos(apuracao: ApuracaoSimplesNacional) -> list[dict]:
    totais: dict[str, float] = {}
    ordem_encontrada: list[str] = []
    for anexo in apuracao.anexos:
        for tributo in anexo.tributos:
            if tributo.nome not in totais:
                ordem_encontrada.append(tributo.nome)
            totais[tributo.nome] = totais.get(tributo.nome, 0.0) + tributo.valor

    conhecidos = [n for n in _ORDEM_TRIBUTOS_PREFERENCIAL if n in totais]
    outros = [n for n in ordem_encontrada if n not in _ORDEM_TRIBUTOS_PREFERENCIAL]
    ordem_final = conhecidos + outros

    # Percentual que cada tributo representa dentro da alíquota efetiva do
    # período: valor do tributo / receita tributada total. A soma dos
    # percentuais de todos os tributos bate com a "Alíquota efetiva do
    # período" em destaque no topo do resumo.
    receita_total = apuracao.receita_tributada_total
    return [
        {
            "nome": nome,
            "valor_fmt": fmt_brl(totais[nome]),
            "percentual_fmt": fmt_pct(totais[nome] / receita_total * 100)
            if receita_total
            else "-",
        }
        for nome in ordem_final
    ]


def _contexto_anexos(apuracao: ApuracaoSimplesNacional) -> list[dict]:
    # Empresas com mais de um estabelecimento (matriz/filial), ou mais de um
    # anexo com o mesmo nome (ex.: dois blocos de Anexo III com tratamento de
    # ISS diferente), fazem o mesmo "nome" de anexo aparecer repetido na
    # tabela sem nenhuma distinção. Quando isso acontece, mostramos um
    # detalhe extra por linha -- o CNPJ do estabelecimento (se houver mais de
    # um) e/ou o texto da "Tabela" do próprio relatório (não reescrevemos essa
    # descrição com palavras nossas, pois o que diferencia os blocos varia
    # por anexo/situação e não dá pra prever de antemão).
    cnpjs_distintos = len({a.estabelecimento_cnpj for a in apuracao.anexos if a.estabelecimento_cnpj})
    contagem_nomes = Counter(a.nome for a in apuracao.anexos)

    contexto = []
    for a in apuracao.anexos:
        tendencia_classe = ""
        aliquota_proximo_fmt = "-"
        if a.aliquota_proximo_periodo is not None:
            aliquota_proximo_fmt = fmt_pct(a.aliquota_proximo_periodo)
            if a.aliquota_proximo_periodo > a.aliquota_efetiva + 0.005:
                tendencia_classe = "tendencia-alta"
                aliquota_proximo_fmt = f"▲ {aliquota_proximo_fmt}"
            elif a.aliquota_proximo_periodo < a.aliquota_efetiva - 0.005:
                tendencia_classe = "tendencia-baixa"
                aliquota_proximo_fmt = f"▼ {aliquota_proximo_fmt}"

        detalhes = []
        if cnpjs_distintos > 1 and a.estabelecimento_cnpj:
            detalhes.append(f"CNPJ {a.estabelecimento_cnpj}")
        if contagem_nomes[a.nome] > 1 and a.tabela:
            detalhes.append(a.tabela)

        contexto.append(
            {
                "nome": a.nome,
                "detalhe": " · ".join(detalhes),
                "receita_tributada_fmt": fmt_brl(a.receita_tributada),
                "aliquota_efetiva_fmt": fmt_pct(a.aliquota_efetiva),
                "simples_nacional_total_fmt": fmt_brl(a.simples_nacional_total),
                "aliquota_proximo_fmt": aliquota_proximo_fmt,
                "tendencia_classe": tendencia_classe,
            }
        )
    return contexto


def build_context(apuracao: ApuracaoSimplesNacional) -> dict:
    anexos_ctx = _contexto_anexos(apuracao)
    fator_r_nota = None
    if apuracao.fator_r > 0:
        fator_r_nota = (
            f"Fator R do período: {fmt_pct(apuracao.fator_r)} "
            "(relação entre folha de pagamento e receita bruta nos últimos 12 meses, "
            "usada para determinar o anexo aplicável a atividades de serviços)."
        )

    return {
        "logo_base64": _file_base64(_LOGO_HEADER_PATH),
        "font_satoshi_black": (_FONTS_DIR / "Satoshi-Black.ttf").as_posix(),
        "font_satoshi_bold": (_FONTS_DIR / "Satoshi-Bold.ttf").as_posix(),
        "font_satoshi_medium": (_FONTS_DIR / "Satoshi-Medium.ttf").as_posix(),
        "font_inter_regular": (_FONTS_DIR / "Inter-Regular.ttf").as_posix(),
        "font_inter_semibold": (_FONTS_DIR / "Inter-SemiBold.ttf").as_posix(),
        "empresa": apuracao.empresa,
        "cnpj": apuracao.cnpj,
        "periodo_extenso": fmt_periodo_extenso(apuracao.periodo),
        "total_a_recolher_fmt": fmt_brl(apuracao.total_a_recolher),
        "aliquota_media_fmt": fmt_pct(apuracao.aliquota_media_efetiva),
        "rpa_competencia_fmt": fmt_brl(apuracao.rpa_competencia),
        "rbt12_fmt": fmt_brl(apuracao.rbt12),
        "faixa_enquadramento": apuracao.faixa_enquadramento_interno,
        "anexos": anexos_ctx,
        "mostrar_proximo_periodo": any(
            a.aliquota_proximo_periodo is not None for a in apuracao.anexos
        ),
        "tributos": _consolidar_tributos(apuracao),
        "fator_r_nota": fator_r_nota,
    }


def render_html(apuracao: ApuracaoSimplesNacional) -> str:
    env = Environment(loader=FileSystemLoader(str(_SRC_DIR)))
    template = env.get_template("template.html")
    return template.render(**build_context(apuracao))


def _limpar_temporarios_xhtml2pdf() -> None:
    """Apaga os arquivos temporários que o xhtml2pdf cria a cada @font-face e
    imagem processados (ver `_patch_xhtml2pdf_windows_tempfile_bug`, que usa
    delete=False). Sem isso, um servidor rodando continuamente acumula ~6
    arquivos temporários por PDF gerado, para sempre.
    """
    for tmp_file in _x2p_files.files_tmp.files:
        Path(tmp_file.name).unlink(missing_ok=True)
    _x2p_files.files_tmp.files.clear()


def gerar_pdf_bytes(apuracao: ApuracaoSimplesNacional) -> bytes:
    html = render_html(apuracao)
    buffer = io.BytesIO()
    try:
        resultado = pisa.CreatePDF(html, dest=buffer)
        if resultado.err:
            raise RuntimeError("Falha ao gerar o PDF do resumo.")
        return buffer.getvalue()
    finally:
        _limpar_temporarios_xhtml2pdf()


def gerar_pdf_arquivo(apuracao: ApuracaoSimplesNacional, output_path: str) -> None:
    Path(output_path).write_bytes(gerar_pdf_bytes(apuracao))
