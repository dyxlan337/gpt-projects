"""
Analisador Patrimonial - Ponto de entrada principal.

Analisa extratos de investimentos (B3/Banco Inter) e gera relatórios
granulares por data de compra individual, revelando ganhos/perdas reais
por lote usando método FIFO.

Uso:
    python main.py extrato_b3.pdf
    python main.py extrato_b3.pdf --sem-precos
    python main.py planilha.csv --csv --exportar relatorio
    python main.py extrato1.pdf extrato2.pdf --exportar resultado
"""

import argparse
import os
import sys

from models import TipoAtivo
from pdf_parser import parse_extrato_b3, parse_csv_manual
from portfolio import Portfolio
from price_fetcher import buscar_precos
from reporter import Reporter


def main():
    parser = argparse.ArgumentParser(
        description="Analisador Patrimonial - Relatório granular por lote de compra"
    )
    parser.add_argument(
        "arquivos",
        nargs="+",
        help="Caminho(s) para arquivo(s) PDF (extrato B3) ou CSV",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Tratar arquivos de entrada como CSV (separador ;)",
    )
    parser.add_argument(
        "--separador",
        default=";",
        help="Separador do CSV (padrão: ;)",
    )
    parser.add_argument(
        "--sem-precos",
        action="store_true",
        help="Não buscar preços atuais (útil para análise offline)",
    )
    parser.add_argument(
        "--exportar",
        metavar="PREFIXO",
        help="Exportar relatório para CSV e JSON com o prefixo informado",
    )
    parser.add_argument(
        "--json",
        metavar="ARQUIVO",
        help="Exportar apenas JSON para o arquivo informado",
    )
    parser.add_argument(
        "--silencioso",
        action="store_true",
        help="Não exibir relatório no console",
    )

    args = parser.parse_args()

    # 1. Parse dos arquivos de entrada
    print("=" * 60)
    print("  ANALISADOR PATRIMONIAL")
    print("=" * 60)
    print()

    todas_transacoes = []

    for caminho in args.arquivos:
        if not os.path.exists(caminho):
            print(f"ERRO: Arquivo não encontrado: {caminho}", file=sys.stderr)
            continue

        print(f"Processando: {caminho}")

        try:
            if args.csv or caminho.lower().endswith(".csv"):
                transacoes = parse_csv_manual(caminho, args.separador)
            else:
                transacoes = parse_extrato_b3(caminho)

            print(f"  → {len(transacoes)} transações encontradas")
            todas_transacoes.extend(transacoes)
        except Exception as e:
            print(f"  ERRO ao processar {caminho}: {e}", file=sys.stderr)

    if not todas_transacoes:
        print("\nNenhuma transação encontrada nos arquivos fornecidos.")
        sys.exit(1)

    print(f"\nTotal: {len(todas_transacoes)} transações de {len(args.arquivos)} arquivo(s)")

    # 2. Processa no portfólio
    print("\nProcessando portfólio (FIFO)...")
    portfolio = Portfolio()
    portfolio.processar_transacoes(todas_transacoes)

    if portfolio.ignoradas:
        print(f"  → {len(portfolio.ignoradas)} transações ignoradas (atualização, cancelamento, etc.)")

    # 3. Busca preços atuais
    precos = {}
    if not args.sem_precos:
        # Identifica tickers com posição aberta
        tickers_ativos = [
            ticker for ticker, lotes in portfolio.lotes.items()
            if any(l.ativo for l in lotes)
        ]

        if tickers_ativos:
            print(f"\nBuscando preços atuais para {len(tickers_ativos)} ativo(s)...")
            precos = buscar_precos(tickers_ativos, portfolio.tipos)
            encontrados = len(precos)
            print(f"  → {encontrados}/{len(tickers_ativos)} preços obtidos")

            # Lista os que falharam
            faltantes = set(tickers_ativos) - set(precos.keys())
            if faltantes:
                print(f"  → Sem preço: {', '.join(sorted(faltantes))}")
    else:
        print("\nModo offline: preços atuais não serão buscados.")

    # 4. Gera análise
    analises = portfolio.gerar_analise(precos)
    resumo = portfolio.resumo_carteira(precos)

    # 5. Gera relatório
    reporter = Reporter(analises, resumo)

    if not args.silencioso:
        reporter.relatorio_completo(mostrar_console=True)

    # 6. Exporta se solicitado
    if args.exportar:
        reporter.exportar_csv(args.exportar)
        reporter.exportar_json(f"{args.exportar}.json")

    if args.json:
        reporter.exportar_json(args.json)

    print("\nAnálise concluída.")


def analisar_programatico(
    arquivos: list,
    buscar_precos_online: bool = True,
    formato_csv: bool = False,
    separador_csv: str = ";",
) -> dict:
    """
    Interface programática para uso com Claude Desktop ou outros scripts.

    Retorna dict com análises e resumo para processamento posterior.
    """
    from pdf_parser import parse_extrato_b3, parse_csv_manual
    from price_fetcher import buscar_precos

    todas_transacoes = []
    for caminho in arquivos:
        if formato_csv or caminho.lower().endswith(".csv"):
            transacoes = parse_csv_manual(caminho, separador_csv)
        else:
            transacoes = parse_extrato_b3(caminho)
        todas_transacoes.extend(transacoes)

    portfolio = Portfolio()
    portfolio.processar_transacoes(todas_transacoes)

    precos = {}
    if buscar_precos_online:
        tickers_ativos = [
            ticker for ticker, lotes in portfolio.lotes.items()
            if any(l.ativo for l in lotes)
        ]
        if tickers_ativos:
            precos = buscar_precos(tickers_ativos, portfolio.tipos)

    analises = portfolio.gerar_analise(precos)
    resumo = portfolio.resumo_carteira(precos)

    return {
        "analises": analises,
        "resumo": resumo,
        "transacoes": todas_transacoes,
        "ignoradas": portfolio.ignoradas,
        "precos": precos,
    }


if __name__ == "__main__":
    main()
