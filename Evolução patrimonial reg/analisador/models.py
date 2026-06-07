from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from enum import Enum


class TipoMovimentacao(Enum):
    COMPRA = "COMPRA"
    VENDA = "VENDA"
    DIVIDENDO = "DIVIDENDO"
    JCP = "JCP"
    RENDIMENTO = "RENDIMENTO"
    BONIFICACAO = "BONIFICACAO"
    FRACAO = "FRACAO"
    LEILAO_FRACAO = "LEILAO_FRACAO"
    APLICACAO = "APLICACAO"
    RESGATE = "RESGATE"
    VENCIMENTO = "VENCIMENTO"
    ATUALIZACAO = "ATUALIZACAO"
    DIREITO_SUBSCRICAO = "DIREITO_SUBSCRICAO"
    CESSAO_DIREITOS = "CESSAO_DIREITOS"
    CANCELADO = "CANCELADO"
    PAGAMENTO_JUROS = "PAGAMENTO_JUROS"
    IGNORAR = "IGNORAR"


class TipoAtivo(Enum):
    ACAO = "ACAO"
    FII = "FII"
    BDR = "BDR"
    ETF = "ETF"
    CDB = "CDB"
    LCI = "LCI"
    LCA = "LCA"
    TESOURO = "TESOURO"
    DESCONHECIDO = "DESCONHECIDO"


@dataclass
class Transacao:
    data: date
    tipo: TipoMovimentacao
    ticker: str
    nome_completo: str
    instituicao: str
    quantidade: float
    preco_unitario: float
    valor_operacao: float
    tipo_ativo: TipoAtivo = TipoAtivo.DESCONHECIDO

    def __repr__(self):
        return (f"Transacao({self.data}, {self.tipo.value}, {self.ticker}, "
                f"qtd={self.quantidade}, preco={self.preco_unitario}, "
                f"valor={self.valor_operacao})")


@dataclass
class Lote:
    """Um lote individual de compra de um ativo."""
    data_compra: date
    ticker: str
    quantidade_original: float
    quantidade_atual: float
    preco_compra: float
    valor_total_compra: float
    instituicao: str
    tipo_ativo: TipoAtivo = TipoAtivo.DESCONHECIDO

    @property
    def ativo(self) -> bool:
        return self.quantidade_atual > 0.001

    def __repr__(self):
        return (f"Lote({self.data_compra}, {self.ticker}, "
                f"qtd={self.quantidade_atual}/{self.quantidade_original}, "
                f"preco={self.preco_compra})")


@dataclass
class VendaRealizada:
    """Registro de uma venda com referência ao lote original."""
    data_venda: date
    ticker: str
    quantidade: float
    preco_venda: float
    preco_compra: float
    data_compra: date
    lucro_bruto: float
    percentual: float


@dataclass
class ProventoRecebido:
    data: date
    ticker: str
    tipo: str  # Dividendo, JCP, Rendimento
    quantidade_base: float
    valor_por_unidade: float
    valor_total: float


@dataclass
class AnaliseAtivo:
    """Análise consolidada de um ativo."""
    ticker: str
    nome: str
    tipo_ativo: TipoAtivo
    lotes_ativos: list  # List[Lote]
    lotes_encerrados: list  # List[Lote]
    vendas: list  # List[VendaRealizada]
    proventos: list  # List[ProventoRecebido]
    preco_atual: Optional[float] = None
    quantidade_total: float = 0.0
    custo_total: float = 0.0
    valor_mercado: float = 0.0
    lucro_nao_realizado: float = 0.0
    lucro_realizado: float = 0.0
    total_proventos: float = 0.0
    percentual_nao_realizado: float = 0.0
