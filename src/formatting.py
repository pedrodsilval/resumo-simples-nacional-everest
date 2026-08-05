"""Formatação de valores no padrão brasileiro para o resumo do cliente."""

from __future__ import annotations

_MESES = {
    "01": "Janeiro", "02": "Fevereiro", "03": "Março", "04": "Abril",
    "05": "Maio", "06": "Junho", "07": "Julho", "08": "Agosto",
    "09": "Setembro", "10": "Outubro", "11": "Novembro", "12": "Dezembro",
}


def fmt_brl(value: float) -> str:
    """1234.56 -> 'R$ 1.234,56'"""
    negativo = value < 0
    value = abs(value)
    inteiro, _, decimal = f"{value:,.2f}".partition(".")
    inteiro = inteiro.replace(",", ".")
    texto = f"R$ {inteiro},{decimal}"
    return f"-{texto}" if negativo else texto


def fmt_pct(value: float, casas: int = 2) -> str:
    """7.0104796507412 -> '7,01%'"""
    texto = f"{value:.{casas}f}".replace(".", ",")
    return f"{texto}%"


def fmt_periodo_extenso(periodo: str) -> str:
    """'06/2026' -> 'Junho/2026'"""
    mes, _, ano = periodo.partition("/")
    return f"{_MESES.get(mes, mes)}/{ano}" if ano else periodo
