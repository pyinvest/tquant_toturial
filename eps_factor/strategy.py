import abc
from collections import defaultdict

import pandas as pd
from logbook import INFO, Logger, StderrHandler
from zipline.api import (attach_pipeline, cancel_order, commission,
                         get_datetime, get_open_orders, order_target,
                         order_target_percent, pipeline_output, record,
                         schedule_function, set_commission, symbol)
from zipline.utils.calendar_utils import get_calendar
from zipline.utils.events import date_rules, time_rules


class PercentageIndicatorStrategy(metaclass=abc.ABCMeta):

    def __init__(self, assets, start_dt, end_dt):
        self.log_handler = StderrHandler(
            format_string='[{record.time:%Y-%m-%d %H:%M:%S.%f}]: ' +
            '{record.level_name}: {record.func_name}: {record.message}',
            level=INFO)
        self.log_handler.push_application()
        self.log = Logger('Algorithm')
        self.commission_cost = 0.001425 + 0.003 / 2
        self.start_dt = start_dt
        self.end_dt = end_dt
        self.assets = assets
        self.calendar_name = 'TEJ'
        self.tz = 'UTC'

    def initialize(self, context):
        context.universe = self.assets
        context.tradeday = self.generate_tradedays(self.start_dt, self.end_dt)
        context.longs = []
        context.shorts = []
        context.set_benchmark(symbol('IR0001'))
        set_commission(commission.PerDollar(cost=self.commission_cost))

        schedule_function(self.rebalance,
                          date_rule=date_rules.every_day(),
                          time_rule=time_rules.market_open)
        schedule_function(self.record_vars,
                          date_rule=date_rules.every_day(),
                          time_rule=time_rules.market_close)
        pipeline = self.compute_signals()
        attach_pipeline(pipeline, 'signals')

    def generate_tradedays(self, start_dt, end_dt):
        _tradeday = [
            pd.Timestamp(year=i, month=m, day=15, tz=self.tz)
            for i in range(int(start_dt.strftime('%Y')),
                           int(end_dt.strftime('%Y')) + 1)
            for m in range(1, 13)
            if pd.Timestamp(year=i, month=m, day=15, tz=self.tz) <= end_dt
        ]
        tradeday = [
            get_calendar(self.calendar_name).next_open(
                pd.Timestamp(i)).strftime('%Y-%m-%d')
            if not get_calendar(self.calendar_name).is_session(i) else
            i.strftime('%Y-%m-%d') for i in _tradeday
        ]
        return tradeday

    @abc.abstractmethod
    def compute_signals(self):
        return NotImplemented

    def rebalance(self, context, data):
        trades = defaultdict(list)
        if get_datetime().strftime('%Y-%m-%d') in context.tradeday:
            open_orders = get_open_orders()
            for asset in open_orders:
                for order in open_orders[asset]:
                    cancel_order(order)
                    self.log.info(
                        'Cancel_order: created: {}, asset: {}, amount: {}, filled: {}'  # noqa
                        .format(order.created.strftime('%Y-%m-%d'), order.sid,
                                order.amount, order.filled))
            for stock, trade in context.trades.items():
                if not trade:
                    order_target(stock, 0)
                else:
                    trades[trade].append(stock)
            context.longs = len(trades[1])
            for stock in trades[1]:
                order_target_percent(stock, 1 / context.longs * 0.8)

    def record_vars(self, context, data):
        record(leverage=context.account.leverage,
               close=data.current(context.universe, 'close'),
               longs=context.longs)

    def before_trading_start(self, context, data):
        context.output = pipeline_output('signals')
        context.trades = (context.output['longs'].astype(
            int).reset_index().drop_duplicates().set_index('index').squeeze())

        # context.market_caps = context.output['market_cap']

        # context.total_market_cap = context.market_caps.sum()
