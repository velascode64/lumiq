
1) Estructura del proyecto

lumina_cli/
├─ app.py
├─ lumina/
│  ├─ __init__.py
│  ├─ views.py          # (opcional) si luego quieres separar, por ahora no es necesario
│  └─ styles.tcss
└─ requirements.txt

requirements.txt

textual>=0.58


⸻

2) Código completo (sin gráficos)

app.py

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import (
    Header, Footer, Tabs, Tab, TabPane, Static,
    DataTable, Select, Button, Input
)
from textual.reactive import reactive


class LuminaApp(App):
    """Lumina Trader Platform (CLI UI) — sin gráficos, con Dashboard y Backtesting."""
    CSS_PATH = "lumina/styles.tcss"
    BINDINGS = [
        Binding("f5", "start", "Start"),
        Binding("space", "pause", "Pause"),
        Binding("s", "stop", "Stop"),
        Binding("b", "focus_backtest", "Backtest"),
        Binding("q", "quit", "Salir"),
    ]

    # Estados básicos
    session_state = reactive("IDLE")     # IDLE | RUNNING | PAUSED
    mode = reactive("Live")              # Live | Backtest

    def compose(self) -> ComposeResult:
        """Arma el layout principal."""
        yield Header(show_clock=True)
        yield Static(
            "Mensaje: Bienvenido a Lumina Trader — conecta tu broker o ejecuta un backtest.",
            id="msg",
        )

        # Tabs principales
        yield Tabs(
            Tab("Dashboard", id="tab-dashboard"),
            Tab("Backtesting", id="tab-backtest"),
            Tab("Órdenes", id="tab-orders"),
            Tab("Logs", id="tab-logs"),
            Tab("Config", id="tab-config"),
        )

        # Pestaña: Dashboard  (sin gráfico)
        with TabPane("Dashboard", id="pane-dashboard"):
            # Panel superior de controles
            top = Static(id="top")
            yield top

            # Tabla de trades
            trades = DataTable(id="trades_table")
            yield trades

            # Resumen P&L
            yield Static(self._pnl_text(), id="pnl_summary")

        # Pestaña: Backtesting
        with TabPane("Backtesting", id="pane-backtest"):
            yield Static(self._backtest_controls_text(), id="bt_controls")
            yield Static(self._bt_metrics_text(), id="bt_metrics")

        # Resto de pestañas vacías por ahora (solo placeholders)
        yield TabPane("Órdenes", id="pane-orders")
        yield TabPane("Logs", id="pane-logs")
        yield TabPane("Config", id="pane-config")

        yield Footer()

    # -----------------------------
    # Ciclo de vida
    # -----------------------------
    def on_mount(self) -> None:
        """Inicializa controles y tabla."""
        # Construir los controles del panel superior (widgets reales)
        self._build_top_controls()

        # Tabla de trades
        dt = self.query_one("#trades_table", DataTable)
        dt.add_columns("#", "Hora", "Símb", "Lado", "Cant", "Precio", "P&L($)", "P&L(%)", "Estado", "TxID")
        dt.add_rows([
            (1, "10:05:13", "QQQ",  "Buy",  10, "503.12", "+12.3", "+0.54", "Filled", "8f3a…"),
            (2, "10:07:42", "NVDA", "Sell",  2, "118.20", "-3.10", "-0.26", "Filled", "b17c…"),
            (3, "10:10:00", "TSLA", "Buy",   1, "235.90", "+0.00", "+0.00", "Open",   "93d4…"),
        ])

        # Estado inicial
        self._set_status_line('Listo para iniciar…')

    # -----------------------------
    # Construcción UI dinámica
    # -----------------------------
    def _build_top_controls(self) -> None:
        """Inserta widgets dentro del contenedor #top."""
        top = self.query_one("#top", Static)

        # Selects
        sel_strategy = Select(
            options=[("MeanReversion", "mean_rev"), ("Breakout", "breakout"), ("PairsTrading", "pairs")],
            value="mean_rev",
            id="sel_strategy",
        )
        sel_timeframe = Select(
            options=[("1m", "1m"), ("5m", "5m"), ("30m", "30m"), ("1h", "1h")],
            value="5m",
            id="sel_timeframe",
        )

        # Monto (Input)
        inp_amount = Input(value="1000", placeholder="Monto $", id="inp_amount")

        # Botones
        btn_start = Button("START ⏵", id="btn_start")
        btn_pause = Button("PAUSE ⏸", id="btn_pause")
        btn_stop  = Button("STOP ⏹",  id="btn_stop")

        # Slippage y TP/SL (texto plano por ahora)
        info_line = Static("Slippage: 0.02%   TP/SL: 1.0% / 0.5%", id="risk_info")

        # Línea de estado
        status_line = Static("", id="status_line")

        # Ensamble: usamos markup simple en top (Static) con .update
        top.update("")
        top.mount(
            Static("Estrategia:", classes="lbl"),
            sel_strategy,
            Static("Timeframe:", classes="lbl"),
            sel_timeframe,
            Static("Monto $:", classes="lbl"),
            inp_amount,
            btn_start, btn_pause, btn_stop,
            info_line,
            status_line,
        )

    # -----------------------------
    # Helpers UI
    # -----------------------------
    def _pnl_text(self) -> str:
        return (
            "P&L Realizado: +$342.50\n"
            "P&L No realizado: +$120.10\n"
            "Comisiones: -$18.40\n"
            "Máx. Drawdown: -$95.00\n"
            "Operaciones: 10 (7W / 3L)\n"
            "Métricas rápidas: Win rate 70%  •  R/M(avg) 1.45  •  Sesión 00:45:12"
        )

    def _backtest_controls_text(self) -> str:
        return (
            "Dataset: [ QQQ 2023-01-01 → 2024-12-31 ]   "
            "Intervalo: [ 30m ]   Capital inicial: $100,000   "
            "Comisiones: 0.005 $/acción   Slippage: 0.02%   Semilla: 42   "
            "[ RUN BACKTEST ]   [ Export CSV ]"
        )

    def _bt_metrics_text(self) -> str:
        return "Resultados: CAGR 11.2% | Sharpe 1.45 | Win rate 62% | Máx DD -9.8% | Operaciones 284"

    def _set_status_line(self, text: str, color: str = "green") -> None:
        status = self.query_one("#status_line", Static)
        status.update(text)
        status.styles.color = color

    # -----------------------------
    # Eventos
    # -----------------------------
    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn_start":
            self.session_state = "RUNNING"
            self._set_status_line("Estrategia INICIADA.", "green")
        elif bid == "btn_pause":
            self.session_state = "PAUSED"
            self._set_status_line("Estrategia PAUSADA.", "yellow")
        elif bid == "btn_stop":
            self.session_state = "IDLE"
            self._set_status_line("Estrategia DETENIDA.", "red")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "sel_strategy":
            self._set_status_line(f"Estrategia seleccionada: {event.value}", "cyan")
        elif event.select.id == "sel_timeframe":
            self._set_status_line(f"Timeframe seleccionado: {event.value}", "cyan")

    # -----------------------------
    # Acciones (key bindings)
    # -----------------------------
    def action_start(self) -> None:
        self.session_state = "RUNNING"
        self._set_status_line("Estrategia INICIADA (F5).", "green")

    def action_pause(self) -> None:
        self.session_state = "PAUSED"
        self._set_status_line("Estrategia PAUSADA (Space).", "yellow")

    def action_stop(self) -> None:
        self.session_state = "IDLE"
        self._set_status_line("Estrategia DETENIDA (S).", "red")

    def action_focus_backtest(self) -> None:
        self.query_one("#pane-backtest", TabPane).focus()


