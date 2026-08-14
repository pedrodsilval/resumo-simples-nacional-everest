"""App interno (Streamlit) para gerar o resumo do Simples Nacional para clientes.

Uso: streamlit run app.py
"""

import sys
import tempfile
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))

from formatting import fmt_brl, fmt_pct, fmt_periodo_extenso  # noqa: E402
from generate import _consolidar_tributos, _contexto_anexos, gerar_pdf_bytes  # noqa: E402
from parser import parse_relatorio  # noqa: E402

st.set_page_config(page_title="Resumo Simples Nacional - Everest", page_icon="📄")

# O Streamlit sempre declara <html lang="en">, mesmo com o app inteiro em
# português -- isso engana o Chrome a oferecer (ou forçar) tradução
# automática, que troca termos técnicos por sinônimos errados (ex.: "Valor"
# vira "Valentia"). Corrigindo o lang para pt-BR, o Chrome reconhece que a
# página já está no idioma certo e não tenta traduzir.
st.components.v1.html(
    "<script>parent.document.documentElement.lang = 'pt-BR';</script>",
    height=0,
)

st.title("Resumo do Simples Nacional")
st.caption(
    "Faça upload do relatório de apuração do Simples Nacional (PDF) para gerar "
    "um resumo pronto para enviar ao cliente."
)

arquivo = st.file_uploader("Relatório de apuração (PDF)", type=["pdf"])

if arquivo is not None:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(arquivo.getvalue())
        caminho_tmp = tmp.name

    try:
        try:
            apuracao = parse_relatorio(caminho_tmp)
        except ValueError as erro:
            st.error(str(erro))
            apuracao = None
        except Exception:
            st.error(
                "Não consegui ler este arquivo. Confirme se é um PDF de apuração do "
                "Simples Nacional válido, não corrompido e sem senha."
            )
            apuracao = None
    finally:
        Path(caminho_tmp).unlink(missing_ok=True)

    if apuracao is not None:
        st.success(f"Relatório de **{apuracao.empresa}** (competência {apuracao.periodo}) lido com sucesso.")

        col1, col2, col3 = st.columns(3)
        col1.metric("Simples Nacional a recolher", fmt_brl(apuracao.total_a_recolher))
        col2.metric("Alíquota efetiva do período", fmt_pct(apuracao.aliquota_media_efetiva))
        col3.metric("Receita bruta do período", fmt_brl(apuracao.rpa_competencia))

        st.subheader("Detalhamento por anexo")
        st.table(
            [
                {
                    "Anexo": a["nome"] + (f" ({a['detalhe']})" if a["detalhe"] else ""),
                    "Receita tributada": a["receita_tributada_fmt"],
                    "Alíquota efetiva": a["aliquota_efetiva_fmt"],
                    "Valor do Simples": a["simples_nacional_total_fmt"],
                    "Próx. período": a["aliquota_proximo_fmt"],
                }
                for a in _contexto_anexos(apuracao)
            ]
        )

        st.subheader("Valor por tributo")
        st.table(
            [
                {"Tributo": t["nome"], "% da alíquota": t["percentual_fmt"], "Valor": t["valor_fmt"]}
                for t in _consolidar_tributos(apuracao)
            ]
        )

        pdf_bytes = gerar_pdf_bytes(apuracao)
        nome_arquivo = (
            f"resumo_simples_nacional_{apuracao.empresa.split()[0].lower()}_"
            f"{apuracao.periodo.replace('/', '-')}.pdf"
        )
        st.download_button(
            "Baixar resumo em PDF",
            data=pdf_bytes,
            file_name=nome_arquivo,
            mime="application/pdf",
            type="primary",
        )
else:
    st.info("Nenhum arquivo selecionado ainda.")
