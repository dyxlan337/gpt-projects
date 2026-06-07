"""
Analisador Patrimonial - Interface Gráfica (CustomTkinter)

Aplicação visual para análise de extratos de investimentos B3/Banco Inter.
Gera relatórios granulares por lote de compra individual (FIFO).
"""

import os
import sys
import threading
from datetime import date, datetime
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional

import customtkinter

# Garante que os módulos do analisador são importáveis
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import AnaliseAtivo, TipoAtivo
from pdf_parser import parse_extrato_b3, parse_csv_manual, parse_xlsx_b3, parse_inter_pdf
from portfolio import Portfolio
from price_fetcher import buscar_precos
from reporter import Reporter


# ── Helpers de formatação ──

def fmt_moeda(valor: float) -> str:
    if valor < 0:
        return f"-R$ {abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_pct(valor: float) -> str:
    sinal = "+" if valor > 0 else ""
    return f"{sinal}{valor:.2f}%"


def fmt_data(d: date) -> str:
    return d.strftime("%d/%m/%Y")


# ── Cores ──

COR_LUCRO = "#2fa572"
COR_PREJUIZO = "#e8524a"
COR_NEUTRO = "#dce4ee"
COR_CARD_BG = "#2b2b2b"
COR_DESTAQUE = "#4a9eff"
COR_RF = "#f0a030"


# ── Widget: Card de resumo ──

class CartaoResumo(customtkinter.CTkFrame):
    """Card exibindo título e valor com cor condicional."""

    def __init__(self, master, titulo: str, valor: str = "—", cor_valor: str = None, **kwargs):
        super().__init__(master, corner_radius=10, **kwargs)

        self.lbl_titulo = customtkinter.CTkLabel(
            self, text=titulo, font=("Segoe UI", 12),
            text_color="gray60",
        )
        self.lbl_titulo.pack(padx=15, pady=(12, 2), anchor="w")

        self.lbl_valor = customtkinter.CTkLabel(
            self, text=valor, font=("Segoe UI", 18, "bold"),
            text_color=cor_valor or COR_NEUTRO,
        )
        self.lbl_valor.pack(padx=15, pady=(0, 12), anchor="w")

    def atualizar(self, valor: str, cor: str = None):
        self.lbl_valor.configure(text=valor, text_color=cor or COR_NEUTRO)


# ── Aplicação principal ──

