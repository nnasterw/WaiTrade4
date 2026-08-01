#ifndef __WAITRADE_TRADE_OPS_MQH__
#define __WAITRADE_TRADE_OPS_MQH__

#include "Config.mqh"

double CalcLotSize(string symbol, double risk_pct, double risk_price)
{
   if(risk_price <= 0) return SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);

   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   double lot_step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   double min_lot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double max_lot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);

   if(tick_value <= 0 || point <= 0) return min_lot;

   // 月度lot基准重置：每月月初记录余额，超过InpFixedLotSizingBalance后锁定
   // 效果：每月从月初余额(最高=设定值)开始计算lot，实现exit-restart
   double eff_balance = balance;
   if(InpFixedLotSizingBalance > 0)
   {
      static int    s_lot_month_key = -1;
      static double s_lot_month_balance = 0.0;
      // 计算当前月份key
      MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
      int cur_key = dt.year * 12 + dt.mon;
      if(cur_key != s_lot_month_key)
      {
         s_lot_month_key = cur_key;
         s_lot_month_balance = balance;  // 记录本月月初实际余额
      }
      // 使用月初余额，但不超过上限
      eff_balance = MathMin(s_lot_month_balance, InpFixedLotSizingBalance);
      if(eff_balance <= 0) eff_balance = balance;
   }
   double risk_money = eff_balance * risk_pct / 100.0;
   double risk_points = risk_price / point;
   double lot = risk_money / (risk_points * tick_value);

   lot = MathFloor(lot / lot_step) * lot_step;
   if(lot < min_lot) lot = min_lot;
   if(lot > max_lot) lot = max_lot;
   return NormalizeDouble(lot, 2);
}

double GetSpread(string symbol)
{
   return (double)SymbolInfoInteger(symbol, SYMBOL_SPREAD) * SymbolInfoDouble(symbol, SYMBOL_POINT);
}

double BrokerStopFromVirtualSL(double virtual_sl, double entry_price, double risk_price, int direction)
{
   if(!UseVirtualSLMode())
      return virtual_sl;
   double buffer_r = CfgVirtualSLHardBufferR();
   if(buffer_r <= 0 || risk_price <= 0)
      return virtual_sl;
   double buffer = risk_price * buffer_r;
   double broker_sl = (direction > 0) ? virtual_sl - buffer : virtual_sl + buffer;
   return NormalizeDouble(broker_sl, (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS));
}

bool ModifySL(ulong ticket, double new_sl, int max_retries=2)
{
   if(!PositionSelectByTicket(ticket)) return false;

   double current_sl = PositionGetDouble(POSITION_SL);
   string symbol = PositionGetString(POSITION_SYMBOL);
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   new_sl = NormalizeDouble(new_sl, digits);

   // 跳过无效修改: 新SL与当前SL差距小于3个point（减少MT5日志量）
   if(MathAbs(new_sl - current_sl) < SymbolInfoDouble(symbol, SYMBOL_POINT) * 3)
      return true;

   for(int attempt = 0; attempt <= max_retries; attempt++)
   {
      if(!PositionSelectByTicket(ticket)) return false;

      double tp = PositionGetDouble(POSITION_TP);

      MqlTradeRequest request = {};
      MqlTradeResult result = {};
      request.action = TRADE_ACTION_SLTP;
      request.position = ticket;
      request.symbol = symbol;
      request.sl = new_sl;
      request.tp = tp;

      if(OrderSend(request, result))
      {
         if(result.retcode == TRADE_RETCODE_DONE || result.retcode == TRADE_RETCODE_PLACED)
            return true;
      }

      if(attempt < max_retries)
         Sleep(100);
   }
   return false;
}

bool PartialClose(ulong ticket, int close_pct)
{
   if(!PositionSelectByTicket(ticket)) return false;

   string symbol = PositionGetString(POSITION_SYMBOL);
   double volume = PositionGetDouble(POSITION_VOLUME);
   ENUM_POSITION_TYPE pos_type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);

   double lot_step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   double min_lot  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double close_vol = MathFloor(volume * close_pct / 100.0 / lot_step) * lot_step;
   if(close_vol < min_lot) close_vol = min_lot;
   if(close_vol >= volume) return false;  // 不全平，用 ClosePosition

   MqlTradeRequest request = {};
   MqlTradeResult result = {};
   request.action = TRADE_ACTION_DEAL;
   request.position = ticket;
   request.symbol = symbol;
   request.volume = close_vol;
   request.type = (pos_type == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   request.price = (pos_type == POSITION_TYPE_BUY) ?
                   SymbolInfoDouble(symbol, SYMBOL_BID) :
                   SymbolInfoDouble(symbol, SYMBOL_ASK);
   request.deviation = 20;

   if(!OrderSend(request, result))
      return false;
   return (result.retcode == TRADE_RETCODE_DONE);
}

bool ClosePosition(ulong ticket, string comment="")
{
   if(!PositionSelectByTicket(ticket)) return false;

   string symbol = PositionGetString(POSITION_SYMBOL);
   double volume = PositionGetDouble(POSITION_VOLUME);
   ENUM_POSITION_TYPE pos_type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);

   MqlTradeRequest request = {};
   MqlTradeResult result = {};
   request.action = TRADE_ACTION_DEAL;
   request.position = ticket;
   request.symbol = symbol;
   request.volume = volume;
   request.type = (pos_type == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   request.price = (pos_type == POSITION_TYPE_BUY) ?
                   SymbolInfoDouble(symbol, SYMBOL_BID) :
                   SymbolInfoDouble(symbol, SYMBOL_ASK);
   request.deviation = 20;
   request.comment = comment;

   if(!OrderSend(request, result))
      return false;
   return (result.retcode == TRADE_RETCODE_DONE);
}

int CountPositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) == InpMagicNumber)
         count++;
   }
   return count;
}

#endif