if __name__ == "__main__":
    app = LuminaApp()
    app.run()

lumina/styles.tcss

/* Layout vertical general */
Screen {
  layout: vertical;
}

/* Mensaje principal */
#msg {
  height: 3;
  padding: 1 2;
}

/* Altura de pestañas */
Tabs {
  height: 3;
}

/* Cada TabPane en columna */
TabPane {
  layout: vertical;
}

/* Panel superior (controles) */
#top {
  height: 7;
  padding: 1 2;
  border: solid gray;
  layout: horizontal;
  content-align: left middle;
  column-gap: 1;
}

/* Etiquetas pequeñas */
.lbl {
  color: gray;
  padding: 0 1;
}

/* Info de riesgo (texto) */
#risk_info {
  padding: 0 1;
  color: lightsteelblue;
}

/* Línea de estado */
#status_line {
  height: 1;
  width: 100%;
  padding: 0 1;
}

/* Tabla de trades */
#trades_table {
  height: 12;
  margin: 1 0;
  border: solid gray;
}

/* Resumen P&L */
#pnl_summary {
  height: 7;
  padding: 1 2;
  border: solid gray;
}

/* Backtesting */
#bt_controls {
  height: 4;
  padding: 1 2;
  border: solid gray;
}
#bt_metrics {
  height: 3;
  padding: 0 2;
  color: cyan;
}