class AnalisadorApp(customtkinter.CTk):

    def __init__(self):
        super().__init__()
        self.title("Analisador Patrimonial")
        self.geometry("1280x860")
        self.minsize(1050, 700)

        self.arquivo_b3: Optional[str] = None
        self.arquivo_banco: Optional[str] = None
        self.resultado: Optional[dict] = None
        self.reporter: Optional[Reporter] = None
        self._processando = False

        self.buscar_precos_var = customtkinter.BooleanVar(value=True)

        self._criar_widgets()
        self._configurar_estilo_treeview()
        self._mostrar_boas_vindas()

    # ════════════════════════════════════════════════════════════
    #  Criação de widgets
    # ════════════════════════════════════════════════════════════

    def _criar_widgets(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._criar_barra_topo()
        self._criar_area_principal()
        self._criar_barra_inferior()

    def _criar_barra_topo(self):
        frame = customtkinter.CTkFrame(self, corner_radius=10, height=50)
        frame.grid(row=0, column=0, padx=15, pady=(15, 5), sticky="ew")
        frame.grid_columnconfigure(1, weight=1)

        titulo = customtkinter.CTkLabel(
            frame, text="Analisador Patrimonial",
            font=("Segoe UI", 18, "bold"), text_color=COR_DESTAQUE,
        )
        titulo.grid(row=0, column=0, padx=20, pady=12)

        self.lbl_status = customtkinter.CTkLabel(
            frame, text="", text_color="gray50", anchor="e",
        )
        self.lbl_status.grid(row=0, column=1, padx=20, pady=12, sticky="e")

    def _criar_area_principal(self):
        """Cria a área principal que alterna entre boas-vindas e resultados."""
        self.area_principal = customtkinter.CTkFrame(self, fg_color="transparent")
        self.area_principal.grid(row=1, column=0, padx=15, pady=5, sticky="nsew")
        self.area_principal.grid_columnconfigure(0, weight=1)
        self.area_principal.grid_rowconfigure(0, weight=1)

    def _criar_barra_inferior(self):
        frame = customtkinter.CTkFrame(self, corner_radius=10, height=50)
        frame.grid(row=2, column=0, padx=15, pady=(5, 15), sticky="ew")
        frame.grid_columnconfigure(3, weight=1)

        self.btn_csv = customtkinter.CTkButton(
            frame, text="Exportar CSV", width=130, state="disabled",
            command=self._exportar_csv,
        )
        self.btn_csv.grid(row=0, column=0, padx=(15, 8), pady=10)

        self.btn_json = customtkinter.CTkButton(
            frame, text="Exportar JSON", width=130, state="disabled",
            command=self._exportar_json,
        )
        self.btn_json.grid(row=0, column=1, padx=8, pady=10)

        self.btn_voltar = customtkinter.CTkButton(
            frame, text="Nova Análise", width=130,
            fg_color="gray30", hover_color="gray40",
            command=self._mostrar_boas_vindas,
        )
        self.btn_voltar.grid(row=0, column=2, padx=8, pady=10)

        self.progress = customtkinter.CTkProgressBar(frame, width=200)
        self.progress.grid(row=0, column=3, padx=20, pady=10, sticky="e")
        self.progress.set(0)

    # ════════════════════════════════════════════════════════════
    #  Tela de boas-vindas (tutorial + upload)
    # ════════════════════════════════════════════════════════════

    def _mostrar_boas_vindas(self):
        """Exibe a tela inicial com tutorial e seleção de arquivos."""
        self.resultado = None
        self.reporter = None
        self.arquivo_b3 = None
        self.arquivo_banco = None
        self.btn_csv.configure(state="disabled")
        self.btn_json.configure(state="disabled")
        self._status("")

        for w in self.area_principal.winfo_children():
            w.destroy()

        scroll = customtkinter.CTkScrollableFrame(
            self.area_principal, fg_color="transparent",
        )
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        row = 0

        # ── Título ──
        lbl = customtkinter.CTkLabel(
            scroll, text="Bem-vindo ao Analisador Patrimonial",
            font=("Segoe UI", 22, "bold"), text_color=COR_DESTAQUE,
        )
        lbl.grid(row=row, column=0, pady=(25, 5))
        row += 1

        sub = customtkinter.CTkLabel(
            scroll,
            text="Analise sua evolução patrimonial em ações, FIIs e renda fixa com dados reais.",
            font=("Segoe UI", 13), text_color="gray55",
        )
        sub.grid(row=row, column=0, pady=(0, 20))
        row += 1

        # ── Como funciona ──
        tutorial_frame = customtkinter.CTkFrame(scroll, corner_radius=12, fg_color="#1a1a2e")
        tutorial_frame.grid(row=row, column=0, sticky="ew", padx=40, pady=(0, 20))
        tutorial_frame.grid_columnconfigure(0, weight=1)
        row += 1

        lbl_como = customtkinter.CTkLabel(
            tutorial_frame, text="Como funciona?",
            font=("Segoe UI", 15, "bold"), text_color="#ffffff",
        )
        lbl_como.grid(row=0, column=0, sticky="w", padx=25, pady=(18, 8))

        passos = [
            ("1.  Extrato da B3 (XLSX)", (
                "Contém todas as suas operações de Renda Variável (ações, FIIs, BDRs, ETFs),\n"
                "dividendos, JCP, bonificações e desdobramentos.\n"
                "Baixe em: https://www.b3.com.br > Área do Investidor > Extratos > Movimentação"
            ), COR_DESTAQUE),
            ("2.  Relatório do Banco (PDF)  —  opcional", (
                "O extrato da B3 não inclui CDBs, LCIs e LCAs negociados diretamente com o banco.\n"
                "Se você investe em Renda Fixa, importe também o PDF do seu banco.\n"
                "No Inter: Menu > Investimentos > Extrato de Movimentações > Exportar PDF"
            ), COR_RF),
            ("3.  Análise automática", (
                "O app cruza os dados, elimina duplicatas, rastreia cada compra (FIFO),\n"
                "busca preços atuais, e gera relatórios detalhados de lucro, vendas e proventos."
            ), COR_LUCRO),
        ]

        for i, (titulo, desc, cor) in enumerate(passos):
            lbl_t = customtkinter.CTkLabel(
                tutorial_frame, text=titulo,
                font=("Segoe UI", 13, "bold"), text_color=cor,
            )
            lbl_t.grid(row=1 + i * 2, column=0, sticky="w", padx=30, pady=(10, 2))

            lbl_d = customtkinter.CTkLabel(
                tutorial_frame, text=desc,
                font=("Segoe UI", 11), text_color="gray55",
                justify="left", anchor="w",
            )
            lbl_d.grid(row=2 + i * 2, column=0, sticky="w", padx=45, pady=(0, 5))

        customtkinter.CTkLabel(tutorial_frame, text="").grid(row=7, column=0, pady=5)

        # ── Seleção de arquivos ──
        files_frame = customtkinter.CTkFrame(scroll, corner_radius=12)
        files_frame.grid(row=row, column=0, sticky="ew", padx=40, pady=(0, 15))
        files_frame.grid_columnconfigure(1, weight=1)
        row += 1

        lbl_arq = customtkinter.CTkLabel(
            files_frame, text="Selecione seus arquivos",
            font=("Segoe UI", 15, "bold"), text_color="#ffffff",
        )
        lbl_arq.grid(row=0, column=0, columnspan=3, sticky="w", padx=25, pady=(18, 12))

        # Arquivo B3
        btn_b3 = customtkinter.CTkButton(
            files_frame, text="Extrato B3 (.xlsx)",
            width=200, height=38, font=("Segoe UI", 13),
            fg_color="#1a5a8a", hover_color="#2070a8",
            command=self._selecionar_b3,
        )
        btn_b3.grid(row=1, column=0, padx=(25, 10), pady=8)

        self.lbl_b3 = customtkinter.CTkLabel(
            files_frame, text="Nenhum arquivo selecionado",
            text_color="gray45", font=("Segoe UI", 11), anchor="w",
        )
        self.lbl_b3.grid(row=1, column=1, padx=10, pady=8, sticky="w")

        self.btn_limpar_b3 = customtkinter.CTkButton(
            files_frame, text="X", width=32, height=32,
            fg_color="gray30", hover_color="gray40",
            command=self._limpar_b3,
        )
        self.btn_limpar_b3.grid(row=1, column=2, padx=(5, 25), pady=8)

        # Arquivo Banco
        btn_banco = customtkinter.CTkButton(
            files_frame, text="Relatório Banco (.pdf)",
            width=200, height=38, font=("Segoe UI", 13),
            fg_color="#6a4a1a", hover_color="#8a6a2a",
            command=self._selecionar_banco,
        )
        btn_banco.grid(row=2, column=0, padx=(25, 10), pady=8)

        self.lbl_banco = customtkinter.CTkLabel(
            files_frame, text="Opcional — para dados de Renda Fixa completos",
            text_color="gray45", font=("Segoe UI", 11), anchor="w",
        )
        self.lbl_banco.grid(row=2, column=1, padx=10, pady=8, sticky="w")

        self.btn_limpar_banco = customtkinter.CTkButton(
            files_frame, text="X", width=32, height=32,
            fg_color="gray30", hover_color="gray40",
            command=self._limpar_banco,
        )
        self.btn_limpar_banco.grid(row=2, column=2, padx=(5, 25), pady=8)

        # Opção de preço
        chk = customtkinter.CTkCheckBox(
            files_frame, text="Buscar preços atuais online (yfinance)",
            variable=self.buscar_precos_var, font=("Segoe UI", 11),
        )
        chk.grid(row=3, column=0, columnspan=2, padx=25, pady=(12, 5), sticky="w")

        nota_preco = customtkinter.CTkLabel(
            files_frame, text="Necessário para calcular lucro/prejuízo em posições abertas. Pode levar alguns segundos.",
            font=("Segoe UI", 10), text_color="gray40",
        )
        nota_preco.grid(row=4, column=0, columnspan=3, padx=45, pady=(0, 15), sticky="w")

        # Botão Analisar
        self.btn_analisar = customtkinter.CTkButton(
            files_frame, text="ANALISAR",
            width=280, height=48, font=("Segoe UI", 16, "bold"),
            fg_color="#1a7a3a", hover_color="#22a34d",
            command=self._iniciar_analise,
        )
        self.btn_analisar.grid(row=5, column=0, columnspan=3, pady=(5, 22))

    # ════════════════════════════════════════════════════════════
    #  Seleção de arquivos
    # ════════════════════════════════════════════════════════════

    def _selecionar_b3(self):
        caminho = filedialog.askopenfilename(
            title="Selecionar extrato da B3",
            filetypes=[("Excel B3", "*.xlsx"), ("Todos", "*.*")],
        )
        if caminho:
            self.arquivo_b3 = caminho
            self.lbl_b3.configure(
                text=os.path.basename(caminho), text_color=COR_NEUTRO,
            )

    def _selecionar_banco(self):
        caminho = filedialog.askopenfilename(
            title="Selecionar relatório do banco",
            filetypes=[("PDF", "*.pdf"), ("Todos", "*.*")],
        )
        if caminho:
            self.arquivo_banco = caminho
            self.lbl_banco.configure(
                text=os.path.basename(caminho), text_color=COR_NEUTRO,
            )

    def _limpar_b3(self):
        self.arquivo_b3 = None
        self.lbl_b3.configure(text="Nenhum arquivo selecionado", text_color="gray45")

    def _limpar_banco(self):
        self.arquivo_banco = None
        self.lbl_banco.configure(
            text="Opcional — para dados de Renda Fixa completos", text_color="gray45",
        )

    def _configurar_estilo_treeview(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview",
            background="#2b2b2b",
            foreground="#dce4ee",
            fieldbackground="#2b2b2b",
            rowheight=28,
            font=("Segoe UI", 10),
            borderwidth=0,
        )
        style.configure("Treeview.Heading",
            background="#333333",
            foreground="#dce4ee",
            font=("Segoe UI", 10, "bold"),
            borderwidth=0,
        )
        style.map("Treeview",
            background=[("selected", "#1f6aa5")],
            foreground=[("selected", "#ffffff")],
        )

    # ════════════════════════════════════════════════════════════
    #  Análise
    # ════════════════════════════════════════════════════════════

    def _iniciar_analise(self):
        if self._processando:
            return
        if not self.arquivo_b3 and not self.arquivo_banco:
            messagebox.showwarning("Atenção", "Selecione pelo menos um arquivo para analisar.")
            return

        self._processando = True
        self.btn_analisar.configure(state="disabled")
        self.btn_csv.configure(state="disabled")
        self.btn_json.configure(state="disabled")
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self._status("Iniciando análise...")

        thread = threading.Thread(target=self._executar_analise, daemon=True)
        thread.start()

    def _executar_analise(self):
        try:
            todas_transacoes = []

            # Fase 1: Parse dos arquivos
            arquivos = []
            if self.arquivo_b3:
                arquivos.append(self.arquivo_b3)
            if self.arquivo_banco:
                arquivos.append(self.arquivo_banco)

            for i, caminho in enumerate(arquivos):
                nome = os.path.basename(caminho)
                self._status_seguro(f"Lendo {nome}... ({i+1}/{len(arquivos)})")

                if not os.path.exists(caminho):
                    self._status_seguro(f"Arquivo não encontrado: {nome}")
                    continue

                if caminho.lower().endswith(".csv"):
                    transacoes = parse_csv_manual(caminho)
                elif caminho.lower().endswith(".xlsx"):
                    transacoes = parse_xlsx_b3(caminho)
                elif caminho.lower().endswith(".pdf"):
                    if self._is_inter_pdf(caminho):
                        transacoes = parse_inter_pdf(caminho)
                    else:
                        transacoes = parse_extrato_b3(caminho)
                else:
                    transacoes = parse_extrato_b3(caminho)
                todas_transacoes.extend(transacoes)

            # Deduplicação: XLSX para RV, Inter PDF para RF
            todas_transacoes = self._deduplicar_transacoes(todas_transacoes)

            if not todas_transacoes:
                self.after(0, self._erro, "Nenhuma transação encontrada nos arquivos.")
                return

            # Fase 2: Portfólio FIFO
            self._status_seguro(f"Processando {len(todas_transacoes)} transações (FIFO)...")
            portfolio = Portfolio()
            portfolio.processar_transacoes(todas_transacoes)

            # Fase 3: Preços atuais
            precos = {}
            if self.buscar_precos_var.get():
                tickers_ativos = [
                    t for t, lotes in portfolio.lotes.items()
                    if any(l.ativo for l in lotes)
                ]
                if tickers_ativos:
                    self._status_seguro(f"Buscando preços para {len(tickers_ativos)} ativo(s)...")
                    precos = buscar_precos(tickers_ativos, portfolio.tipos)

            # Fase 4: Análise
            self._status_seguro("Gerando análise...")
            analises = portfolio.gerar_analise(precos)
            resumo = portfolio.resumo_carteira(precos)

            resultado = {
                "analises": analises,
                "resumo": resumo,
                "transacoes": todas_transacoes,
                "ignoradas": portfolio.ignoradas,
                "precos": precos,
                "tem_b3": self.arquivo_b3 is not None,
                "tem_banco": self.arquivo_banco is not None,
            }

            self.after(0, self._exibir_resultados, resultado)

        except Exception as e:
            self.after(0, self._erro, f"Erro na análise: {e}")
        finally:
            self.after(0, self._finalizar_processamento)

    @staticmethod
    def _is_inter_pdf(caminho: str) -> bool:
        """Detecta se um PDF é do Banco Inter (vs B3) pela primeira página."""
        import pdfplumber
        try:
            with pdfplumber.open(caminho) as pdf:
                if pdf.pages:
                    text = pdf.pages[0].extract_text() or ""
                    return "Conta" in text and "movimenta" in text.lower()
        except Exception:
            pass
        return False

    @staticmethod
    def _deduplicar_transacoes(transacoes):
        """Remove duplicatas quando B3 XLSX e Inter PDF são usados juntos."""
        inter = [t for t in transacoes if t.instituicao == "INTER"]
        outras = [t for t in transacoes if t.instituicao != "INTER"]

        if not inter or not outras:
            return transacoes

        TIPOS_RF = {TipoAtivo.CDB, TipoAtivo.LCI, TipoAtivo.LCA, TipoAtivo.TESOURO}
        TIPOS_RV = {TipoAtivo.ACAO, TipoAtivo.FII, TipoAtivo.BDR, TipoAtivo.ETF}

        resultado = []
        for t in outras:
            if t.tipo_ativo in TIPOS_RF:
                continue
            resultado.append(t)
        for t in inter:
            if t.tipo_ativo in TIPOS_RV:
                continue
            resultado.append(t)

        return resultado

    def _finalizar_processamento(self):
        self._processando = False
        self.btn_analisar.configure(state="normal")
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(1.0 if self.resultado else 0)

    # ════════════════════════════════════════════════════════════
    #  Exibição de resultados
    # ════════════════════════════════════════════════════════════

    def _exibir_resultados(self, resultado):
        self.resultado = resultado
        self.reporter = Reporter(resultado["analises"], resultado["resumo"])

        self.btn_csv.configure(state="normal")
        self.btn_json.configure(state="normal")

        # Limpa área e cria abas
        for w in self.area_principal.winfo_children():
            w.destroy()

        self.tabview = customtkinter.CTkTabview(self.area_principal, corner_radius=10)
        self.tabview.grid(row=0, column=0, sticky="nsew")

        # Abas RV (foco principal)
        self.tab_resumo = self.tabview.add("Resumo")
        self.tab_posicoes = self.tabview.add("Posições")
        self.tab_lotes = self.tabview.add("Lotes")
        self.tab_vendas = self.tabview.add("Vendas")
        self.tab_proventos = self.tabview.add("Proventos")
        self.tab_ranking = self.tabview.add("Ranking")
        # Aba RF (secundária)
        self.tab_renda_fixa = self.tabview.add("Renda Fixa")

        for tab in [self.tab_resumo, self.tab_posicoes, self.tab_lotes,
                     self.tab_vendas, self.tab_proventos, self.tab_ranking,
                     self.tab_renda_fixa]:
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(0, weight=1)

        # Popular abas
        self._popular_resumo(resultado["resumo"], resultado)
        self._popular_posicoes(resultado["analises"])
        self._popular_lotes(resultado["analises"])
        self._popular_vendas(resultado["analises"])
        self._popular_proventos(resultado["analises"])
        self._popular_ranking(resultado["analises"])
        self._popular_renda_fixa(resultado["analises"], resultado["resumo"], resultado)

        n_trans = len(resultado["transacoes"])
        n_ativos = resultado["resumo"].get("total_ativos", 0)
        n_precos = len(resultado["precos"])
        self._status(f"Concluído: {n_trans} transações, {n_ativos} ativos, {n_precos} preços")

        self.tabview.set("Resumo")

    # ── Tab: Resumo (RV) ──

    def _popular_resumo(self, resumo: dict, resultado: dict):
        scroll = customtkinter.CTkScrollableFrame(self.tab_resumo, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        scroll.grid_columnconfigure((0, 1, 2), weight=1)

        row = 0

        # Cabeçalho
        lbl = customtkinter.CTkLabel(
            scroll, text="Renda Variável — Visão Geral",
            font=("Segoe UI", 16, "bold"), text_color=COR_DESTAQUE,
        )
        lbl.grid(row=row, column=0, columnspan=3, sticky="w", padx=12, pady=(12, 3))
        row += 1

        desc = customtkinter.CTkLabel(
            scroll,
            text="Ações, FIIs, BDRs e ETFs — posições abertas, lucro realizado e proventos recebidos.",
            font=("Segoe UI", 11), text_color="gray50",
        )
        desc.grid(row=row, column=0, columnspan=3, sticky="w", padx=12, pady=(0, 12))
        row += 1

        rv = resumo.get("rv", {})
        rv_custo = rv.get("custo", 0)
        rv_mercado = rv.get("mercado", 0)
        rv_lucro_nr = rv.get("lucro_nr", 0)
        rv_pct = rv.get("pct_nr", 0)
        rv_lucro_r = rv.get("lucro_r", 0)
        rv_proventos = rv.get("proventos", 0)
        retorno_rv = rv_lucro_r + rv_proventos

        cards = [
            ("Ativos em Carteira",
             "Quantidade de ações/FIIs que você possui atualmente.",
             str(rv.get("ativos", 0)), None),
            ("Custo Total",
             "Quanto você pagou pelas posições que ainda tem em carteira.",
             fmt_moeda(rv_custo), None),
            ("Valor de Mercado",
             "Quanto suas posições valem hoje (preço atual x quantidade).",
             fmt_moeda(rv_mercado),
             COR_LUCRO if rv_mercado > rv_custo else COR_PREJUIZO if rv_mercado < rv_custo else None),
            ("Lucro Não Realizado",
             "Ganho ou perda das posições que você ainda NÃO vendeu.",
             f"{fmt_moeda(rv_lucro_nr)}  ({fmt_pct(rv_pct)})",
             COR_LUCRO if rv_lucro_nr > 0 else COR_PREJUIZO if rv_lucro_nr < 0 else None),
            ("Lucro Realizado",
             "Ganho ou perda das posições que você já vendeu.",
             fmt_moeda(rv_lucro_r),
             COR_LUCRO if rv_lucro_r > 0 else COR_PREJUIZO if rv_lucro_r < 0 else None),
            ("Proventos Recebidos",
             "Total de dividendos e JCP (juros sobre capital próprio) recebidos.",
             fmt_moeda(rv_proventos),
             COR_LUCRO if rv_proventos > 0 else None),
        ]

        for i, (titulo, dica, valor, cor) in enumerate(cards):
            card = CartaoResumo(scroll, titulo, valor, cor)
            card.grid(row=row + i // 3, column=i % 3, padx=10, pady=8, sticky="nsew")
        row += 2

        # Retorno total
        sep = customtkinter.CTkFrame(scroll, height=1, fg_color="gray30")
        sep.grid(row=row, column=0, columnspan=3, sticky="ew", padx=12, pady=(15, 10))
        row += 1

        lbl_ret = customtkinter.CTkLabel(
            scroll, text="Retorno Total (RV)",
            font=("Segoe UI", 14, "bold"), text_color="#ffffff",
        )
        lbl_ret.grid(row=row, column=0, columnspan=3, sticky="w", padx=12, pady=(0, 3))
        row += 1

        desc_ret = customtkinter.CTkLabel(
            scroll, text="Soma do lucro de vendas realizadas + proventos recebidos.",
            font=("Segoe UI", 11), text_color="gray50",
        )
        desc_ret.grid(row=row, column=0, columnspan=3, sticky="w", padx=12, pady=(0, 8))
        row += 1

        n_trans = len(resultado["transacoes"])
        n_ign = len(resultado["ignoradas"])

        cards_ret = [
            ("Retorno RV", fmt_moeda(retorno_rv),
             COR_LUCRO if retorno_rv > 0 else COR_PREJUIZO if retorno_rv < 0 else None),
            ("Transações", f"{n_trans} processadas / {n_ign} ignoradas", None),
        ]

        for i, (titulo, valor, cor) in enumerate(cards_ret):
            card = CartaoResumo(scroll, titulo, valor, cor)
            card.grid(row=row, column=i, padx=10, pady=8, sticky="nsew")
        row += 1

        # Indicador de RF
        rf = resumo.get("rf", {})
        if rf.get("ativos_qtd", 0) > 0:
            nota_rf = customtkinter.CTkLabel(
                scroll,
                text=f"Renda Fixa: {rf['ativos_qtd']} título(s) ativo(s) — veja aba 'Renda Fixa'",
                font=("Segoe UI", 11), text_color="gray45",
            )
            nota_rf.grid(row=row, column=0, columnspan=3, sticky="w", padx=15, pady=(12, 0))

    # ── Tab: Posições (RV) ──

    def _popular_posicoes(self, analises: Dict[str, AnaliseAtivo]):
        from models import TipoAtivo as TA
        _rf_tipos = (TA.CDB, TA.LCI, TA.LCA, TA.TESOURO)

        scroll = customtkinter.CTkScrollableFrame(self.tab_posicoes, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        scroll.grid_columnconfigure(0, weight=1)

        rv_items = {t: a for t, a in analises.items()
                     if a.quantidade_total > 0 and a.tipo_ativo not in _rf_tipos}

        lbl = customtkinter.CTkLabel(
            scroll, text="Posições Abertas",
            font=("Segoe UI", 14, "bold"), text_color=COR_DESTAQUE,
        )
        lbl.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 3))

        desc = customtkinter.CTkLabel(
            scroll, text="Ativos que você possui atualmente. PM = Preço Médio de compra.",
            font=("Segoe UI", 11), text_color="gray50",
        )
        desc.grid(row=1, column=0, sticky="w", padx=12, pady=(0, 8))

        colunas = ("Ticker", "Tipo", "Qtd", "PM Compra", "Preço Atual",
                    "Valor Mercado", "Lucro/Prejuízo", "%")
        tree = self._criar_treeview(scroll, colunas,
                                     larguras=[80, 60, 70, 100, 100, 120, 130, 80], row=2)

        for ticker, a in sorted(rv_items.items()):
            pm = fmt_moeda(a.custo_total / a.quantidade_total) if a.quantidade_total > 0 else "—"
            preco = fmt_moeda(a.preco_atual) if a.preco_atual else "N/D"
            vmercado = fmt_moeda(a.valor_mercado) if a.preco_atual else "N/D"
            lucro = fmt_moeda(a.lucro_nao_realizado) if a.preco_atual else "N/D"
            pct = fmt_pct(a.percentual_nao_realizado) if a.preco_atual else "N/D"

            tag = "neutro"
            if a.preco_atual and a.lucro_nao_realizado > 0.01:
                tag = "lucro"
            elif a.preco_atual and a.lucro_nao_realizado < -0.01:
                tag = "prejuizo"

            tree.insert("", "end", values=(
                ticker, a.tipo_ativo.value, f"{a.quantidade_total:.0f}",
                pm, preco, vmercado, lucro, pct,
            ), tags=(tag,))

        if not rv_items:
            lbl_vazio = customtkinter.CTkLabel(
                scroll, text="Nenhuma posição aberta em renda variável.",
                text_color="gray50", font=("Segoe UI", 14),
            )
            lbl_vazio.grid(row=3, column=0, pady=30)

    # ── Tab: Lotes Detalhados (RV) ──

    def _popular_lotes(self, analises: Dict[str, AnaliseAtivo]):
        from models import TipoAtivo as TA
        _rf_tipos = (TA.CDB, TA.LCI, TA.LCA, TA.TESOURO)

        scroll = customtkinter.CTkScrollableFrame(self.tab_lotes, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        scroll.grid_columnconfigure(0, weight=1)

        rv_analises = {t: a for t, a in analises.items()
                       if a.tipo_ativo not in _rf_tipos and a.lotes_ativos}

        lbl = customtkinter.CTkLabel(
            scroll, text="Lotes de Compra (FIFO)",
            font=("Segoe UI", 14, "bold"), text_color=COR_DESTAQUE,
        )
        lbl.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 3))

        desc = customtkinter.CTkLabel(
            scroll, text="Cada compra individual que você fez, com lucro/prejuízo calculado pelo preço atual.",
            font=("Segoe UI", 11), text_color="gray50",
        )
        desc.grid(row=1, column=0, sticky="w", padx=12, pady=(0, 8))

        colunas = ("Ticker", "Data Compra", "Qtd Atual/Orig", "Preço Compra",
                    "Preço Atual", "Custo Posição", "Lucro/Prejuízo", "%", "Instituição")

        # Usar frame diretamente (sem scroll extra) para hierarquia
        frame_tree = customtkinter.CTkFrame(scroll, fg_color="transparent")
        frame_tree.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)
        frame_tree.grid_columnconfigure(0, weight=1)
        frame_tree.grid_rowconfigure(0, weight=1)

        tree = ttk.Treeview(frame_tree, columns=colunas, show="tree headings", selectmode="browse")
        tree.column("#0", width=30, minwidth=20, stretch=False)
        tree.heading("#0", text="")

        larguras = [80, 100, 100, 100, 100, 110, 130, 80, 120]
        for i, col in enumerate(colunas):
            w = larguras[i] if i < len(larguras) else 100
            tree.column(col, width=w, minwidth=50, anchor="e")
            tree.heading(col, text=col,
                         command=lambda c=col: self._ordenar_coluna(tree, c, False))

        scrollbar = ttk.Scrollbar(frame_tree, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        tree.tag_configure("lucro", foreground=COR_LUCRO)
        tree.tag_configure("prejuizo", foreground=COR_PREJUIZO)
        tree.tag_configure("neutro", foreground=COR_NEUTRO)
        tree.tag_configure("pai", foreground="#87CEEB", font=("Segoe UI", 10, "bold"))

        for ticker, a in sorted(rv_analises.items()):
            pai = tree.insert("", "end", text="", values=(
                f"► {ticker} — {a.nome[:40]}", "", f"Total: {a.quantidade_total:.0f}", "",
                fmt_moeda(a.preco_atual) if a.preco_atual else "N/D",
                fmt_moeda(a.custo_total),
                fmt_moeda(a.lucro_nao_realizado) if a.preco_atual else "N/D",
                fmt_pct(a.percentual_nao_realizado) if a.preco_atual else "N/D",
                "",
            ), open=True, tags=("pai",))

            for lote in sorted(a.lotes_ativos, key=lambda l: l.data_compra):
                preco_atual = a.preco_atual
                custo = lote.quantidade_atual * lote.preco_compra
                if preco_atual:
                    lucro = (preco_atual - lote.preco_compra) * lote.quantidade_atual
                    pct = ((preco_atual / lote.preco_compra) - 1) * 100 if lote.preco_compra > 0 else 0
                else:
                    lucro = None
                    pct = None

                tag = "neutro"
                if lucro is not None and lucro > 0.01:
                    tag = "lucro"
                elif lucro is not None and lucro < -0.01:
                    tag = "prejuizo"

                tree.insert(pai, "end", values=(
                    "",
                    fmt_data(lote.data_compra),
                    f"{lote.quantidade_atual:.0f}/{lote.quantidade_original:.0f}",
                    fmt_moeda(lote.preco_compra),
                    fmt_moeda(preco_atual) if preco_atual else "N/D",
                    fmt_moeda(custo),
                    fmt_moeda(lucro) if lucro is not None else "N/D",
                    fmt_pct(pct) if pct is not None else "N/D",
                    lote.instituicao or "",
                ), tags=(tag,))

        if not rv_analises:
            lbl_vazio = customtkinter.CTkLabel(
                scroll, text="Nenhum lote ativo em renda variável.",
                text_color="gray50", font=("Segoe UI", 14),
            )
            lbl_vazio.grid(row=3, column=0, pady=30)

    # ── Tab: Vendas Realizadas (RV) ──

    def _popular_vendas(self, analises: Dict[str, AnaliseAtivo]):
        from models import TipoAtivo as TA
        _rf_tipos = (TA.CDB, TA.LCI, TA.LCA, TA.TESOURO)

        scroll = customtkinter.CTkScrollableFrame(self.tab_vendas, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        scroll.grid_columnconfigure(0, weight=1)

        lbl = customtkinter.CTkLabel(
            scroll, text="Vendas Realizadas",
            font=("Segoe UI", 14, "bold"), text_color=COR_DESTAQUE,
        )
        lbl.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 3))

        desc = customtkinter.CTkLabel(
            scroll,
            text="Histórico de todas as vendas de ações e FIIs, com lucro/prejuízo calculado pelo FIFO.",
            font=("Segoe UI", 11), text_color="gray50",
        )
        desc.grid(row=1, column=0, sticky="w", padx=12, pady=(0, 8))

        colunas = ("Data Venda", "Ticker", "Qtd", "Preço Compra", "Data Compra",
                    "Preço Venda", "Lucro Bruto", "%")
        tree = self._criar_treeview(scroll, colunas,
                                     larguras=[100, 80, 70, 100, 100, 100, 130, 80], row=2)

        todas_vendas = []
        for ticker, a in analises.items():
            if a.tipo_ativo in _rf_tipos:
                continue
            for v in a.vendas:
                todas_vendas.append((ticker, v))
        todas_vendas.sort(key=lambda x: x[1].data_venda)

        for ticker, v in todas_vendas:
            tag = "lucro" if v.lucro_bruto > 0.01 else "prejuizo" if v.lucro_bruto < -0.01 else "neutro"
            tree.insert("", "end", values=(
                fmt_data(v.data_venda), ticker, f"{v.quantidade:.0f}",
                fmt_moeda(v.preco_compra), fmt_data(v.data_compra),
                fmt_moeda(v.preco_venda), fmt_moeda(v.lucro_bruto),
                fmt_pct(v.percentual),
            ), tags=(tag,))

        if not todas_vendas:
            lbl_vazio = customtkinter.CTkLabel(
                scroll, text="Nenhuma venda de RV registrada.",
                text_color="gray50", font=("Segoe UI", 14),
            )
            lbl_vazio.grid(row=3, column=0, pady=30)

    # ── Tab: Proventos ──

    def _popular_proventos(self, analises: Dict[str, AnaliseAtivo]):
        scroll = customtkinter.CTkScrollableFrame(self.tab_proventos, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        scroll.grid_columnconfigure(0, weight=1)

        lbl = customtkinter.CTkLabel(
            scroll, text="Proventos Recebidos",
            font=("Segoe UI", 14, "bold"), text_color=COR_DESTAQUE,
        )
        lbl.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 3))

        desc = customtkinter.CTkLabel(
            scroll,
            text="Dividendos e JCP (Juros sobre Capital Próprio) pagos pelas empresas que você possui ou já possuiu.",
            font=("Segoe UI", 11), text_color="gray50",
        )
        desc.grid(row=1, column=0, sticky="w", padx=12, pady=(0, 8))

        colunas = ("Data", "Ticker", "Tipo", "Valor")
        tree = self._criar_treeview(scroll, colunas,
                                     larguras=[100, 80, 100, 120], row=2)

        todos = []
        for ticker, a in analises.items():
            for p in a.proventos:
                todos.append((ticker, p))
        todos.sort(key=lambda x: x[1].data)

        total = 0.0
        for ticker, p in todos:
            tree.insert("", "end", values=(
                fmt_data(p.data), ticker, p.tipo, fmt_moeda(p.valor_total),
            ), tags=("lucro",))
            total += p.valor_total

        if todos:
            lbl_total = customtkinter.CTkLabel(
                scroll,
                text=f"Total de proventos recebidos: {fmt_moeda(total)}",
                font=("Segoe UI", 14, "bold"), text_color=COR_LUCRO,
            )
            lbl_total.grid(row=3, column=0, pady=(8, 12), sticky="w", padx=15)
        else:
            lbl_vazio = customtkinter.CTkLabel(
                scroll, text="Nenhum provento registrado.",
                text_color="gray50", font=("Segoe UI", 14),
            )
            lbl_vazio.grid(row=3, column=0, pady=30)

    # ── Tab: Ranking ──

    def _popular_ranking(self, analises: Dict[str, AnaliseAtivo]):
        from models import TipoAtivo as TA
        _rf_tipos = (TA.CDB, TA.LCI, TA.LCA, TA.TESOURO)

        # Coleta lotes com preço
        lotes_com_preco = []
        for ticker, a in analises.items():
            if a.tipo_ativo in _rf_tipos or not a.preco_atual:
                continue
            for lote in a.lotes_ativos:
                pct = ((a.preco_atual / lote.preco_compra) - 1) * 100 if lote.preco_compra > 0 else 0
                lucro = (a.preco_atual - lote.preco_compra) * lote.quantidade_atual
                lotes_com_preco.append((ticker, lote, pct, lucro))

        scroll = customtkinter.CTkScrollableFrame(self.tab_ranking, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        scroll.grid_columnconfigure(0, weight=1)

        lbl = customtkinter.CTkLabel(
            scroll, text="Ranking de Compras e Vendas",
            font=("Segoe UI", 14, "bold"), text_color=COR_DESTAQUE,
        )
        lbl.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 3))

        desc = customtkinter.CTkLabel(
            scroll,
            text="Suas melhores e piores compras individuais, baseado no preço atual de mercado.",
            font=("Segoe UI", 11), text_color="gray50",
        )
        desc.grid(row=1, column=0, sticky="w", padx=12, pady=(0, 12))

        next_row = 2

        if lotes_com_preco:
            # Top 10 Melhores
            lbl_m = customtkinter.CTkLabel(scroll, text="TOP 10 Melhores Compras (por % ganho)",
                                            font=("Segoe UI", 13, "bold"), text_color=COR_LUCRO)
            lbl_m.grid(row=next_row, column=0, sticky="w", padx=12, pady=(5, 5))
            next_row += 1

            colunas = ("Ticker", "Data Compra", "Qtd", "Preço Compra", "Retorno %", "Lucro R$")
            tree_m = self._criar_treeview(scroll, colunas,
                                           larguras=[80, 100, 70, 100, 90, 120], row=next_row)
            next_row += 1

            melhores = sorted(lotes_com_preco, key=lambda x: x[2], reverse=True)[:10]
            for ticker, lote, pct, lucro in melhores:
                tree_m.insert("", "end", values=(
                    ticker, fmt_data(lote.data_compra), f"{lote.quantidade_atual:.0f}",
                    fmt_moeda(lote.preco_compra), fmt_pct(pct), fmt_moeda(lucro),
                ), tags=("lucro",))

            # Top 10 Piores
            lbl_p = customtkinter.CTkLabel(scroll, text="TOP 10 Piores Compras (por % perda)",
                                            font=("Segoe UI", 13, "bold"), text_color=COR_PREJUIZO)
            lbl_p.grid(row=next_row, column=0, sticky="w", padx=12, pady=(20, 5))
            next_row += 1

            tree_p = self._criar_treeview(scroll, colunas,
                                           larguras=[80, 100, 70, 100, 90, 120], row=next_row)
            next_row += 1

            piores = sorted(lotes_com_preco, key=lambda x: x[2])[:10]
            for ticker, lote, pct, lucro in piores:
                tag = "prejuizo" if lucro < 0 else "lucro"
                tree_p.insert("", "end", values=(
                    ticker, fmt_data(lote.data_compra), f"{lote.quantidade_atual:.0f}",
                    fmt_moeda(lote.preco_compra), fmt_pct(pct), fmt_moeda(lucro),
                ), tags=(tag,))
        else:
            lbl_sem = customtkinter.CTkLabel(
                scroll, text="Sem dados de preço atual para ranking de compras.",
                text_color="gray50", font=("Segoe UI", 12),
            )
            lbl_sem.grid(row=next_row, column=0, pady=15, padx=12, sticky="w")
            next_row += 1

        # ── Histórico de Vendas por Ativo ──
        vendas_por_ticker = {}
        for ticker, a in analises.items():
            if a.tipo_ativo in _rf_tipos or not a.vendas:
                continue
            lucro_vendas = sum(v.lucro_bruto for v in a.vendas)
            total_vendido = sum(v.preco_venda * v.quantidade for v in a.vendas)
            total_comprado = sum(v.preco_compra * v.quantidade for v in a.vendas)
            resultado = lucro_vendas + a.total_proventos
            vendas_por_ticker[ticker] = {
                "lucro_vendas": lucro_vendas,
                "proventos": a.total_proventos,
                "resultado": resultado,
                "total_vendido": total_vendido,
                "total_comprado": total_comprado,
                "n_ops": len(a.vendas),
                "tipo": a.tipo_ativo.value,
                "ativo": a.quantidade_total > 0,
            }

        if vendas_por_ticker:
            sep = customtkinter.CTkFrame(scroll, height=1, fg_color="gray30")
            sep.grid(row=next_row, column=0, sticky="ew", padx=12, pady=(20, 10))
            next_row += 1

            lbl_hist = customtkinter.CTkLabel(
                scroll, text="Histórico de Vendas por Ativo",
                font=("Segoe UI", 14, "bold"), text_color="#b090ff",
            )
            lbl_hist.grid(row=next_row, column=0, sticky="w", padx=12, pady=(5, 3))
            next_row += 1

            desc_hist = customtkinter.CTkLabel(
                scroll,
                text="Resultado consolidado de cada ativo que teve vendas: lucro das vendas + proventos recebidos.",
                font=("Segoe UI", 11), text_color="gray50",
            )
            desc_hist.grid(row=next_row, column=0, sticky="w", padx=12, pady=(0, 8))
            next_row += 1

            colunas_h = ("Ticker", "Tipo", "Ops", "Custo", "Venda", "Lucro Vendas", "Proventos", "Resultado", "Status")
            tree_h = self._criar_treeview(scroll, colunas_h,
                                           larguras=[80, 50, 40, 100, 100, 110, 90, 110, 80], row=next_row)

            for ticker, info in sorted(vendas_por_ticker.items(), key=lambda x: x[1]["resultado"], reverse=True):
                tag = "lucro" if info["resultado"] > 0 else "prejuizo" if info["resultado"] < 0 else "neutro"
                status = "Em carteira" if info["ativo"] else "Encerrado"
                tree_h.insert("", "end", values=(
                    ticker, info["tipo"], info["n_ops"],
                    fmt_moeda(info["total_comprado"]),
                    fmt_moeda(info["total_vendido"]),
                    fmt_moeda(info["lucro_vendas"]),
                    fmt_moeda(info["proventos"]),
                    fmt_moeda(info["resultado"]),
                    status,
                ), tags=(tag,))

    # ── Tab: Renda Fixa ──

    def _popular_renda_fixa(self, analises: Dict[str, AnaliseAtivo], resumo: dict, resultado: dict):
        from models import TipoAtivo as TA
        _rf_tipos = (TA.CDB, TA.LCI, TA.LCA, TA.TESOURO)

        scroll = customtkinter.CTkScrollableFrame(self.tab_renda_fixa, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        scroll.grid_columnconfigure(0, weight=1)

        row = 0

        # Título
        lbl = customtkinter.CTkLabel(
            scroll, text="Renda Fixa — CDB / LCI / LCA / Tesouro",
            font=("Segoe UI", 16, "bold"), text_color=COR_RF,
        )
        lbl.grid(row=row, column=0, sticky="w", padx=12, pady=(12, 3))
        row += 1

        desc = customtkinter.CTkLabel(
            scroll,
            text="Títulos de renda fixa: aplicações, resgates e vencimentos.",
            font=("Segoe UI", 11), text_color="gray50",
        )
        desc.grid(row=row, column=0, sticky="w", padx=12, pady=(0, 12))
        row += 1

        # ── Notas explicativas sobre fontes de dados ──
        tem_b3 = resultado.get("tem_b3", False)
        tem_banco = resultado.get("tem_banco", False)

        notas_frame = customtkinter.CTkFrame(scroll, corner_radius=10, fg_color="#1e1e2e")
        notas_frame.grid(row=row, column=0, sticky="ew", padx=10, pady=(0, 15))
        notas_frame.grid_columnconfigure(0, weight=1)
        row += 1

        lbl_info = customtkinter.CTkLabel(
            notas_frame, text="Sobre os dados de Renda Fixa",
            font=("Segoe UI", 13, "bold"), text_color=COR_RF,
        )
        lbl_info.grid(row=0, column=0, sticky="w", padx=20, pady=(15, 5))

        if tem_b3 and tem_banco:
            notas = [
                "Dados de RF vindos do relatório do Banco Inter (fonte mais completa).",
                "Dados de RV (ações/FIIs) vindos do extrato da B3.",
                "",
                "Por que dois arquivos?",
                "O extrato da B3 NÃO inclui CDBs negociados diretamente com o banco emissor.",
                "Apenas CDBs comprados via plataformas de terceiros (XP, Rico, etc.) aparecem na B3.",
                "O relatório do banco tem todos os títulos, incluindo os que não passam pela B3.",
            ]
        elif tem_banco:
            notas = [
                "Dados vindos do relatório do Banco Inter.",
                "Para dados completos de Renda Variável, importe também o extrato da B3 (XLSX).",
            ]
        else:
            notas = [
                "Dados de RF vindos apenas do extrato da B3 (XLSX).",
                "",
                "Atenção: dados possivelmente incompletos!",
                "O extrato da B3 NÃO inclui CDBs negociados diretamente com o banco emissor.",
                "Se você investe em CDB/LCI/LCA pelo banco, os dados abaixo podem estar faltando.",
                "Para dados completos, importe também o relatório PDF do seu banco.",
            ]

        nota_row = 1
        for nota in notas:
            if nota == "":
                customtkinter.CTkLabel(notas_frame, text="").grid(row=nota_row, column=0, pady=2)
                nota_row += 1
                continue

            is_destaque = nota.startswith("Por que") or nota.startswith("Atenção")
            lbl_n = customtkinter.CTkLabel(
                notas_frame, text=f"  {nota}",
                font=("Segoe UI", 11, "bold" if is_destaque else "normal"),
                text_color=COR_RF if is_destaque else "gray50",
                anchor="w", wraplength=900, justify="left",
            )
            lbl_n.grid(row=nota_row, column=0, sticky="w", padx=20, pady=1)
            nota_row += 1

        customtkinter.CTkLabel(notas_frame, text="").grid(row=nota_row, column=0, pady=5)

        # ── Cards de resumo RF ──
        rf = resumo.get("rf", {})
        cards_frame = customtkinter.CTkFrame(scroll, fg_color="transparent")
        cards_frame.grid(row=row, column=0, sticky="ew", padx=5, pady=(0, 10))
        cards_frame.grid_columnconfigure((0, 1, 2), weight=1)
        row += 1

        rf_ativos_qtd = rf.get("ativos_qtd", 0)
        rf_encerrados = rf.get("encerrados_qtd", 0)
        rf_aplicado = rf.get("aplicado_ativo", 0)
        rf_investido = rf.get("investido_total", 0)
        rf_resgatado = rf.get("total_resgatado", 0)
        rf_rendimento = rf.get("rendimento_resgates", 0)

        cards_rf = [
            ("Títulos Ativos", "Títulos de RF que estão rendendo atualmente.",
             str(rf_ativos_qtd), None),
            ("Títulos Encerrados", "Títulos já vencidos ou resgatados.",
             str(rf_encerrados), None),
            ("Aplicado (ativo)", "Quanto você tem aplicado em títulos que ainda estão rendendo.",
             fmt_moeda(rf_aplicado), COR_LUCRO if rf_aplicado > 0 else None),
            ("Total Investido", "Soma de tudo que você já aplicou em RF (ativo + encerrado).",
             fmt_moeda(rf_investido), None),
            ("Total Resgatado", "Soma de tudo que já foi resgatado ou venceu.",
             fmt_moeda(rf_resgatado), None),
            ("Rendimento", "Lucro obtido nos resgates (valor resgatado - valor aplicado).",
             fmt_moeda(rf_rendimento),
             COR_LUCRO if rf_rendimento > 0 else COR_PREJUIZO if rf_rendimento < 0 else None),
        ]

        for i, (titulo, dica, valor, cor) in enumerate(cards_rf):
            card = CartaoResumo(cards_frame, titulo, valor, cor)
            card.grid(row=i // 3, column=i % 3, padx=10, pady=8, sticky="nsew")

        # ── Títulos Ativos (tabela) ──
        rf_ativos = {t: a for t, a in analises.items()
                      if a.quantidade_total > 0 and a.tipo_ativo in _rf_tipos}

        if rf_ativos:
            lbl_at = customtkinter.CTkLabel(
                scroll, text="Títulos Ativos (rendendo)",
                font=("Segoe UI", 13, "bold"), text_color=COR_RF,
            )
            lbl_at.grid(row=row, column=0, sticky="w", padx=12, pady=(15, 5))
            row += 1

            colunas = ("Título", "Tipo", "Data Aplicação", "Valor Aplicado")
            tree_at = self._criar_treeview(scroll, colunas,
                                            larguras=[300, 60, 120, 140], row=row)
            row += 1

            for ticker, a in sorted(rf_ativos.items()):
                data_aplic = fmt_data(a.lotes_ativos[0].data_compra) if a.lotes_ativos else ""
                tree_at.insert("", "end", values=(
                    ticker, a.tipo_ativo.value, data_aplic, fmt_moeda(a.custo_total),
                ), tags=("lucro",))

        # ── Títulos Resgatados (tabela) ──
        rf_resgatados = {t: a for t, a in analises.items()
                          if a.quantidade_total <= 0 and a.tipo_ativo in _rf_tipos and a.vendas}

        if rf_resgatados:
            lbl_res = customtkinter.CTkLabel(
                scroll, text="Títulos Resgatados / Vencidos",
                font=("Segoe UI", 13, "bold"), text_color="gray60",
            )
            lbl_res.grid(row=row, column=0, sticky="w", padx=12, pady=(15, 5))
            row += 1

            colunas_res = ("Título", "Tipo", "Valor Resgatado", "Rendimento")
            tree_res = self._criar_treeview(scroll, colunas_res,
                                             larguras=[300, 60, 140, 140], row=row)
            row += 1

            for ticker, a in sorted(rf_resgatados.items()):
                total_resgate = sum(v.preco_venda * v.quantidade for v in a.vendas)
                vendas_com_custo = [v for v in a.vendas if v.preco_compra > 0]
                if vendas_com_custo:
                    rend = sum(v.lucro_bruto for v in vendas_com_custo)
                    rend_txt = fmt_moeda(rend)
                    tag = "lucro" if rend > 0 else "prejuizo" if rend < 0 else "neutro"
                else:
                    rend_txt = "N/D*"
                    tag = "neutro"

                tree_res.insert("", "end", values=(
                    ticker, a.tipo_ativo.value, fmt_moeda(total_resgate), rend_txt,
                ), tags=(tag,))

            # Nota sobre N/D
            if any(not [v for v in a.vendas if v.preco_compra > 0] for a in rf_resgatados.values()):
                lbl_nd = customtkinter.CTkLabel(
                    scroll,
                    text="* N/D = Título aplicado antes do período do extrato (valor original desconhecido).",
                    font=("Segoe UI", 10), text_color="gray40",
                )
                lbl_nd.grid(row=row, column=0, sticky="w", padx=15, pady=(3, 5))

        if not rf_ativos and not rf_resgatados:
            lbl_vazio = customtkinter.CTkLabel(
                scroll,
                text="Nenhum título de renda fixa encontrado.\nImporte o relatório do banco para ver seus CDBs, LCIs e LCAs.",
                text_color="gray50", font=("Segoe UI", 14), justify="center",
            )
            lbl_vazio.grid(row=row, column=0, pady=30)

    # ════════════════════════════════════════════════════════════
    #  Helpers de Treeview
    # ════════════════════════════════════════════════════════════

    def _criar_treeview(self, parent, colunas, larguras=None, row=0):
        """Cria um Treeview estilizado dentro de um frame."""
        frame = customtkinter.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="nsew", padx=5, pady=5)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)

        tree = ttk.Treeview(frame, columns=colunas, show="tree headings", selectmode="browse")

        tree.column("#0", width=30, minwidth=20, stretch=False)
        tree.heading("#0", text="")

        for i, col in enumerate(colunas):
            w = larguras[i] if larguras and i < len(larguras) else 100
            tree.column(col, width=w, minwidth=50, anchor="e")
            tree.heading(col, text=col,
                         command=lambda c=col: self._ordenar_coluna(tree, c, False))

        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        tree.tag_configure("lucro", foreground=COR_LUCRO)
        tree.tag_configure("prejuizo", foreground=COR_PREJUIZO)
        tree.tag_configure("neutro", foreground=COR_NEUTRO)
        tree.tag_configure("pai", foreground="#87CEEB", font=("Segoe UI", 10, "bold"))

        return tree

    def _ordenar_coluna(self, tree, coluna, reverso):
        """Ordena Treeview por coluna clicada."""
        items = [(tree.set(k, coluna), k) for k in tree.get_children("")]

        def chave_ordenacao(item):
            val = item[0]
            limpo = val.replace("R$", "").replace(".", "").replace(",", ".").replace("%", "").replace("+", "").replace("►", "").replace("—", "").replace("N/D", "0").strip()
            if limpo.startswith("-"):
                try:
                    return float(limpo)
                except ValueError:
                    return val.lower()
            try:
                return float(limpo)
            except ValueError:
                return val.lower()

        items.sort(key=chave_ordenacao, reverse=reverso)

        for i, (_, k) in enumerate(items):
            tree.move(k, "", i)

        tree.heading(coluna, command=lambda: self._ordenar_coluna(tree, coluna, not reverso))

    # ════════════════════════════════════════════════════════════
    #  Exportação
    # ════════════════════════════════════════════════════════════

    def _exportar_csv(self):
        if not self.reporter:
            return
        caminho = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile="analise_patrimonial",
            title="Exportar CSV",
        )
        if caminho:
            try:
                self.reporter.exportar_csv(caminho)
                self._status(f"CSV exportado: {os.path.basename(caminho)}")
                messagebox.showinfo("Exportação", f"CSVs exportados com sucesso!\n\nLocal: {os.path.dirname(caminho)}")
            except Exception as e:
                messagebox.showerror("Erro", f"Erro ao exportar CSV: {e}")

    def _exportar_json(self):
        if not self.reporter:
            return
        caminho = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile="analise_patrimonial.json",
            title="Exportar JSON",
        )
        if caminho:
            try:
                self.reporter.exportar_json(caminho)
                self._status(f"JSON exportado: {os.path.basename(caminho)}")
                messagebox.showinfo("Exportação", f"JSON exportado com sucesso!\n\nLocal: {caminho}")
            except Exception as e:
                messagebox.showerror("Erro", f"Erro ao exportar JSON: {e}")

    # ════════════════════════════════════════════════════════════
    #  Status e erros
    # ════════════════════════════════════════════════════════════

    def _status(self, texto: str):
        self.lbl_status.configure(text=texto)

    def _status_seguro(self, texto: str):
        """Atualiza status de forma thread-safe."""
        self.after(0, self._status, texto)

    def _erro(self, mensagem: str):
        self._finalizar_processamento()
        messagebox.showerror("Erro", mensagem)
        self._status("Erro na análise")


def main():
    customtkinter.set_appearance_mode("dark")
    customtkinter.set_default_color_theme("blue")
    app = AnalisadorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
