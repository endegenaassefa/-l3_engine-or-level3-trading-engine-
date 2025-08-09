# l3_engine/analysis/performance.py
import logging
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from ..core.portfolio import Portfolio

logger = logging.getLogger(__name__)

class PerformanceAnalyzer:
    """Generates reports and plots from a completed backtest portfolio."""
    def __init__(self, portfolio: Portfolio):
        self.portfolio = portfolio

    def generate_report(self):
        """Generates and prints the final performance report."""
        logger.info("Generating Performance Report...")
        equity_curve = pd.DataFrame(self.portfolio.equity_curve, columns=['Timestamp', 'Equity'])
        if len(equity_curve) < 2:
            logger.error("Equity curve has insufficient data for full report.")
            return

        equity_curve['Timestamp'] = pd.to_datetime(equity_curve['Timestamp'], unit='ns')
        equity_curve = equity_curve.set_index('Timestamp').resample('1D').last().dropna()

        if not self.portfolio.trade_log:
            logger.warning("No closed trades to analyze.")
            print("\n--- Backtest Results ---")
            print("No closed trades executed.")
            return

        trades_df = pd.DataFrame(self.portfolio.trade_log)
        trades_df['pnl_net'] = trades_df['pnl'] - trades_df['commission']

        total_trades = len(trades_df)
        win_rate = (trades_df['pnl_net'] > 0).sum() / total_trades if total_trades > 0 else 0
        total_net_pnl = trades_df['pnl_net'].sum()
        gross_profit = trades_df[trades_df['pnl_net'] > 0]['pnl_net'].sum()
        gross_loss = abs(trades_df[trades_df['pnl_net'] < 0]['pnl_net'].sum())
        profit_factor = gross_profit / gross_loss if gross_loss != 0 else float('inf')

        max_drawdown, sharpe_ratio = 0.0, float('nan')
        if not equity_curve.empty:
            equity_curve['Highwatermark'] = equity_curve['Equity'].cummax()
            equity_curve['Drawdown'] = equity_curve['Equity'] - equity_curve['Highwatermark']
            max_drawdown = abs(equity_curve['Drawdown'].min())
            daily_returns = equity_curve['Equity'].pct_change().dropna()
            if not daily_returns.empty and daily_returns.std() != 0:
                sharpe_ratio = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)

        print("\n--- Backtest Results ---")
        print(f"Initial Capital: {self.portfolio.initial_capital:.2f}")
        print(f"Final Equity:    {equity_curve['Equity'].iloc[-1]:.2f}")
        print(f"Total Net P&L:   {total_net_pnl:.2f}")
        print("-" * 30)
        print(f"Total Closed Trades: {total_trades}")
        print(f"Win Rate:            {win_rate:.2%}")
        print(f"Profit Factor:       {profit_factor:.2f}")
        print(f"Max Drawdown:        {max_drawdown:.2f}")
        print(f"Sharpe Ratio (Ann.): {sharpe_ratio:.2f if not np.isnan(sharpe_ratio) else 'N/A'}")
        print("-" * 30)

        trades_df.to_csv("detailed_trade_log.csv", index=False, float_format='%.4f')
        logger.info("Detailed trade log saved to detailed_trade_log.csv")

        try:
            plt.style.use('seaborn-v0_8-darkgrid')
            if not equity_curve.empty:
                fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), sharex=True, gridspec_kw={'height_ratios': [3, 1]})
                ax1.plot(equity_curve.index, equity_curve['Equity'], label='Equity')
                ax1.set_title('Equity Curve')
                ax1.set_ylabel('Equity ($)')
                ax1.grid(True)
                
                ax2.fill_between(equity_curve.index, equity_curve['Drawdown'], 0, color='red', alpha=0.3, label='Drawdown')
                ax2.set_title('Drawdown')
                ax2.set_ylabel('Drawdown ($)')
                ax2.set_xlabel('Date')
                ax2.grid(True)
                
                plt.tight_layout()
                plt.show()
        except Exception as e:
            logger.error(f"Error generating plots: {e}")