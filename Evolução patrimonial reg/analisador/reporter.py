"""
Gerador de relatórios de análise patrimonial.
Saída em console (tabulate), CSV e JSON.
"""

import csv
import json
import os
from datetime import date, datetime
from typing import Dict, List, Optional

from tabulate import tabulate

from models import AnaliseAtivo, Lote, VendaRealizada, ProventoRecebido, TipoAtivo


def _fmt_moeda(valor: float) -> str:
    """Formata valor em reais."""
    if valor < 0:
        return f"-R$ {abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_pct(valor: float) -> str:
    """Formata percentual."""
    sinal = "+" if valor > 0 else ""
    return f"{sinal}{valor:.2f}%"


def _fmt_data(d: date) -> str:
    """Formata data."""
    return d.strftime("%d/%m/%Y")


def _cor_lucro(valor: float) -> str:
    """Indicador visual de lucro/prejuízo."""
    if valor > 0.01:
        return "▲"
    elif valor < -0.01:
        return "▼"
    return "─"


class Reporter:
    """Gera relatórios de análise patrimonial."""

    def __init__(self, analises: Dict[str, AnaliseAtivo], resumo: dict = None):
        self.analises = analises
        self.resumo = resumo or {}

    def relatorio_completo(self, mostrar_console: bool = True) -> str:
        """Gera relatório completo em texto."""
        partes = []

        partes.append(self._secao_resumo_geral())
        partes.append(self._secao_posicoes_abertas())
        partes.append(self._secao_lotes_detalhados())
        partes.append(self._secao_vendas_realizadas())
        partes.append(self._secao_proventos())
        partes.append(self._secao_ranking())
        partes.append(self._secao_timing())

        texto = "\n".join(partes)

        if mostrar_console:
            print(texto)

        return texto

    def _secao_resumo_geral(self) -> str:
        """Seção: Resumo geral da carteira."""
        linhas = [
            "",
            "=" * 80,
            "  ANÁLISE PATRIMONIAL - RELATÓRIO POR LOTE DE COMPRA",
            "=" * 80,
            "",
        ]

        if self.resumo:
            linhas.append(f"  Ativos em carteira: {self.resumo.get('total_ativos', 0)}")
            linhas.append(f"  Custo total:              {_fmt_moeda(self.resumo.get('custo_total', 0))}")
            linhas.append(f"  Valor de mercado:         {_fmt_moeda(self.resumo.get('valor_mercado', 0))}")
            linhas.append(f"  Lucro não realizado:      {_fmt_moeda(self.resumo.get('lucro_nao_realizado', 0))}  ({_fmt_pct(self.resumo.get('percentual_nao_realizado', 0))})")
            linhas.append(f"  Lucro realizado (vendas): {_fmt_moeda(self.resumo.get('lucro_realizado', 0))}")
            linhas.append(f"  Proventos recebidos:      {_fmt_moeda(self.resumo.get('total_proventos', 0))}")
            linhas.append(f"  Retorno total:            {_fmt_moeda(self.resumo.get('retorno_total', 0))}")

        linhas.append("")
        return "\n".join(linhas)

    def _secao_posicoes_abertas(self) -> str:
        """Seção: Posições abertas consolidadas por ativo."""
        linhas = [
            "-" * 80,
            "  POSIÇÕES ABERTAS (CONSOLIDADO POR ATIVO)",
            "-" * 80,
            "",
        ]

        tabela = []
        for ticker, analise in sorted(self.analises.items()):
            if analise.quantidade_total <= 0:
                continue

            tabela.append([
                ticker,
                analise.tipo_ativo.value,
                f"{analise.quantidade_total:.0f}",
                _fmt_moeda(analise.custo_total / analise.quantidade_total) if analise.quantidade_total > 0 else "-",
                _fmt_moeda(analise.preco_atual) if analise.preco_atual else "N/D",
                _fmt_moeda(analise.valor_mercado) if analise.preco_atual else "N/D",
                f"{_cor_lucro(analise.lucro_nao_realizado)} {_fmt_moeda(analise.lucro_nao_realizado)}" if analise.preco_atual else "N/D",
                _fmt_pct(analise.percentual_nao_realizado) if analise.preco_atual else "N/D",
            ])

        if tabela:
            headers = ["Ticker", "Tipo", "Qtd", "PM Compra", "Preço Atual", "Valor Mercado", "Lucro/Prejuízo", "%"]
            linhas.append(tabulate(tabela, headers=headers, tablefmt="simple", stralign="right"))
        else:
            linhas.append("  Nenhuma posição aberta.")

        linhas.append("")
        return "\n".join(linhas)

    def _secao_lotes_detalhados(self) -> str:
        """Seção: Detalhamento por lote individual de compra."""
        linhas = [
            "-" * 80,
            "  DETALHAMENTO POR LOTE DE COMPRA (GRANULAR)",
            "-" * 80,
            "",
        ]

        for ticker, analise in sorted(self.analises.items()):
            if not analise.lotes_ativos:
                continue

            preco_atual = analise.preco_atual
            linhas.append(f"  ┌─ {ticker} ({analise.nome}) ─ {analise.tipo_ativo.value}")

            tabela = []
            for i, lote in enumerate(sorted(analise.lotes_ativos, key=lambda l: l.data_compra)):
                lucro = (preco_atual - lote.preco_compra) * lote.quantidade_atual if preco_atual else 0
                pct = ((preco_atual / lote.preco_compra) - 1) * 100 if preco_atual and lote.preco_compra > 0 else 0

                tabela.append([
                    f"  #{i+1}",
                    _fmt_data(lote.data_compra),
                    f"{lote.quantidade_atual:.0f}/{lote.quantidade_original:.0f}",
                    _fmt_moeda(lote.preco_compra),
                    _fmt_moeda(preco_atual) if preco_atual else "N/D",
                    _fmt_moeda(lote.quantidade_atual * lote.preco_compra),
                    f"{_cor_lucro(lucro)} {_fmt_moeda(lucro)}" if preco_atual else "N/D",
                    _fmt_pct(pct) if preco_atual else "N/D",
                    lote.instituicao or "",
                ])

            headers = ["", "Data Compra", "Qtd Atual/Orig", "Preço Compra", "Preço Atual",
                       "Custo Posição", "Lucro/Prejuízo", "%", "Instituição"]
            linhas.append(tabulate(tabela, headers=headers, tablefmt="simple", stralign="right"))
            linhas.append(f"  └─ Total proventos {ticker}: {_fmt_moeda(analise.total_proventos)}")
            linhas.append("")

        if not any(a.lotes_ativos for a in self.analises.values()):
            linhas.append("  Nenhum lote ativo.")
            linhas.append("")

        return "\n".join(linhas)

    def _secao_vendas_realizadas(self) -> str:
        """Seção: Vendas realizadas com lucro/prejuízo por lote."""
        linhas = [
            "-" * 80,
            "  VENDAS REALIZADAS (LUCRO/PREJUÍZO POR LOTE ORIGINAL)",
            "-" * 80,
            "",
        ]

        todas_vendas = []
        for ticker, analise in self.analises.items():
            for venda in analise.vendas:
                todas_vendas.append((ticker, venda))

        if todas_vendas:
            todas_vendas.sort(key=lambda x: x[1].data_venda)

            tabela = []
            for ticker, v in todas_vendas:
                tabela.append([
                    _fmt_data(v.data_venda),
                    ticker,
                    f"{v.quantidade:.0f}",
                    _fmt_moeda(v.preco_compra),
                    _fmt_data(v.data_compra),
                    _fmt_moeda(v.preco_venda),
                    f"{_cor_lucro(v.lucro_bruto)} {_fmt_moeda(v.lucro_bruto)}",
                    _fmt_pct(v.percentual),
                ])

            headers = ["Data Venda", "Ticker", "Qtd", "Preço Compra", "Data Compra",
                       "Preço Venda", "Lucro Bruto", "%"]
            linhas.append(tabulate(tabela, headers=headers, tablefmt="simple", stralign="right"))
        else:
            linhas.append("  Nenhuma venda registrada.")

        linhas.append("")
        return "\n".join(linhas)

    def _secao_proventos(self) -> str:
        """Seção: Proventos recebidos."""
        linhas = [
            "-" * 80,
            "  PROVENTOS RECEBIDOS",
            "-" * 80,
            "",
        ]

        todos_proventos = []
        for ticker, analise in self.analises.items():
            for p in analise.proventos:
                todos_proventos.append((ticker, p))

        if todos_proventos:
            todos_proventos.sort(key=lambda x: x[1].data)

            tabela = []
            for ticker, p in todos_proventos:
                tabela.append([
                    _fmt_data(p.data),
                    ticker,
                    p.tipo,
                    _fmt_moeda(p.valor_total),
                ])

            headers = ["Data", "Ticker", "Tipo", "Valor"]
            linhas.append(tabulate(tabela, headers=headers, tablefmt="simple", stralign="right"))

            # Total
            total = sum(p.valor_total for _, p in todos_proventos)
            linhas.append(f"\n  Total proventos: {_fmt_moeda(total)}")
        else:
            linhas.append("  Nenhum provento registrado.")

        linhas.append("")
        return "\n".join(linhas)

    def _secao_ranking(self) -> str:
        """Seção: Ranking de melhores e piores desempenhos."""
        linhas = [
            "-" * 80,
            "  RANKING DE DESEMPENHO",
            "-" * 80,
            "",
        ]

        # Ranking por lote individual (não realizado)
        lotes_com_preco = []
        for ticker, analise in self.analises.items():
            if not analise.preco_atual:
                continue
            for lote in analise.lotes_ativos:
                pct = ((analise.preco_atual / lote.preco_compra) - 1) * 100 if lote.preco_compra > 0 else 0
                lucro = (analise.preco_atual - lote.preco_compra) * lote.quantidade_atual
                lotes_com_preco.append((ticker, lote, pct, lucro))

        if lotes_com_preco:
            # Top 10 melhores
            melhores = sorted(lotes_com_preco, key=lambda x: x[2], reverse=True)[:10]
            linhas.append("  ▲ TOP 10 MELHORES COMPRAS (por % ganho):")
            tabela = []
            for ticker, lote, pct, lucro in melhores:
                tabela.append([
                    ticker,
                    _fmt_data(lote.data_compra),
                    f"{lote.quantidade_atual:.0f}",
                    _fmt_moeda(lote.preco_compra),
                    _fmt_pct(pct),
                    _fmt_moeda(lucro),
                ])
            headers = ["Ticker", "Data Compra", "Qtd", "Preço Compra", "Retorno %", "Lucro R$"]
            linhas.append(tabulate(tabela, headers=headers, tablefmt="simple", stralign="right"))
            linhas.append("")

            # Top 10 piores
            piores = sorted(lotes_com_preco, key=lambda x: x[2])[:10]
            linhas.append("  ▼ TOP 10 PIORES COMPRAS (por % perda):")
            tabela = []
            for ticker, lote, pct, lucro in piores:
                tabela.append([
                    ticker,
                    _fmt_data(lote.data_compra),
                    f"{lote.quantidade_atual:.0f}",
                    _fmt_moeda(lote.preco_compra),
                    _fmt_pct(pct),
                    _fmt_moeda(lucro),
                ])
            linhas.append(tabulate(tabela, headers=headers, tablefmt="simple", stralign="right"))

            # Ranking por valor absoluto (R$)
            linhas.append("")
            maiores_lucros = sorted(lotes_com_preco, key=lambda x: x[3], reverse=True)[:5]
            linhas.append("  💰 TOP 5 MAIORES LUCROS (em R$):")
            tabela = []
            for ticker, lote, pct, lucro in maiores_lucros:
                tabela.append([
                    ticker,
                    _fmt_data(lote.data_compra),
                    _fmt_moeda(lucro),
                    _fmt_pct(pct),
                ])
            headers2 = ["Ticker", "Data Compra", "Lucro R$", "%"]
            linhas.append(tabulate(tabela, headers=headers2, tablefmt="simple", stralign="right"))

            maiores_perdas = sorted(lotes_com_preco, key=lambda x: x[3])[:5]
            linhas.append("")
            linhas.append("  📉 TOP 5 MAIORES PERDAS (em R$):")
            tabela = []
            for ticker, lote, pct, lucro in maiores_perdas:
                tabela.append([
                    ticker,
                    _fmt_data(lote.data_compra),
                    _fmt_moeda(lucro),
                    _fmt_pct(pct),
                ])
            linhas.append(tabulate(tabela, headers=headers2, tablefmt="simple", stralign="right"))
        else:
            linhas.append("  Sem dados de preço atual para ranking.")

        linhas.append("")
        return "\n".join(linhas)

    def _secao_timing(self) -> str:
        """Seção: Análise de timing das compras."""
        linhas = [
            "-" * 80,
            "  ANÁLISE DE TIMING",
            "-" * 80,
            "",
        ]

        # Análise por período (mês/ano)
        compras_por_mes = {}
        for ticker, analise in self.analises.items():
            if not analise.preco_atual:
                continue
            for lote in analise.lotes_ativos:
                chave = lote.data_compra.strftime("%Y-%m")
                if chave not in compras_por_mes:
                    compras_por_mes[chave] = {"custo": 0, "valor": 0, "qtd_lotes": 0}
                custo = lote.quantidade_atual * lote.preco_compra
                valor = lote.quantidade_atual * analise.preco_atual
                compras_por_mes[chave]["custo"] += custo
                compras_por_mes[chave]["valor"] += valor
                compras_por_mes[chave]["qtd_lotes"] += 1

        if compras_por_mes:
            linhas.append("  Desempenho por mês de compra:")
            tabela = []
            for mes in sorted(compras_por_mes.keys()):
                dados = compras_por_mes[mes]
                pct = ((dados["valor"] / dados["custo"]) - 1) * 100 if dados["custo"] > 0 else 0
                lucro = dados["valor"] - dados["custo"]
                tabela.append([
                    mes,
                    dados["qtd_lotes"],
                    _fmt_moeda(dados["custo"]),
                    _fmt_moeda(dados["valor"]),
                    f"{_cor_lucro(lucro)} {_fmt_moeda(lucro)}",
                    _fmt_pct(pct),
                ])

            headers = ["Mês", "Lotes", "Custo", "Valor Atual", "Lucro/Prejuízo", "%"]
            linhas.append(tabulate(tabela, headers=headers, tablefmt="simple", stralign="right"))
        else:
            linhas.append("  Sem dados de preço atual para análise de timing.")

        linhas.append("")
        return "\n".join(linhas)

    def exportar_csv(self, caminho: str) -> None:
        """Exporta dados para CSV (múltiplos arquivos)."""
        base = os.path.splitext(caminho)[0]

        # 1. Lotes ativos
        self._csv_lotes_ativos(f"{base}_lotes_ativos.csv")

        # 2. Vendas
        self._csv_vendas(f"{base}_vendas.csv")

        # 3. Proventos
        self._csv_proventos(f"{base}_proventos.csv")

        # 4. Resumo por ativo
        self._csv_resumo_ativos(f"{base}_resumo.csv")

        print(f"CSVs exportados com prefixo: {base}_*.csv")

    def _csv_lotes_ativos(self, caminho: str) -> None:
        with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow([
                "Ticker", "Tipo", "Data Compra", "Qtd Atual", "Qtd Original",
                "Preço Compra", "Preço Atual", "Custo Posição", "Valor Mercado",
                "Lucro/Prejuízo", "Retorno %", "Instituição",
            ])
            for ticker, analise in sorted(self.analises.items()):
                for lote in analise.lotes_ativos:
                    preco_atual = analise.preco_atual or 0
                    custo = lote.quantidade_atual * lote.preco_compra
                    valor = lote.quantidade_atual * preco_atual
                    lucro = valor - custo
                    pct = ((preco_atual / lote.preco_compra) - 1) * 100 if lote.preco_compra > 0 and preco_atual > 0 else 0

                    writer.writerow([
                        ticker,
                        analise.tipo_ativo.value,
                        _fmt_data(lote.data_compra),
                        f"{lote.quantidade_atual:.2f}",
                        f"{lote.quantidade_original:.2f}",
                        f"{lote.preco_compra:.2f}",
                        f"{preco_atual:.2f}" if preco_atual else "",
                        f"{custo:.2f}",
                        f"{valor:.2f}" if preco_atual else "",
                        f"{lucro:.2f}" if preco_atual else "",
                        f"{pct:.2f}" if preco_atual else "",
                        lote.instituicao,
                    ])

    def _csv_vendas(self, caminho: str) -> None:
        with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow([
                "Data Venda", "Ticker", "Quantidade", "Preço Compra",
                "Data Compra", "Preço Venda", "Lucro Bruto", "Retorno %",
            ])
            for ticker, analise in sorted(self.analises.items()):
                for v in analise.vendas:
                    writer.writerow([
                        _fmt_data(v.data_venda),
                        ticker,
                        f"{v.quantidade:.2f}",
                        f"{v.preco_compra:.2f}",
                        _fmt_data(v.data_compra),
                        f"{v.preco_venda:.2f}",
                        f"{v.lucro_bruto:.2f}",
                        f"{v.percentual:.2f}",
                    ])

    def _csv_proventos(self, caminho: str) -> None:
        with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["Data", "Ticker", "Tipo", "Valor"])
            for ticker, analise in sorted(self.analises.items()):
                for p in analise.proventos:
                    writer.writerow([
                        _fmt_data(p.data),
                        ticker,
                        p.tipo,
                        f"{p.valor_total:.2f}",
                    ])

    def _csv_resumo_ativos(self, caminho: str) -> None:
        with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow([
                "Ticker", "Nome", "Tipo", "Qtd Total", "Custo Total",
                "Preço Atual", "Valor Mercado", "Lucro Não Realizado",
                "% Não Realizado", "Lucro Realizado", "Total Proventos",
            ])
            for ticker, a in sorted(self.analises.items()):
                writer.writerow([
                    ticker,
                    a.nome,
                    a.tipo_ativo.value,
                    f"{a.quantidade_total:.2f}",
                    f"{a.custo_total:.2f}",
                    f"{a.preco_atual:.2f}" if a.preco_atual else "",
                    f"{a.valor_mercado:.2f}" if a.preco_atual else "",
                    f"{a.lucro_nao_realizado:.2f}" if a.preco_atual else "",
                    f"{a.percentual_nao_realizado:.2f}" if a.preco_atual else "",
                    f"{a.lucro_realizado:.2f}",
                    f"{a.total_proventos:.2f}",
                ])

    def exportar_json(self, caminho: str) -> None:
        """Exporta análise completa para JSON."""
        dados = {
            "data_geracao": datetime.now().isoformat(),
            "resumo": self.resumo,
            "ativos": {},
        }

        for ticker, analise in sorted(self.analises.items()):
            ativo_json = {
                "ticker": ticker,
                "nome": analise.nome,
                "tipo": analise.tipo_ativo.value,
                "quantidade_total": analise.quantidade_total,
                "custo_total": analise.custo_total,
                "preco_atual": analise.preco_atual,
                "valor_mercado": analise.valor_mercado,
                "lucro_nao_realizado": analise.lucro_nao_realizado,
                "percentual_nao_realizado": analise.percentual_nao_realizado,
                "lucro_realizado": analise.lucro_realizado,
                "total_proventos": analise.total_proventos,
                "lotes_ativos": [
                    {
                        "data_compra": _fmt_data(l.data_compra),
                        "quantidade_atual": l.quantidade_atual,
                        "quantidade_original": l.quantidade_original,
                        "preco_compra": l.preco_compra,
                        "custo_posicao": l.quantidade_atual * l.preco_compra,
                        "valor_mercado": l.quantidade_atual * analise.preco_atual if analise.preco_atual else None,
                        "lucro": (analise.preco_atual - l.preco_compra) * l.quantidade_atual if analise.preco_atual else None,
                        "retorno_pct": ((analise.preco_atual / l.preco_compra) - 1) * 100 if analise.preco_atual and l.preco_compra > 0 else None,
                        "instituicao": l.instituicao,
                    }
                    for l in sorted(analise.lotes_ativos, key=lambda x: x.data_compra)
                ],
                "vendas": [
                    {
                        "data_venda": _fmt_data(v.data_venda),
                        "data_compra": _fmt_data(v.data_compra),
                        "quantidade": v.quantidade,
                        "preco_compra": v.preco_compra,
                        "preco_venda": v.preco_venda,
                        "lucro_bruto": v.lucro_bruto,
                        "retorno_pct": v.percentual,
                    }
                    for v in analise.vendas
                ],
                "proventos": [
                    {
                        "data": _fmt_data(p.data),
                        "tipo": p.tipo,
                        "valor": p.valor_total,
                    }
                    for p in analise.proventos
                ],
            }
            dados["ativos"][ticker] = ativo_json

        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)

        print(f"JSON exportado: {caminho}")
