"""
Gerenciador de portfólio com rastreamento de lotes individuais (FIFO).
Processa transações e mantém posições abertas/fechadas.
"""

from collections import defaultdict
from copy import deepcopy
from datetime import date
from typing import Dict, List, Tuple

from models import (
    Transacao, Lote, VendaRealizada, ProventoRecebido,
    AnaliseAtivo, TipoMovimentacao, TipoAtivo,
)


class Portfolio:
    """Gerencia posições de investimento usando método FIFO por lote."""

    def __init__(self):
        # ticker -> lista de Lote (ordenados por data de compra)
        self.lotes: Dict[str, List[Lote]] = defaultdict(list)
        # ticker -> lista de VendaRealizada
        self.vendas: Dict[str, List[VendaRealizada]] = defaultdict(list)
        # ticker -> lista de ProventoRecebido
        self.proventos: Dict[str, List[ProventoRecebido]] = defaultdict(list)
        # ticker -> nome completo mais recente
        self.nomes: Dict[str, str] = {}
        # ticker -> tipo do ativo
        self.tipos: Dict[str, TipoAtivo] = {}
        # Transações ignoradas ou não processadas
        self.ignoradas: List[Transacao] = []

    def processar_transacoes(self, transacoes: List[Transacao]) -> None:
        """Processa lista de transações em ordem cronológica."""
        # Ordena por data
        transacoes_ord = sorted(transacoes, key=lambda t: t.data)

        for trans in transacoes_ord:
            self._processar_transacao(trans)

    def _processar_transacao(self, trans: Transacao) -> None:
        """Processa uma única transação."""
        # Atualiza nome e tipo
        if trans.ticker:
            if trans.nome_completo:
                self.nomes[trans.ticker] = trans.nome_completo
            if trans.tipo_ativo != TipoAtivo.DESCONHECIDO:
                self.tipos[trans.ticker] = trans.tipo_ativo

        if trans.tipo == TipoMovimentacao.COMPRA:
            self._compra(trans)
        elif trans.tipo == TipoMovimentacao.VENDA:
            self._venda(trans)
        elif trans.tipo in (
            TipoMovimentacao.DIVIDENDO,
            TipoMovimentacao.JCP,
            TipoMovimentacao.RENDIMENTO,
        ):
            self._provento(trans)
        elif trans.tipo == TipoMovimentacao.BONIFICACAO:
            self._bonificacao(trans)
        elif trans.tipo == TipoMovimentacao.APLICACAO:
            self._compra(trans)  # Trata aplicação como compra
        elif trans.tipo == TipoMovimentacao.RESGATE:
            self._venda(trans)  # Trata resgate como venda
        elif trans.tipo == TipoMovimentacao.VENCIMENTO:
            self._vencimento(trans)
        elif trans.tipo == TipoMovimentacao.LEILAO_FRACAO:
            self._venda(trans)  # Leilão de fração = venda forçada
        elif trans.tipo == TipoMovimentacao.PAGAMENTO_JUROS:
            self._provento(trans)
        elif trans.tipo in (
            TipoMovimentacao.IGNORAR,
            TipoMovimentacao.CANCELADO,
            TipoMovimentacao.ATUALIZACAO,
        ):
            self.ignoradas.append(trans)
        else:
            self.ignoradas.append(trans)

    def _compra(self, trans: Transacao) -> None:
        """Registra uma compra como novo lote."""
        preco = trans.preco_unitario
        if preco == 0 and trans.quantidade > 0:
            preco = trans.valor_operacao / trans.quantidade

        valor_total = trans.valor_operacao
        if valor_total == 0:
            valor_total = trans.quantidade * preco

        lote = Lote(
            data_compra=trans.data,
            ticker=trans.ticker,
            quantidade_original=trans.quantidade,
            quantidade_atual=trans.quantidade,
            preco_compra=preco,
            valor_total_compra=valor_total,
            instituicao=trans.instituicao,
            tipo_ativo=trans.tipo_ativo,
        )
        self.lotes[trans.ticker].append(lote)

    def _venda(self, trans: Transacao) -> None:
        """Processa uma venda usando FIFO - consume lotes mais antigos primeiro."""
        preco_venda = trans.preco_unitario
        if preco_venda == 0 and trans.quantidade > 0:
            preco_venda = trans.valor_operacao / trans.quantidade

        qtd_restante = trans.quantidade
        lotes_ticker = self.lotes.get(trans.ticker, [])

        for lote in lotes_ticker:
            if qtd_restante <= 0.001:
                break
            if not lote.ativo:
                continue

            # Quanto consumir deste lote
            qtd_consumir = min(lote.quantidade_atual, qtd_restante)

            # Calcula lucro
            lucro = (preco_venda - lote.preco_compra) * qtd_consumir
            percentual = ((preco_venda / lote.preco_compra) - 1) * 100 if lote.preco_compra > 0 else 0.0

            venda = VendaRealizada(
                data_venda=trans.data,
                ticker=trans.ticker,
                quantidade=qtd_consumir,
                preco_venda=preco_venda,
                preco_compra=lote.preco_compra,
                data_compra=lote.data_compra,
                lucro_bruto=lucro,
                percentual=percentual,
            )
            self.vendas[trans.ticker].append(venda)

            # Atualiza lote
            lote.quantidade_atual -= qtd_consumir
            qtd_restante -= qtd_consumir

        if qtd_restante > 0.001:
            # Venda sem lote correspondente (pode ser posição anterior ao extrato)
            venda = VendaRealizada(
                data_venda=trans.data,
                ticker=trans.ticker,
                quantidade=qtd_restante,
                preco_venda=preco_venda,
                preco_compra=0.0,
                data_compra=trans.data,
                lucro_bruto=0.0,
                percentual=0.0,
            )
            self.vendas[trans.ticker].append(venda)

    def _provento(self, trans: Transacao) -> None:
        """Registra recebimento de provento."""
        # Calcula quantidade base (posição atual)
        qtd_base = sum(
            l.quantidade_atual for l in self.lotes.get(trans.ticker, []) if l.ativo
        )

        valor_por_unidade = 0.0
        if qtd_base > 0 and trans.valor_operacao > 0:
            valor_por_unidade = trans.valor_operacao / qtd_base
        elif trans.preco_unitario > 0:
            valor_por_unidade = trans.preco_unitario

        tipo_texto = {
            TipoMovimentacao.DIVIDENDO: "Dividendo",
            TipoMovimentacao.JCP: "JCP",
            TipoMovimentacao.RENDIMENTO: "Rendimento",
            TipoMovimentacao.PAGAMENTO_JUROS: "Juros",
        }.get(trans.tipo, str(trans.tipo.value))

        provento = ProventoRecebido(
            data=trans.data,
            ticker=trans.ticker,
            tipo=tipo_texto,
            quantidade_base=qtd_base if qtd_base > 0 else trans.quantidade,
            valor_por_unidade=valor_por_unidade,
            valor_total=trans.valor_operacao,
        )
        self.proventos[trans.ticker].append(provento)

    def _vencimento(self, trans: Transacao) -> None:
        """Processa vencimento de título de renda fixa.

        No XLSX da B3, VENCIMENTO frequentemente vem com preço=0 e valor=0
        (campo '-'). Nesse caso, o título venceu e o principal foi devolvido.
        Usamos o valor original do lote como valor de 'venda' (lucro=0 no principal;
        juros já vieram em PAGAMENTO DE JUROS separado).
        """
        preco_venda = trans.preco_unitario
        if preco_venda == 0 and trans.quantidade > 0 and trans.valor_operacao > 0:
            preco_venda = trans.valor_operacao / trans.quantidade

        # Se valor é 0, tentar usar o preço de compra do lote (devolução do principal)
        lotes_ticker = self.lotes.get(trans.ticker, [])
        if preco_venda == 0 and lotes_ticker:
            for lote in lotes_ticker:
                if lote.ativo:
                    preco_venda = lote.preco_compra
                    break

        qtd_restante = trans.quantidade
        for lote in lotes_ticker:
            if qtd_restante <= 0.001:
                break
            if not lote.ativo:
                continue

            qtd_consumir = min(lote.quantidade_atual, qtd_restante)
            # No vencimento, se não temos preço de venda, usamos o preço de compra
            # (lucro = 0, pois juros vieram separadamente)
            pv = preco_venda if preco_venda > 0 else lote.preco_compra

            lucro = (pv - lote.preco_compra) * qtd_consumir
            percentual = ((pv / lote.preco_compra) - 1) * 100 if lote.preco_compra > 0 else 0.0

            venda = VendaRealizada(
                data_venda=trans.data,
                ticker=trans.ticker,
                quantidade=qtd_consumir,
                preco_venda=pv,
                preco_compra=lote.preco_compra,
                data_compra=lote.data_compra,
                lucro_bruto=lucro,
                percentual=percentual,
            )
            self.vendas[trans.ticker].append(venda)
            lote.quantidade_atual -= qtd_consumir
            qtd_restante -= qtd_consumir

        if qtd_restante > 0.001:
            # Vencimento sem lote (aplicação anterior ao extrato)
            venda = VendaRealizada(
                data_venda=trans.data,
                ticker=trans.ticker,
                quantidade=qtd_restante,
                preco_venda=preco_venda,
                preco_compra=0.0,
                data_compra=trans.data,
                lucro_bruto=0.0,
                percentual=0.0,
            )
            self.vendas[trans.ticker].append(venda)

    def _bonificacao(self, trans: Transacao) -> None:
        """Registra bonificação como compra a custo zero (ou custo informado)."""
        lote = Lote(
            data_compra=trans.data,
            ticker=trans.ticker,
            quantidade_original=trans.quantidade,
            quantidade_atual=trans.quantidade,
            preco_compra=trans.preco_unitario,
            valor_total_compra=trans.valor_operacao,
            instituicao=trans.instituicao,
            tipo_ativo=trans.tipo_ativo,
        )
        self.lotes[trans.ticker].append(lote)

    def gerar_analise(
        self, precos_atuais: Dict[str, float] = None
    ) -> Dict[str, AnaliseAtivo]:
        """Gera análise consolidada de todos os ativos."""
        if precos_atuais is None:
            precos_atuais = {}

        resultado = {}

        # Todos os tickers que apareceram
        todos_tickers = set(self.lotes.keys()) | set(self.vendas.keys()) | set(self.proventos.keys())

        for ticker in sorted(todos_tickers):
            lotes_ticker = self.lotes.get(ticker, [])
            lotes_ativos = [l for l in lotes_ticker if l.ativo]
            lotes_encerrados = [l for l in lotes_ticker if not l.ativo]

            vendas_ticker = self.vendas.get(ticker, [])
            proventos_ticker = self.proventos.get(ticker, [])

            preco_atual = precos_atuais.get(ticker)

            # Calcula totais
            qtd_total = sum(l.quantidade_atual for l in lotes_ativos)
            custo_total = sum(l.quantidade_atual * l.preco_compra for l in lotes_ativos)

            valor_mercado = qtd_total * preco_atual if preco_atual else 0.0
            lucro_nao_realizado = valor_mercado - custo_total if preco_atual else 0.0
            percentual_nr = ((valor_mercado / custo_total) - 1) * 100 if custo_total > 0 and preco_atual else 0.0

            lucro_realizado = sum(v.lucro_bruto for v in vendas_ticker)
            total_proventos = sum(p.valor_total for p in proventos_ticker)

            analise = AnaliseAtivo(
                ticker=ticker,
                nome=self.nomes.get(ticker, ticker),
                tipo_ativo=self.tipos.get(ticker, TipoAtivo.DESCONHECIDO),
                lotes_ativos=lotes_ativos,
                lotes_encerrados=lotes_encerrados,
                vendas=vendas_ticker,
                proventos=proventos_ticker,
                preco_atual=preco_atual,
                quantidade_total=qtd_total,
                custo_total=custo_total,
                valor_mercado=valor_mercado,
                lucro_nao_realizado=lucro_nao_realizado,
                lucro_realizado=lucro_realizado,
                total_proventos=total_proventos,
                percentual_nao_realizado=percentual_nr,
            )
            resultado[ticker] = analise

        return resultado

    @staticmethod
    def _is_renda_fixa(tipo: TipoAtivo) -> bool:
        return tipo in (TipoAtivo.CDB, TipoAtivo.LCI, TipoAtivo.LCA, TipoAtivo.TESOURO)

    def resumo_carteira(self, precos_atuais: Dict[str, float] = None) -> dict:
        """Retorna resumo geral da carteira, separando renda variável e fixa."""
        analises = self.gerar_analise(precos_atuais)

        # Separar renda variável e renda fixa
        rv = [a for a in analises.values() if not self._is_renda_fixa(a.tipo_ativo)]
        rf = [a for a in analises.values() if self._is_renda_fixa(a.tipo_ativo)]

        # Renda variável
        rv_custo = sum(a.custo_total for a in rv)
        rv_mercado = sum(a.valor_mercado for a in rv)
        rv_lucro_nr = sum(a.lucro_nao_realizado for a in rv)
        rv_lucro_r = sum(a.lucro_realizado for a in rv)
        rv_proventos = sum(a.total_proventos for a in rv)

        # Renda fixa
        rf_ativos = [a for a in rf if a.quantidade_total > 0]
        rf_encerrados = [a for a in rf if a.quantidade_total <= 0 and a.vendas]

        # Aplicado ativo = títulos que ainda estão rendendo
        rf_aplicado_ativo = sum(a.custo_total for a in rf_ativos)

        # Total investido no extrato = aplicações ativas + custo dos encerrados
        # (para encerrados com lotes, o custo_total=0 porque os lotes foram consumidos,
        #  então somamos o custo original via vendas com preco_compra>0)
        rf_investido_total = rf_aplicado_ativo
        for a in rf:
            for lote in a.lotes_encerrados:
                rf_investido_total += lote.quantidade_original * lote.preco_compra

        # Resgates/vencimentos — separar os que têm custo conhecido dos que não têm
        rf_total_resgatado = 0.0
        rf_rendimento_resgates = 0.0
        rf_resgates_sem_custo = 0
        rf_resgatado_sem_custo = 0.0
        for a in rf:
            for v in a.vendas:
                valor_resgate = v.preco_venda * v.quantidade
                rf_total_resgatado += valor_resgate
                if v.preco_compra > 0:
                    rf_rendimento_resgates += v.lucro_bruto
                else:
                    rf_resgates_sem_custo += 1
                    rf_resgatado_sem_custo += valor_resgate

        rf_proventos = sum(a.total_proventos for a in rf)

        # Totais gerais
        custo_total = rv_custo + rf_aplicado_ativo
        valor_mercado = rv_mercado + rf_aplicado_ativo
        lucro_r = rv_lucro_r + rf_rendimento_resgates
        proventos = rv_proventos + rf_proventos

        return {
            "total_ativos": len([a for a in analises.values() if a.quantidade_total > 0]),
            "custo_total": custo_total,
            "valor_mercado": valor_mercado,
            "lucro_nao_realizado": rv_lucro_nr,
            "lucro_realizado": lucro_r,
            "total_proventos": proventos,
            "percentual_nao_realizado": (
                ((rv_mercado / rv_custo) - 1) * 100 if rv_custo > 0 else 0.0
            ),
            "retorno_total": rv_lucro_nr + lucro_r + proventos,
            "rv": {
                "ativos": len([a for a in rv if a.quantidade_total > 0]),
                "custo": rv_custo,
                "mercado": rv_mercado,
                "lucro_nr": rv_lucro_nr,
                "lucro_r": rv_lucro_r,
                "proventos": rv_proventos,
                "pct_nr": ((rv_mercado / rv_custo) - 1) * 100 if rv_custo > 0 else 0.0,
            },
            "rf": {
                "ativos_qtd": len(rf_ativos),
                "encerrados_qtd": len(rf_encerrados),
                "aplicado_ativo": rf_aplicado_ativo,
                "investido_total": rf_investido_total,
                "total_resgatado": rf_total_resgatado,
                "rendimento_resgates": rf_rendimento_resgates,
                "resgates_sem_custo": rf_resgates_sem_custo,
                "resgatado_sem_custo": rf_resgatado_sem_custo,
                "proventos": rf_proventos,
            },
        }
