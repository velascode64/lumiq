import backtrader as bt
import backtrader.indicators as btind


class VelezMomentumStrategy(bt.Strategy):
    params = (
        ('ema_period', 20),  # 20-period EMA como en enseñanzas de Velez
        ('volume_multiplier', 1.5),  # Volumen > 1.5x avg para confirmación
        ('trailing_stop_perc', 0.02),  # Trailing stop al 2%
        ('risk_per_trade', 0.01),  # Riesgo max 1% por trade
    )

    def __init__(self):
        self.ema = btind.EMA(period=self.p.ema_period)
        self.avg_volume = btind.SimpleMovingAverage(
            self.data.volume, period=20)  # Avg vol over 20 periods
        self.order = None
        self.trailing_stop = None

    def next(self):
        if self.order:  # Orden pendiente, no hacer nada
            return

        position_size = self.broker.getvalue() * self.p.risk_per_trade / \
            (self.data.close[0] * self.p.trailing_stop_perc)

        # Entrada larga: Precio > EMA y volumen > avg * multiplier (momentum alcista)
        if self.data.close[0] > self.ema[0] and self.data.volume[0] > self.avg_volume[0] * self.p.volume_multiplier:
            self.order = self.buy(size=position_size)
            self.trailing_stop = self.data.close[0] * \
                (1 - self.p.trailing_stop_perc)
            self.log(
                f'Compra: Precio={self.data.close[0]:.2f}, EMA={self.ema[0]:.2f}, Vol={self.data.volume[0]}')

        # Trailing stop: Actualizar si precio sube, vender si breach
        elif self.position:
            self.trailing_stop = max(
                self.trailing_stop, self.data.close[0] * (1 - self.p.trailing_stop_perc))
            if self.data.close[0] < self.trailing_stop:
                self.sell()
                self.log(
                    f'Venta (Trailing Stop): Precio={self.data.close[0]:.2f}, Stop={self.trailing_stop:.2f}')

    def log(self, txt):
        dt = self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()} - {txt}')


# Ejemplo de ejecución (agrega datos y corre en tu bot)
if __name__ == '__main__':
    cerebro = bt.Cerebro()
    cerebro.addstrategy(VelezMomentumStrategy)
    # Agrega data feed, e.g., from Yahoo: data = bt.feeds.YahooFinanceData(dataname='AAPL', fromdate=..., todate=...)
    # cerebro.adddata(data)
    cerebro.broker.setcash(100000.0)  # Capital inicial
    cerebro.run()
    cerebro.plot()  # Para visualización
