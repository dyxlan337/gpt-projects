"""
Busca preços atuais de ativos via yfinance.
Tickers brasileiros usam sufixo .SA no Yahoo Finance.
"""

import sys
from typing import Dict, List, Optional

from models import TipoAtivo


def _ticker_yahoo(ticker: str, tipo_ativo: TipoAtivo = TipoAtivo.DESCONHECIDO) -> Optional[str]:
    """Converte ticker B3 para formato Yahoo Finance (.SA)."""
    ticker = ticker.upper().strip()

    # Renda fixa não tem cotação no Yahoo
    if tipo_ativo in (TipoAtivo.CDB, TipoAtivo.LCI, TipoAtivo.LCA, TipoAtivo.TESOURO):
        return None

    # Se já tem .SA, retorna
    if ticker.endswith(".SA"):
        return ticker

    return f"{ticker}.SA"


def buscar_precos(
    tickers: List[str],
    tipos: Dict[str, TipoAtivo] = None,
) -> Dict[str, float]:
    """
    Busca preços atuais para uma lista de tickers.

    Retorna dict ticker -> preço atual (sem sufixo .SA nas chaves).
    """
    if tipos is None:
        tipos = {}

    precos = {}

    # Filtra tickers que podem ser consultados
    tickers_yahoo = {}
    for ticker in tickers:
        tipo = tipos.get(ticker, TipoAtivo.DESCONHECIDO)
        yahoo = _ticker_yahoo(ticker, tipo)
        if yahoo:
            tickers_yahoo[ticker] = yahoo

    if not tickers_yahoo:
        return precos

    try:
        import yfinance as yf
    except ImportError:
        print("AVISO: yfinance não instalado. Instale com: pip install yfinance", file=sys.stderr)
        return precos

    # Busca em lote para eficiência
    yahoo_tickers = list(tickers_yahoo.values())
    yahoo_to_original = {v: k for k, v in tickers_yahoo.items()}

    try:
        # Busca dados de todos os tickers de uma vez
        dados = yf.download(
            yahoo_tickers,
            period="1d",
            progress=False,
            threads=True,
        )

        if dados.empty:
            # Tenta um por um como fallback
            return _buscar_individual(tickers_yahoo)

        # Extrai preço de fechamento
        if len(yahoo_tickers) == 1:
            # yf.download retorna DataFrame simples para 1 ticker
            ticker_orig = yahoo_to_original[yahoo_tickers[0]]
            if "Close" in dados.columns:
                preco = dados["Close"].iloc[-1]
                if preco and preco > 0:
                    precos[ticker_orig] = float(preco)
        else:
            # Múltiplos tickers - DataFrame com MultiIndex nas colunas
            if "Close" in dados.columns:
                close = dados["Close"]
                for yahoo_tk in yahoo_tickers:
                    ticker_orig = yahoo_to_original[yahoo_tk]
                    if yahoo_tk in close.columns:
                        preco = close[yahoo_tk].dropna()
                        if not preco.empty and preco.iloc[-1] > 0:
                            precos[ticker_orig] = float(preco.iloc[-1])

    except Exception as e:
        print(f"AVISO: Erro ao buscar preços em lote: {e}", file=sys.stderr)
        return _buscar_individual(tickers_yahoo)

    # Para tickers que falharam no lote, tenta individual
    faltantes = {k: v for k, v in tickers_yahoo.items() if k not in precos}
    if faltantes:
        precos_ind = _buscar_individual(faltantes)
        precos.update(precos_ind)

    return precos


def _buscar_individual(tickers_map: Dict[str, str]) -> Dict[str, float]:
    """Busca preços individualmente como fallback."""
    import yfinance as yf

    precos = {}
    for ticker_orig, ticker_yahoo in tickers_map.items():
        try:
            ativo = yf.Ticker(ticker_yahoo)
            info = ativo.fast_info
            preco = getattr(info, "last_price", None)
            if preco and preco > 0:
                precos[ticker_orig] = float(preco)
            else:
                # Tenta histórico
                hist = ativo.history(period="5d")
                if not hist.empty and "Close" in hist.columns:
                    preco = hist["Close"].dropna().iloc[-1]
                    if preco > 0:
                        precos[ticker_orig] = float(preco)
        except Exception as e:
            print(f"AVISO: Não foi possível obter preço de {ticker_orig}: {e}", file=sys.stderr)

    return precos


def buscar_preco_unico(ticker: str, tipo_ativo: TipoAtivo = TipoAtivo.DESCONHECIDO) -> Optional[float]:
    """Busca preço de um único ticker."""
    resultado = buscar_precos([ticker], {ticker: tipo_ativo})
    return resultado.get(ticker)