lumina/init.py

__all__ = []


⸻

3) Cómo ejecutar

cd lumina_cli
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py


⸻

4) IDs y widgets que Claude debe respetar
	•	IDs obligatorios:
msg, top, status_line, trades_table, pnl_summary,
bt_controls, bt_metrics,
sel_strategy, sel_timeframe, inp_amount,
btn_start, btn_pause, btn_stop.
	•	Widgets permitidos: Header, Footer, Tabs, Tab, TabPane, Static, DataTable, Select, Button, Input.
	•	Nada de gráficos por ahora.

⸻

5) Mockup ASCII (versión de referencia)

┌────────────────────────────────────────── Lumina Trader Platform ──────────────────────────────────────────┐
│ Mensaje: Bienvenido a Lumina Trader — conecta tu broker o ejecuta un backtest.                            │
├───────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [Estado: ● IDLE]  Modo: [ Live ▾ | Backtest ]   Cuenta: PAPER-12345   Reloj: 10:21:04 PST                 │
├───────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Tabs: [ Dashboard ] [ Backtesting ] [ Órdenes ] [ Logs ] [ Config ]                                       │
├───────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────── Panel superior ────────────────────────────────────────┐ │
│  │ Estrategia: [ MeanReversion ▾ ]  Timeframe: [ 5m ▾ ]  Monto: [$][1,000]                              │ │
│  │ [ START ⏵ ]  [ PAUSE ⏸ ]  [ STOP ⏹ ]   Slippage: [0.02%]  TP/SL: [1.0% / 0.5%]                       │ │
│  │ Último: “Listo para iniciar…”                                                                         │ │
│  └──────────────────────────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                                           │
│  ┌──────────────────────────── Ventana inferior — Tabla de trades / fills ──────────────────────────────┐ │
│  │ #  Hora        Símb  Lado  Cant  Precio      P&L($)  P&L(%)  Estado   TxID                          │ │
│  │ 1  10:05:13    QQQ   Buy   10    503.12      +12.3   +0.54   Filled   8f3a…                         │ │
│  │ 2  10:07:42    NVDA  Sell  2     118.20      -3.10   -0.26   Filled   b17c…                         │ │
│  │ 3  10:10:00    TSLA  Buy   1     235.90      +0.00   +0.00   Open     93d4…                         │ │
│  │ …                                                                                                    │ │
│  └──────────────────────────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                                           │
│  ┌────────────── Resumen de P&L (Sesión) ───────────────┐                                                 │
│  │ P&L Realizado:        +$  342.50                     │   Métricas rápidas                              │
│  │ P&L No realizado:     +$  120.10                     │   • Win rate:        70%                        │
│  │ Comisiones:           -$   18.40                     │   • R/M (avg):       1.45                       │
│  │ Máx. Drawdown:        -$   95.00                     │   • Sesión:          00:45:12                   │
│  │ Operaciones:          10 (7W / 3L)                   │                                                   │
│  └──────────────────────────────────────────────────────┘                                                 │
├───────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ BACKTESTING                                                                                               │
│  Dataset: [ QQQ 2023-01-01 → 2024-12-31 ▾ ]  Intervalo: [ 30m ▾ ]  Capital inicial: [$][100,000]        │
│  Comisiones: [0.005 $/acción]   Slippage: [0.02%]   Semilla: [ 42 ]   [ RUN BACKTEST ]  [ Export CSV ]   │
│  Resultados: CAGR 11.2% | Sharpe 1.45 | Win rate 62% | Máx DD -9.8% | Operaciones 284                   │
├───────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Atajos: F5 Start • Space Pause • S Stop • B Backtest • Q Salir                                            │
└───────────────────────────────────────────────────────────────────────────────────────────────────────────┘

¿Quieres que ahora agregue la persistencia de configuración (estrategia/timeframe/monto) en un JSON local y el cargado al abrir la app? Lo puedo sumar sin tocar el layout.