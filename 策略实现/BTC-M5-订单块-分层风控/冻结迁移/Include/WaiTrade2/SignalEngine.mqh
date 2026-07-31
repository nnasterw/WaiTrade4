#ifndef __WAITRADE_SIGNAL_ENGINE_MQH__
#define __WAITRADE_SIGNAL_ENGINE_MQH__

#include "Types.mqh"
#include "Config.mqh"
#include "Utils.mqh"
#include "MarketState.mqh"
#include "ScoreEngine.mqh"
#include "DecayDetector.mqh"

double CalcOBHeightTP(const OBZone &zone, double entry)
{
   if(CfgOBHeightTPMult() <= 0 || zone.is_range_breakout || zone.is_htf_pullback) return 0.0;
   double ob_h = zone.high - zone.low;
   if(ob_h <= 0) return 0.0;
   return entry + zone.direction * ob_h * CfgOBHeightTPMult();
}

double CalcHTFPullbackTP(const OBZone &zone, double entry)
{
   if(!zone.is_htf_pullback || InpHTFPullbackTPMult <= 0 || zone.range_height <= 0)
      return 0.0;
   return entry + zone.direction * zone.range_height * InpHTFPullbackTPMult;
}

double CalcLiquiditySweepTP(const OBZone &zone, double entry)
{
   if(!zone.is_liquidity_sweep || CfgSweepTPMult() <= 0 || zone.range_height <= 0)
      return 0.0;
   if(zone.direction == OB_BUY)
      return zone.high + zone.range_height * CfgSweepTPMult();
   return zone.low - zone.range_height * CfgSweepTPMult();
}

bool IsZoneTouched(const OBZone &zone, double bid, double ask)
{
   if(zone.is_range_breakout)
   {
      if(zone.direction == OB_BUY)
         return (bid >= zone.high);
      return (ask <= zone.low);
   }

   if(zone.is_htf_pullback)
   {
      if(zone.direction == OB_BUY)
         return (bid <= zone.high);
      return (ask >= zone.low);
   }

   if(zone.direction == OB_BUY)
      return (bid <= zone.high);
   else
      return (ask >= zone.low);
}

bool PassDoubleTouchFilter(const OBZone &zone)
{
   if(CfgRequireDoubleTch())
   {
      if(zone.touch_count < 2)
         return false;
      if(zone.last_touch - zone.first_touch > InpDoubleTchWindowMin * 60)
         return false;
   }
   else
   {
      if(zone.touch_count < 1)
         return false;
   }
   return true;
}

bool PassOffsetGuard(double entry_price, double risk_price, int direction, double zone_mid, double max_offset_r)
{
   double offset = MathAbs(entry_price - zone_mid) / risk_price;
   return (offset <= max_offset_r);
}

bool PassSpreadRatio(double risk_distance, double spread)
{
   if(spread > 0 && risk_distance / spread < CfgMinRiskSpreadRatio())
      return false;
   return true;
}

bool PassMinRisk(double final_lot, double risk_price, string symbol)
{
   if(InpMinAbsRiskUSD <= 0)
      return true;

   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   double tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);

   if(point <= 0 || tick_value <= 0)
      return true;

   double risk_usd = final_lot * (risk_price / point) * tick_value;
   return (risk_usd >= InpMinAbsRiskUSD);
}

bool IsCsvIntListed(string csv, int value)
{
   if(StringLen(csv) == 0)
      return false;

   string parts[];
   ushort sep = StringGetCharacter(",", 0);
   int count = StringSplit(csv, sep, parts);
   for(int i = 0; i < count; i++)
   {
      string token = parts[i];
      StringTrimLeft(token);
      StringTrimRight(token);
      if(StringLen(token) == 0)
         continue;
      int listed = (int)StringToInteger(token);
      if(listed == value)
         return true;
   }

   return false;
}

bool IsHourBlocked(string csv, int hour)
{
   return IsCsvIntListed(csv, hour);
}

bool IsMonthAllowed(string csv, int month)
{
   return (StringLen(csv) == 0 || IsCsvIntListed(csv, month));
}

bool PassNoEntryHours(datetime now)
{
   MqlDateTime dt;
   TimeToStruct(now, dt);

   if(!IsMonthAllowed(InpEntryMonths, dt.mon))
      return false;
   return !IsHourBlocked(CfgNoEntryHours(), dt.hour);
}

bool PassDirectionEntryHours(int direction, datetime now)
{
   MqlDateTime dt;
   TimeToStruct(now, dt);

   if(!IsMonthAllowed(InpEntryMonths, dt.mon))
      return false;
   if(IsHourBlocked(CfgNoEntryHours(), dt.hour))
      return false;
   if(direction == OB_BUY && IsHourBlocked(CfgNoBuyHours(), dt.hour))
      return false;
   if(direction == OB_SELL && IsHourBlocked(CfgNoSellHours(), dt.hour))
      return false;

   return true;
}

bool PassEntryMomentumFilter(int direction)
{
   if(!InpEnableEntryMomentumFilter)
      return true;

   int tf_min = (InpEntryMomentumTF > 0) ? InpEntryMomentumTF : CfgBarTF();
   ENUM_TIMEFRAMES tf = MinutesToTF(tf_min);
   int need = MathMax(MathMax(InpStrongMomentumBars, CfgDecayBars()) + 5, 8);

   MqlRates rates[];
   int count = CopyRates(_Symbol, tf, 0, need, rates);
   if(count < need)
      return true;

   bool counter_strong = CheckStrongMomentum(_Symbol, -direction, rates, count);
   bool counter_weak = CheckMomentumWeakness(_Symbol, -direction, rates, count);

   if(InpEntryBlockCounterStrong && counter_strong && !counter_weak)
      return false;
   if(InpEntryRequireCounterWeak && !counter_weak)
      return false;

   return true;
}

void ApplyHTFTarget(string symbol, double entry, double risk_price, TradeSignal &signal)
{
   if(!InpEnableHTFTarget)
      return;

   double htf_tp = 0;
   if(!CalcHTFTargetPrice(symbol, signal.direction, entry, risk_price, htf_tp))
      return;

   signal.tp = htf_tp;
   signal.htf_target = true;
   signal.htf_partial_r = InpHTFPartialR;
   signal.htf_partial_pct = InpHTFPartialPct;
}

void PrintEntryDebug(const string stage, const OBZone &zone, const EAState &state,
                     const TradeSignal &signal, double entry, double risk_price,
                     double spread, double pos_mult, int score)
{
   if(!InpEnableEntryDebug)
      return;

   int hour = 0;
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   hour = dt.hour;

   double risk_atr = (state.atr_value > 0) ? risk_price / state.atr_value : 0.0;
   double spread_risk = (risk_price > 0) ? spread / risk_price : 0.0;
   int age = state.bar_count - zone.created_bar;

   Print("ENTRY_DIAG stage=", stage,
         " ticket=0",
         " dir=", signal.direction,
         " hour=", hour,
         " ob_age=", age,
         " touch_count=", zone.touch_count,
         " entry_count=", zone.entry_count,
         " strength=", DoubleToString(zone.strength, 2),
         " ds=", DoubleToString(zone.ds_weight, 2),
         " fresh=", zone.is_fresh ? 1 : 0,
         " cont=", zone.is_continuation ? 1 : 0,
         " h1=", zone.is_1h_aligned ? 1 : 0,
         " deep=", signal.deep_entry ? 1 : 0,
         " htf=", signal.htf_target ? 1 : 0,
         " bounce_sec=", signal.bounce_seconds,
         " bounce_ob=", DoubleToString(signal.bounce_ob_pct, 3),
         " confirm_pos=", DoubleToString(signal.confirm_ob_pos, 3),
         " touch_price=", DoubleToString(signal.touch_price, _Digits),
         " confirm=", DoubleToString(signal.confirm_price, _Digits),
         " risk_atr=", DoubleToString(risk_atr, 2),
         " spread_risk=", DoubleToString(spread_risk, 3),
         " pos_mult=", DoubleToString(pos_mult, 2),
         " score=", score,
         " entry=", DoubleToString(entry, _Digits),
         " sl=", DoubleToString(signal.sl, _Digits));
}

double ApplyPositionMultiplierCap(double pos_mult)
{
   if(CfgMaxPosMult() > 0 && pos_mult > CfgMaxPosMult())
      return CfgMaxPosMult();
   return pos_mult;
}

double ApplyLotCap(double lot)
{
   if(CfgMaxLotSize() > 0 && lot > CfgMaxLotSize())
      return CfgMaxLotSize();
   return lot;
}

bool IsLooseSweepZone(const OBZone &zone)
{
   return zone.is_liquidity_sweep && zone.is_loose_sweep;
}

double ApplySignalTypeLotCap(const OBZone &zone, double lot)
{
   if(IsLooseSweepZone(zone))
   {
      if(InpLooseSweepMaxLotSize > 0 && lot > InpLooseSweepMaxLotSize)
         return InpLooseSweepMaxLotSize;
      return lot;
   }
   if(zone.is_htf_pullback && InpHTFPullbackMaxLotSize > 0 && lot > InpHTFPullbackMaxLotSize)
      return InpHTFPullbackMaxLotSize;
   if(zone.is_liquidity_sweep && CfgSweepMaxLotSize() > 0 && lot > CfgSweepMaxLotSize())
      return CfgSweepMaxLotSize();
   if(zone.is_range_breakout && InpRangeBreakoutMaxLotSize > 0 && lot > InpRangeBreakoutMaxLotSize)
      return InpRangeBreakoutMaxLotSize;
   return lot;
}

double ApplyBalanceLotCap(double lot)
{
   if(CfgLowBalanceThreshold() <= 0 || CfgLowBalanceMaxLotSize() <= 0)
      return lot;
   if(AccountInfoDouble(ACCOUNT_BALANCE) < CfgLowBalanceThreshold() && lot > CfgLowBalanceMaxLotSize())
      return CfgLowBalanceMaxLotSize();
   return lot;
}

double GetDirectionMinStrength(int direction)
{
   if(direction == OB_BUY && InpBuyMinStrength > 0)
      return InpBuyMinStrength;
   if(direction == OB_SELL && InpSellMinStrength > 0)
      return InpSellMinStrength;
   return InpMinOBStrength;
}

double ApplyDirectionPosMult(int direction, double pos_mult)
{
   if(direction == OB_BUY)
      return pos_mult * InpBuyPosMult;
   if(direction == OB_SELL)
      return pos_mult * InpSellPosMult;
   return pos_mult;
}

double ApplyHourPositionMultiplier(double pos_mult)
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);

   if(CfgLowRiskHourMult() != 1.0 && IsHourBlocked(CfgLowRiskHours(), dt.hour))
      pos_mult *= CfgLowRiskHourMult();
   if(CfgHighRiskHourMult() != 1.0 && IsHourBlocked(CfgHighRiskHours(), dt.hour))
      pos_mult *= CfgHighRiskHourMult();

   return pos_mult;
}

double ApplyOneContextFilterPositionMultiplier(
   string months,
   string no_hours,
   string no_buy_hours,
   string no_sell_hours,
   double min_month_start_balance,
   double max_month_start_balance,
   double min_price,
   double max_price,
   double mult,
   int direction,
   double pos_mult
)
{
   if(mult == 1.0)
      return pos_mult;
   if(no_hours == "" && no_buy_hours == "" && no_sell_hours == "")
      return pos_mult;

   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(!IsMonthAllowed(months, dt.mon))
      return pos_mult;

   if(min_month_start_balance > 0 || max_month_start_balance > 0)
   {
      SyncMonthlyRiskState();
      if(g_monthly_start_balance <= 0)
         return pos_mult;
      if(min_month_start_balance > 0 && g_monthly_start_balance < min_month_start_balance)
         return pos_mult;
      if(max_month_start_balance > 0 && g_monthly_start_balance > max_month_start_balance)
         return pos_mult;
   }

   if(min_price > 0 || max_price > 0)
   {
      double ref_price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      if(ref_price <= 0)
         ref_price = SymbolInfoDouble(_Symbol, SYMBOL_LAST);
      if(ref_price <= 0)
         return pos_mult;
      if(min_price > 0 && ref_price < min_price)
         return pos_mult;
      if(max_price > 0 && ref_price > max_price)
         return pos_mult;
   }

   bool matched = IsHourBlocked(no_hours, dt.hour);
   if(direction == OB_BUY && IsHourBlocked(no_buy_hours, dt.hour))
      matched = true;
   if(direction == OB_SELL && IsHourBlocked(no_sell_hours, dt.hour))
      matched = true;
   if(!matched)
      return pos_mult;

   if(mult <= 0)
      return -1.0;
   return pos_mult * mult;
}

double ApplyContextFilterPositionMultiplier(int direction, double pos_mult)
{
   if(UseBTCProfile())
      return pos_mult;

   pos_mult = ApplyOneContextFilterPositionMultiplier(
      CfgContextFilter1Months(), CfgContextFilter1NoHours(),
      CfgContextFilter1NoBuyHours(), CfgContextFilter1NoSellHours(),
      CfgContextFilter1MinMonthStartBalance(), CfgContextFilter1MaxMonthStartBalance(),
      CfgContextFilter1MinPrice(), CfgContextFilter1MaxPrice(),
      CfgContextFilter1Mult(), direction, pos_mult);
   if(pos_mult < 0)
      return pos_mult;

   pos_mult = ApplyOneContextFilterPositionMultiplier(
      CfgContextFilter2Months(), CfgContextFilter2NoHours(),
      CfgContextFilter2NoBuyHours(), CfgContextFilter2NoSellHours(),
      CfgContextFilter2MinMonthStartBalance(), CfgContextFilter2MaxMonthStartBalance(),
      CfgContextFilter2MinPrice(), CfgContextFilter2MaxPrice(),
      CfgContextFilter2Mult(), direction, pos_mult);
   if(pos_mult < 0)
      return pos_mult;

   pos_mult = ApplyOneContextFilterPositionMultiplier(
      CfgContextFilter3Months(), CfgContextFilter3NoHours(),
      CfgContextFilter3NoBuyHours(), CfgContextFilter3NoSellHours(),
      CfgContextFilter3MinMonthStartBalance(), CfgContextFilter3MaxMonthStartBalance(),
      CfgContextFilter3MinPrice(), CfgContextFilter3MaxPrice(),
      CfgContextFilter3Mult(), direction, pos_mult);
   if(pos_mult < 0)
      return pos_mult;

   pos_mult = ApplyOneContextFilterPositionMultiplier(
      CfgContextFilter4Months(), CfgContextFilter4NoHours(),
      CfgContextFilter4NoBuyHours(), CfgContextFilter4NoSellHours(),
      CfgContextFilter4MinMonthStartBalance(), CfgContextFilter4MaxMonthStartBalance(),
      CfgContextFilter4MinPrice(), CfgContextFilter4MaxPrice(),
      CfgContextFilter4Mult(), direction, pos_mult);
   if(pos_mult < 0)
      return pos_mult;

   return ApplyOneContextFilterPositionMultiplier(
      CfgContextFilter5Months(), CfgContextFilter5NoHours(),
      CfgContextFilter5NoBuyHours(), CfgContextFilter5NoSellHours(),
      CfgContextFilter5MinMonthStartBalance(), CfgContextFilter5MaxMonthStartBalance(),
      CfgContextFilter5MinPrice(), CfgContextFilter5MaxPrice(),
      CfgContextFilter5Mult(), direction, pos_mult);
}

bool ShouldApplyContextReverse(int direction, double ref_price, double risk_price)
{
   if(UseBTCProfile())
      return false;
   if(InpContextReverseHours == "")
      return false;
   if(InpContextReverseDirections != "")
   {
      if(direction == OB_BUY && StringFind(InpContextReverseDirections, "buy") < 0)
         return false;
      if(direction == OB_SELL && StringFind(InpContextReverseDirections, "sell") < 0)
         return false;
   }
   if(InpContextReverseMaxRisk > 0 && risk_price > InpContextReverseMaxRisk)
      return false;

   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(!IsHourBlocked(InpContextReverseHours, dt.hour))
      return false;
   if(direction == OB_SELL &&
      (InpContextReverseSellEarlyDayMax > 0 || InpContextReverseSellLateDayMin > 0))
   {
      bool in_sell_day = false;
      if(InpContextReverseSellEarlyDayMax > 0 && dt.day <= InpContextReverseSellEarlyDayMax)
         in_sell_day = true;
      if(InpContextReverseSellLateDayMin > 0 && dt.day >= InpContextReverseSellLateDayMin)
         in_sell_day = true;
      if(!in_sell_day)
         return false;
   }

   if(InpContextReverseMaxMonthStartBalance > 0)
   {
      SyncMonthlyRiskState();
      if(g_monthly_start_balance <= 0 ||
         g_monthly_start_balance > InpContextReverseMaxMonthStartBalance)
         return false;
   }

   if(ref_price <= 0)
      ref_price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(ref_price <= 0)
      ref_price = SymbolInfoDouble(_Symbol, SYMBOL_LAST);
   if(ref_price <= 0)
      return false;
   if(InpContextReverseMinPrice > 0 && ref_price < InpContextReverseMinPrice)
      return false;
   if(InpContextReverseMaxPrice > 0 && ref_price > InpContextReverseMaxPrice)
      return false;

   return true;
}

double ApplySignalTypePositionMultiplier(const OBZone &zone, double pos_mult)
{
   if(IsLooseSweepZone(zone))
      pos_mult *= InpLooseSweepPosMult;
   else if(zone.is_liquidity_sweep)
      pos_mult *= CfgSweepPosMult();
   if(zone.is_range_breakout)
      pos_mult *= InpRangeBreakoutPosMult;
   if(zone.is_htf_pullback)
      pos_mult *= InpHTFPullbackPosMult;
   return pos_mult;
}

double ApplyBalancePositionMultiplier(double pos_mult)
{
   if(CfgLowBalanceThreshold() <= 0 || CfgLowBalancePosMult() == 1.0)
      return pos_mult;
   if(AccountInfoDouble(ACCOUNT_BALANCE) < CfgLowBalanceThreshold())
      pos_mult *= CfgLowBalancePosMult();
   return pos_mult;
}

int g_monthly_risk_key = 0;
double g_monthly_start_balance = 0.0;
double g_monthly_peak_balance = 0.0;
int g_monthly_entry_count = 0;
bool g_monthly_entry_stopped = false;
bool g_monthly_loss_stopped = false;
bool g_monthly_profit_locked = false;

bool UseSharedMonthlyGuard()
{
   return (InpSharedMonthlyGuard && StringLen(InpSharedMonthlyGuardKey) > 0);
}

void PrintSharedMonthlyDiag(string event_name)
{
   if(!InpSharedMonthlyGuardDebug || !UseSharedMonthlyGuard())
      return;

   Print("SHARED_GUARD event=", event_name,
         " key=", InpSharedMonthlyGuardKey,
         " version=", InpVersion,
         " symbol=", _Symbol,
         " month=", g_monthly_risk_key,
         " start=", DoubleToString(g_monthly_start_balance, 2),
         " peak=", DoubleToString(g_monthly_peak_balance, 2),
         " count=", g_monthly_entry_count,
         " entry_stopped=", g_monthly_entry_stopped ? 1 : 0,
         " loss_stopped=", g_monthly_loss_stopped ? 1 : 0,
         " profit_locked=", g_monthly_profit_locked ? 1 : 0);
}

string SharedMonthlyPrefix(int key)
{
   return "WT2_MONTH_" + InpSharedMonthlyGuardKey + "_" + IntegerToString(key);
}

void SaveSharedMonthlyState()
{
   if(!UseSharedMonthlyGuard() || g_monthly_risk_key <= 0)
      return;

   string prefix = SharedMonthlyPrefix(g_monthly_risk_key);
   GlobalVariableSet(prefix + "_start", g_monthly_start_balance);
   GlobalVariableSet(prefix + "_peak", g_monthly_peak_balance);
   GlobalVariableSet(prefix + "_count", g_monthly_entry_count);
   GlobalVariableSet(prefix + "_entry_stopped", g_monthly_entry_stopped ? 1.0 : 0.0);
   GlobalVariableSet(prefix + "_loss_stopped", g_monthly_loss_stopped ? 1.0 : 0.0);
   GlobalVariableSet(prefix + "_profit_locked", g_monthly_profit_locked ? 1.0 : 0.0);
}

void LoadSharedMonthlyState(int key)
{
   string prefix = SharedMonthlyPrefix(key);
   string start_key = prefix + "_start";

   if(!GlobalVariableCheck(start_key))
   {
      g_monthly_risk_key = key;
      g_monthly_start_balance = AccountInfoDouble(ACCOUNT_BALANCE);
      g_monthly_peak_balance = g_monthly_start_balance;
      g_monthly_entry_count = 0;
      g_monthly_entry_stopped = false;
      g_monthly_loss_stopped = false;
      g_monthly_profit_locked = false;
      SaveSharedMonthlyState();
      PrintSharedMonthlyDiag("init");
      return;
   }

   bool first_local_load = (key != g_monthly_risk_key);
   g_monthly_risk_key = key;
   g_monthly_start_balance = GlobalVariableGet(start_key);
   g_monthly_peak_balance = GlobalVariableGet(prefix + "_peak");
   g_monthly_entry_count = (int)GlobalVariableGet(prefix + "_count");
   g_monthly_entry_stopped = (GlobalVariableGet(prefix + "_entry_stopped") > 0.5);
   g_monthly_loss_stopped = (GlobalVariableGet(prefix + "_loss_stopped") > 0.5);
   g_monthly_profit_locked = (GlobalVariableGet(prefix + "_profit_locked") > 0.5);
   if(first_local_load)
      PrintSharedMonthlyDiag("load");
}

void SyncMonthlyRiskState()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   int key = dt.year * 100 + dt.mon;
   if(UseSharedMonthlyGuard())
   {
      LoadSharedMonthlyState(key);
      return;
   }
   if(key != g_monthly_risk_key)
   {
      g_monthly_risk_key = key;
      g_monthly_start_balance = AccountInfoDouble(ACCOUNT_BALANCE);
      g_monthly_peak_balance = g_monthly_start_balance;
      g_monthly_entry_count = 0;
      g_monthly_entry_stopped = false;
      g_monthly_loss_stopped = false;
      g_monthly_profit_locked = false;
   }
}

void UpdateMonthlyPeakBalance(double balance)
{
   if(balance > g_monthly_peak_balance)
   {
      g_monthly_peak_balance = balance;
      SaveSharedMonthlyState();
   }
}

void RecordMonthlyEntry()
{
   SyncMonthlyRiskState();
   g_monthly_entry_count++;
   SaveSharedMonthlyState();
   PrintSharedMonthlyDiag("entry");
}

bool CheckMonthlyLossStop(bool lock_stop)
{
   if(InpMonthlyLossStopPct <= 0)
      return false;

   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk_balance = MathMin(balance, equity);

   SyncMonthlyRiskState();
   UpdateMonthlyPeakBalance(balance);

   bool loss_guard_enabled = (InpMonthlyGuardMinBalance <= 0 ||
      g_monthly_peak_balance >= InpMonthlyGuardMinBalance);
   if(!loss_guard_enabled || g_monthly_start_balance <= 0)
      return false;

   if(g_monthly_loss_stopped)
      return true;

   bool early_stop_check = (InpMonthlyEarlyLossStopTrades > 0 &&
      (g_monthly_entry_count == InpMonthlyEarlyLossStopTrades ||
       (InpMonthlyEarlyLossStopContinuous && g_monthly_entry_count >= InpMonthlyEarlyLossStopTrades)));
   if(early_stop_check)
   {
      bool early_guard_enabled = (InpMonthlyEarlyLossStopMinBalance <= 0 ||
         g_monthly_peak_balance >= InpMonthlyEarlyLossStopMinBalance);
      if(early_guard_enabled)
      {
         double early_stop_balance = g_monthly_start_balance * (1.0 - InpMonthlyEarlyLossStopPct / 100.0);
         if(risk_balance <= early_stop_balance)
         {
            if(lock_stop)
            {
               g_monthly_loss_stopped = true;
               g_monthly_entry_stopped = true;
               SaveSharedMonthlyState();
               PrintSharedMonthlyDiag("early_loss_stop");
            }
            return true;
         }
      }
   }

   double stop_balance = g_monthly_start_balance * (1.0 - InpMonthlyLossStopPct / 100.0);
   bool enough_trades = (InpMonthlyLossStopMinTrades <= 0 ||
      g_monthly_entry_count >= InpMonthlyLossStopMinTrades);
   if(enough_trades && risk_balance <= stop_balance)
   {
      if(lock_stop)
      {
         g_monthly_loss_stopped = true;
         g_monthly_entry_stopped = true;
         SaveSharedMonthlyState();
         PrintSharedMonthlyDiag("loss_stop");
      }
      return true;
   }

   // 峰值回撤止损：从月内最高余额回撤超过阈值则停止（适用于lot5放大场景）
   if(InpMonthlyDrawdownStopPct > 0 && g_monthly_peak_balance > 0)
   {
      double dd_stop = g_monthly_peak_balance * (1.0 - InpMonthlyDrawdownStopPct / 100.0);
      if(risk_balance <= dd_stop)
      {
         if(lock_stop)
         {
            g_monthly_loss_stopped = true;
            g_monthly_entry_stopped = true;
            SaveSharedMonthlyState();
            PrintSharedMonthlyDiag("drawdown_stop");
         }
         return true;
      }
   }

   return false;
}

bool IsMonthlyProfitLockEnabled()
{
   return (InpMonthlyProfitLockStartPct > 0 &&
      InpMonthlyProfitLockKeepPct > 0 &&
      (InpMonthlyProfitLockMinBalance <= 0 ||
         g_monthly_peak_balance >= InpMonthlyProfitLockMinBalance));
}

bool IsMonthlyProfitTargetStopSlotEnabled(
   double pct,
   double min_balance,
   double max_balance,
   string months
)
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   return (pct > 0 &&
      IsMonthAllowed(months, dt.mon) &&
      (min_balance <= 0 || g_monthly_start_balance >= min_balance) &&
      (max_balance <= 0 || g_monthly_start_balance <= max_balance));
}

bool IsMonthlyProfitTargetStopEnabled()
{
   if(UseBTCProfile())
      return false;

   return (
      IsMonthlyProfitTargetStopSlotEnabled(
         InpMonthlyProfitTargetStopPct,
         InpMonthlyProfitTargetStopMinBalance,
         InpMonthlyProfitTargetStopMaxBalance,
         CfgMonthlyProfitTargetStopMonths()
      ) ||
      IsMonthlyProfitTargetStopSlotEnabled(
         InpMonthlyProfitTargetStop2Pct,
         InpMonthlyProfitTargetStop2MinBalance,
         InpMonthlyProfitTargetStop2MaxBalance,
         InpMonthlyProfitTargetStop2Months
      )
   );
}

double MonthlyProfitTargetStopPct()
{
   if(UseBTCProfile())
      return 0.0;

   if(IsMonthlyProfitTargetStopSlotEnabled(
      InpMonthlyProfitTargetStopPct,
      InpMonthlyProfitTargetStopMinBalance,
      InpMonthlyProfitTargetStopMaxBalance,
      CfgMonthlyProfitTargetStopMonths()
   ))
      return InpMonthlyProfitTargetStopPct;

   if(IsMonthlyProfitTargetStopSlotEnabled(
      InpMonthlyProfitTargetStop2Pct,
      InpMonthlyProfitTargetStop2MinBalance,
      InpMonthlyProfitTargetStop2MaxBalance,
      InpMonthlyProfitTargetStop2Months
   ))
      return InpMonthlyProfitTargetStop2Pct;

   return 0.0;
}

bool CheckMonthlyProfitTargetStop(bool lock_stop)
{
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk_balance = MathMin(balance, equity);

   SyncMonthlyRiskState();
   UpdateMonthlyPeakBalance(balance);

   double target_pct = MonthlyProfitTargetStopPct();
   if(target_pct <= 0 || g_monthly_start_balance <= 0)
      return false;

   double target_profit = g_monthly_start_balance * target_pct / 100.0;
   if(risk_balance - g_monthly_start_balance >= target_profit)
   {
      if(lock_stop)
      {
         g_monthly_profit_locked = true;
         g_monthly_entry_stopped = true;
         SaveSharedMonthlyState();
         PrintSharedMonthlyDiag("profit_target_stop");
      }
      return true;
   }

   return false;
}

bool CheckMonthlyProfitLockStop(bool lock_stop)
{
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk_balance = MathMin(balance, equity);

   SyncMonthlyRiskState();
   UpdateMonthlyPeakBalance(balance);

   if(!IsMonthlyProfitLockEnabled())
      return false;
   if(g_monthly_start_balance <= 0)
      return false;
   if(g_monthly_profit_locked)
      return true;

   double peak_profit = g_monthly_peak_balance - g_monthly_start_balance;
   double start_profit = g_monthly_start_balance * InpMonthlyProfitLockStartPct / 100.0;
   if(peak_profit < start_profit)
      return false;

   double current_profit = risk_balance - g_monthly_start_balance;
   double keep_profit = peak_profit * InpMonthlyProfitLockKeepPct / 100.0;
   if(current_profit < keep_profit)
   {
      if(lock_stop)
      {
         g_monthly_profit_locked = true;
         g_monthly_entry_stopped = true;
         SaveSharedMonthlyState();
         PrintSharedMonthlyDiag("profit_lock_stop");
      }
      return true;
   }

   return false;
}

bool PassMonthlyEntryGuard()
{
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   SyncMonthlyRiskState();
   UpdateMonthlyPeakBalance(balance);

   if(InpHighBalanceNoEntryMinMonthStartBalance > 0 &&
      g_monthly_start_balance >= InpHighBalanceNoEntryMinMonthStartBalance)
   {
      MqlDateTime dt;
      TimeToStruct(TimeCurrent(), dt);
      if(IsMonthAllowed(InpHighBalanceNoEntryMonths, dt.mon) &&
         StringLen(InpHighBalanceNoEntryMonths) > 0)
         return false;
   }

   bool profit_lock_enabled = IsMonthlyProfitLockEnabled();
   bool profit_target_enabled = IsMonthlyProfitTargetStopEnabled();

   if(InpMonthlyLossStopPct <= 0 && !profit_lock_enabled && !profit_target_enabled)
      return true;

   if(g_monthly_start_balance <= 0)
      return true;

   if(g_monthly_entry_stopped)
   {
      static datetime s_last_shared_block_diag = 0;
      if(TimeCurrent() - s_last_shared_block_diag >= 3600)
      {
         s_last_shared_block_diag = TimeCurrent();
         PrintSharedMonthlyDiag("entry_blocked");
      }
      return false;
   }

   if(CheckMonthlyLossStop(true))
      return false;

   if(CheckMonthlyProfitTargetStop(true))
      return false;

   if(CheckMonthlyProfitLockStop(true))
      return false;

   return true;
}

void LockMonthlyEntriesAfterFilteredBadCluster()
{
   if(!InpBadClusterFilteredMonthlyStop)
      return;

   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   SyncMonthlyRiskState();
   UpdateMonthlyPeakBalance(balance);

   if(InpBadClusterFilteredStopMinBalance > 0 &&
      g_monthly_peak_balance < InpBadClusterFilteredStopMinBalance)
      return;

   g_monthly_loss_stopped = true;
   g_monthly_entry_stopped = true;
   SaveSharedMonthlyState();
   PrintSharedMonthlyDiag("bad_cluster_stop");
}

double ApplyMonthlyPositionMultiplier(double pos_mult)
{
   if(InpMonthlyNegativePosMult == 1.0 &&
      (InpMonthlyWarmupProfitPct <= 0 || InpMonthlyWarmupPosMult == 1.0))
      return pos_mult;
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   SyncMonthlyRiskState();
   UpdateMonthlyPeakBalance(balance);
   if(InpMonthlyGuardMinBalance > 0 && g_monthly_peak_balance < InpMonthlyGuardMinBalance)
      return pos_mult;
   if(g_monthly_start_balance <= 0)
      return pos_mult;
   if(InpMonthlyWarmupProfitPct > 0 && InpMonthlyWarmupPosMult != 1.0)
   {
      double required_profit = g_monthly_start_balance * InpMonthlyWarmupProfitPct / 100.0;
      if(balance - g_monthly_start_balance < required_profit)
      {
         if(InpMonthlyWarmupPosMult <= 0)
            return -1.0;
         pos_mult *= InpMonthlyWarmupPosMult;
      }
   }
   if(balance < g_monthly_start_balance)
      pos_mult *= InpMonthlyNegativePosMult;
   return pos_mult;
}

double ApplyEntryQualityPositionMultiplier(const TradeSignal &signal, double risk_price, double pos_mult)
{
   if(CfgLateBounceSec() > 0 && CfgLateBounceMult() != 1.0 &&
      signal.bounce_seconds > CfgLateBounceSec())
      pos_mult *= CfgLateBounceMult();

   double bounce_sweet_min = CfgDefensiveBounceSweetMinPct();
   double bounce_sweet_max = CfgDefensiveBounceSweetMaxPct();
   double outside_bounce_sweet_mult = CfgDefensiveOutsideBounceSweetMult();
   if(bounce_sweet_min > 0 && bounce_sweet_max > bounce_sweet_min &&
      outside_bounce_sweet_mult != 1.0 && signal.bounce_ob_pct > 0)
   {
      if(signal.bounce_ob_pct < bounce_sweet_min ||
         signal.bounce_ob_pct > bounce_sweet_max)
      {
         if(outside_bounce_sweet_mult <= 0)
            return -1.0;
         pos_mult *= outside_bounce_sweet_mult;
      }
   }

   if(CfgBounceCloseWeakBodyPct() > 0 && CfgBounceCloseWeakBodyMult() != 1.0 &&
      signal.confirm_body_pct > 0 && signal.confirm_body_pct < CfgBounceCloseWeakBodyPct())
   {
      if(CfgBounceCloseWeakBodyMult() <= 0)
         return -1.0;
      pos_mult *= CfgBounceCloseWeakBodyMult();
   }

   if(CfgBadRiskMax() > CfgBadRiskMin() && CfgBadRiskMult() != 1.0 &&
      risk_price >= CfgBadRiskMin() && risk_price < CfgBadRiskMax())
      pos_mult *= CfgBadRiskMult();

   if(CfgLargeRiskMin() > 0 && CfgLargeRiskMult() != 1.0 &&
      risk_price >= CfgLargeRiskMin())
      pos_mult *= CfgLargeRiskMult();

   if(CfgShallowConfirmPosMin() > -999.0 && CfgShallowConfirmPosMult() != 1.0 &&
      signal.confirm_ob_pos > CfgShallowConfirmPosMin())
   {
      if(CfgShallowConfirmPosMult() <= 0)
         return -1.0;
      pos_mult *= CfgShallowConfirmPosMult();
   }

   return pos_mult;
}

double ApplyOneBadClusterPositionMultiplier(
   string hours,
   double risk_min,
   double risk_max,
   double confirm_min,
   double confirm_max,
   double mult,
   string signal_filter,
   const OBZone &zone,
   const TradeSignal &signal,
   double risk_price,
   double pos_mult
)
{
   if(hours == "" || mult == 1.0)
      return pos_mult;

   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(!IsHourBlocked(hours, dt.hour))
      return pos_mult;

   if(risk_max > risk_min && (risk_price < risk_min || risk_price >= risk_max))
      return pos_mult;

   if(signal.confirm_ob_pos < confirm_min || signal.confirm_ob_pos >= confirm_max)
      return pos_mult;

   string filter = signal_filter;
   StringToLower(filter);
   if(filter != "" && filter != "all")
   {
      if(filter == "sweep" && !zone.is_liquidity_sweep)
         return pos_mult;
      if(filter == "range" && !zone.is_range_breakout)
         return pos_mult;
      if(filter == "htf_pullback" && !zone.is_htf_pullback)
         return pos_mult;
      if(filter == "htfpb" && !zone.is_htf_pullback)
         return pos_mult;
      if(filter == "ob" && (zone.is_liquidity_sweep || zone.is_range_breakout || zone.is_htf_pullback))
         return pos_mult;
   }

   if(mult <= 0)
      return -1.0;
   return pos_mult * mult;
}

double ApplyBadClusterPositionMultiplier(const OBZone &zone, const TradeSignal &signal, double risk_price, double pos_mult)
{
   if(InpBadClusterMinBalance > 0 || InpBadClusterOnlyMonthlyNegative)
   {
      double balance = AccountInfoDouble(ACCOUNT_BALANCE);
      if(InpBadClusterMinBalance > 0 && balance < InpBadClusterMinBalance)
         return pos_mult;

      if(InpBadClusterOnlyMonthlyNegative)
      {
         SyncMonthlyRiskState();
         if(g_monthly_start_balance <= 0 || balance >= g_monthly_start_balance)
            return pos_mult;
      }
   }

   pos_mult = ApplyOneBadClusterPositionMultiplier(
      InpBadCluster1Hours, InpBadCluster1RiskMin, InpBadCluster1RiskMax,
      InpBadCluster1ConfirmMin, InpBadCluster1ConfirmMax, InpBadCluster1Mult,
      InpBadCluster1Signal, zone,
      signal, risk_price, pos_mult);
   if(pos_mult < 0)
   {
      LockMonthlyEntriesAfterFilteredBadCluster();
      return pos_mult;
   }

   pos_mult = ApplyOneBadClusterPositionMultiplier(
      InpBadCluster2Hours, InpBadCluster2RiskMin, InpBadCluster2RiskMax,
      InpBadCluster2ConfirmMin, InpBadCluster2ConfirmMax, InpBadCluster2Mult,
      InpBadCluster2Signal, zone,
      signal, risk_price, pos_mult);
   if(pos_mult < 0)
   {
      LockMonthlyEntriesAfterFilteredBadCluster();
      return pos_mult;
   }

   pos_mult = ApplyOneBadClusterPositionMultiplier(
      InpBadCluster3Hours, InpBadCluster3RiskMin, InpBadCluster3RiskMax,
      InpBadCluster3ConfirmMin, InpBadCluster3ConfirmMax, InpBadCluster3Mult,
      InpBadCluster3Signal, zone,
      signal, risk_price, pos_mult);
   if(pos_mult < 0)
   {
      LockMonthlyEntriesAfterFilteredBadCluster();
      return pos_mult;
   }

   pos_mult = ApplyOneBadClusterPositionMultiplier(
      InpBadCluster4Hours, InpBadCluster4RiskMin, InpBadCluster4RiskMax,
      InpBadCluster4ConfirmMin, InpBadCluster4ConfirmMax, InpBadCluster4Mult,
      InpBadCluster4Signal, zone,
      signal, risk_price, pos_mult);
   if(pos_mult < 0)
   {
      LockMonthlyEntriesAfterFilteredBadCluster();
      return pos_mult;
   }

   pos_mult = ApplyOneBadClusterPositionMultiplier(
      InpBadCluster5Hours, InpBadCluster5RiskMin, InpBadCluster5RiskMax,
      InpBadCluster5ConfirmMin, InpBadCluster5ConfirmMax, InpBadCluster5Mult,
      InpBadCluster5Signal, zone,
      signal, risk_price, pos_mult);
   if(pos_mult < 0)
   {
      LockMonthlyEntriesAfterFilteredBadCluster();
      return pos_mult;
   }

   pos_mult = ApplyOneBadClusterPositionMultiplier(
      InpBadCluster6Hours, InpBadCluster6RiskMin, InpBadCluster6RiskMax,
      InpBadCluster6ConfirmMin, InpBadCluster6ConfirmMax, InpBadCluster6Mult,
      InpBadCluster6Signal, zone,
      signal, risk_price, pos_mult);
    if(pos_mult < 0)
       LockMonthlyEntriesAfterFilteredBadCluster();
    return pos_mult;
}

double ApplyStartupBadClusterPositionMultiplier(const OBZone &zone, const TradeSignal &signal, double risk_price, double pos_mult)
{
   if(InpStartupBadClusterMaxMonthStartBalance <= 0)
      return pos_mult;

   SyncMonthlyRiskState();
   if(g_monthly_start_balance <= 0 ||
      g_monthly_start_balance > InpStartupBadClusterMaxMonthStartBalance)
      return pos_mult;

   pos_mult = ApplyOneBadClusterPositionMultiplier(
      InpStartupBadCluster1Hours, InpStartupBadCluster1RiskMin, InpStartupBadCluster1RiskMax,
      InpStartupBadCluster1ConfirmMin, InpStartupBadCluster1ConfirmMax, InpStartupBadCluster1Mult,
      InpStartupBadCluster1Signal, zone,
      signal, risk_price, pos_mult);
   if(pos_mult < 0)
      return pos_mult;

   pos_mult = ApplyOneBadClusterPositionMultiplier(
      InpStartupBadCluster2Hours, InpStartupBadCluster2RiskMin, InpStartupBadCluster2RiskMax,
      InpStartupBadCluster2ConfirmMin, InpStartupBadCluster2ConfirmMax, InpStartupBadCluster2Mult,
      InpStartupBadCluster2Signal, zone,
      signal, risk_price, pos_mult);
   if(pos_mult < 0)
      return pos_mult;

   pos_mult = ApplyOneBadClusterPositionMultiplier(
      InpStartupBadCluster3Hours, InpStartupBadCluster3RiskMin, InpStartupBadCluster3RiskMax,
      InpStartupBadCluster3ConfirmMin, InpStartupBadCluster3ConfirmMax, InpStartupBadCluster3Mult,
      InpStartupBadCluster3Signal, zone,
      signal, risk_price, pos_mult);
   if(pos_mult < 0)
      return pos_mult;

   pos_mult = ApplyOneBadClusterPositionMultiplier(
      InpStartupBadCluster4Hours, InpStartupBadCluster4RiskMin, InpStartupBadCluster4RiskMax,
      InpStartupBadCluster4ConfirmMin, InpStartupBadCluster4ConfirmMax, InpStartupBadCluster4Mult,
      InpStartupBadCluster4Signal, zone,
      signal, risk_price, pos_mult);
   return pos_mult;
}

double ApplySweepContextPositionMultiplier(const OBZone &zone, const EAState &state,
                                           const TradeSignal &signal, double risk_price, double pos_mult)
{
   if(!zone.is_liquidity_sweep)
      return pos_mult;

   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);

   if(InpSweepAllowHours != "" && !IsHourBlocked(InpSweepAllowHours, dt.hour))
      return -1.0;
   if(IsHourBlocked(InpSweepNoHours, dt.hour))
      return -1.0;

   bool sweep_context_active = IsMonthAllowed(InpSweepContextMonths, dt.mon);
   if(sweep_context_active && InpSweepContextMaxDay > 0 && dt.day > InpSweepContextMaxDay)
      sweep_context_active = false;
   if(sweep_context_active && InpSweepContextMinMonthStartBalance > 0)
   {
      SyncMonthlyRiskState();
      if(g_monthly_start_balance < InpSweepContextMinMonthStartBalance)
         sweep_context_active = false;
   }

   if(sweep_context_active && IsHourBlocked(InpSweepContextNoHours, dt.hour))
      return -1.0;

   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   if(InpSweepMinBalance > 0 && balance < InpSweepMinBalance)
      return -1.0;
   if(InpSweepLowBalanceThreshold > 0 && balance < InpSweepLowBalanceThreshold &&
      InpSweepLowBalanceMult != 1.0)
   {
      if(InpSweepLowBalanceMult <= 0)
         return -1.0;
      pos_mult *= InpSweepLowBalanceMult;
   }
   if(InpSweepMonthlyNegativeMult != 1.0)
   {
      SyncMonthlyRiskState();
      if(g_monthly_start_balance > 0 && balance < g_monthly_start_balance)
      {
         if(InpSweepMonthlyNegativeMult <= 0)
            return -1.0;
         pos_mult *= InpSweepMonthlyNegativeMult;
      }
   }
   if(InpSweepMonthlyProfitStartPct > 0)
   {
      SyncMonthlyRiskState();
      if(g_monthly_start_balance > 0)
      {
         double required_profit = g_monthly_start_balance * InpSweepMonthlyProfitStartPct / 100.0;
         if(balance - g_monthly_start_balance < required_profit)
            return -1.0;
      }
   }

   if(InpSweepEarlyBounceSecMax > InpSweepEarlyBounceSecMin &&
      InpSweepEarlyBounceMult != 1.0 &&
      signal.bounce_seconds >= InpSweepEarlyBounceSecMin &&
      signal.bounce_seconds <= InpSweepEarlyBounceSecMax)
   {
      if(InpSweepEarlyBounceHours != "" && !IsHourBlocked(InpSweepEarlyBounceHours, dt.hour))
         return pos_mult;
      if(InpSweepEarlyBounceMult <= 0)
         return -1.0;
      pos_mult *= InpSweepEarlyBounceMult;
   }

   if(InpSweepBadRiskMax > InpSweepBadRiskMin &&
      risk_price >= InpSweepBadRiskMin && risk_price < InpSweepBadRiskMax &&
      InpSweepBadRiskMult != 1.0)
   {
      if(InpSweepBadRiskMult <= 0)
         return -1.0;
      pos_mult *= InpSweepBadRiskMult;
   }

   if(InpSweepBadAgeMaxBars > InpSweepBadAgeMinBars &&
      InpSweepBadAgeMult != 1.0)
   {
      int age = state.bar_count - zone.created_bar;
      if(age >= InpSweepBadAgeMinBars && age < InpSweepBadAgeMaxBars)
      {
         if(InpSweepBadAgeMult <= 0)
            return -1.0;
         pos_mult *= InpSweepBadAgeMult;
      }
   }

   return pos_mult;
}

double ApplyHTFPullbackContextPositionMultiplier(const OBZone &zone, const TradeSignal &signal,
                                                 double risk_price, double pos_mult)
{
   if(!zone.is_htf_pullback)
      return pos_mult;

   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);

   if(InpHTFPullbackAllowHours != "" && !IsHourBlocked(InpHTFPullbackAllowHours, dt.hour))
      return -1.0;
   if(IsHourBlocked(InpHTFPullbackNoHours, dt.hour))
      return -1.0;

   if(InpHTFPullbackRiskMax > InpHTFPullbackRiskMin &&
      (risk_price < InpHTFPullbackRiskMin || risk_price >= InpHTFPullbackRiskMax))
      return -1.0;

   if(signal.confirm_ob_pos < InpHTFPullbackConfirmMin ||
      signal.confirm_ob_pos >= InpHTFPullbackConfirmMax)
      return -1.0;

   if(InpHTFPullbackContextMult != 1.0)
   {
      if(InpHTFPullbackContextMult <= 0)
         return -1.0;
      pos_mult *= InpHTFPullbackContextMult;
   }

   return pos_mult;
}

double ApplyOBContextPositionMultiplier(const OBZone &zone, double pos_mult)
{
   if(zone.is_liquidity_sweep || zone.is_range_breakout || zone.is_htf_pullback)
      return pos_mult;

   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);

   if(InpOBPosMult != 1.0)
   {
      if(InpOBPosMultMinBalance > 0 && AccountInfoDouble(ACCOUNT_BALANCE) < InpOBPosMultMinBalance)
         return pos_mult;
      if(InpOBPosMult <= 0)
         return -1.0;
      pos_mult *= InpOBPosMult;
   }

   if(InpOBBadHours != "" && InpOBBadHourMult != 1.0 &&
      IsHourBlocked(InpOBBadHours, dt.hour))
   {
      if(InpOBBadHourMult <= 0)
         return -1.0;
      pos_mult *= InpOBBadHourMult;
   }

   if(InpLowBalanceOBBadHours == "" || InpLowBalanceOBBadHourMult == 1.0 ||
      InpLowBalanceOBBadMaxMonthStartBalance <= 0)
      return pos_mult;

   SyncMonthlyRiskState();
   if(g_monthly_start_balance <= 0 ||
      g_monthly_start_balance > InpLowBalanceOBBadMaxMonthStartBalance)
      return pos_mult;

   if(!IsMonthAllowed(InpLowBalanceOBBadMonths, dt.mon))
      return pos_mult;

   if(!IsHourBlocked(InpLowBalanceOBBadHours, dt.hour))
      return pos_mult;

   if(InpLowBalanceOBBadHourMult <= 0)
      return -1.0;
   return pos_mult * InpLowBalanceOBBadHourMult;
}

double ApplyHTFNetPushPositionMultiplier(int direction, double pos_mult)
{
   if(!CfgEnableHTFNetPushFilter() || CfgHTFNetPushMinATR() <= 0)
      return pos_mult;

   int bars = MathMax(CfgHTFNetPushBars(), 1);
   int need = bars + InpATRPeriod + 1;
   ENUM_TIMEFRAMES tf = MinutesToTF(CfgHTFNetPushTF());

   MqlRates rates[];
   int count = CopyRates(_Symbol, tf, 1, need, rates);
   if(count < bars + 1)
      return pos_mult;

   double atr = CalcATR(rates, count, InpATRPeriod);
   if(atr <= 0)
      return pos_mult;

   int start = count - bars;
   double net_move = (rates[count - 1].close - rates[start].open) * direction;
   double base_price = rates[start].open;
   double net_metric;
   double threshold;
   if(InpHTFNetPushMinPct > 0 && base_price > 0)
   {
      net_metric = net_move / base_price * 100.0;
      threshold = InpHTFNetPushMinPct;
   }
   else
   {
      net_metric = (atr > 0) ? net_move / atr : 0;
      threshold = CfgHTFNetPushMinATR();
   }
   double mult = CfgHTFNetPushNeutralMult();

   if(net_metric >= threshold)
   {
      mult = CfgHTFNetPushAlignedMult();
      double dir_scale = (direction < 0) ? InpHTFNetPushSellAlignedScale : InpHTFNetPushBuyAlignedScale;
      mult *= dir_scale;
   }
   else if(net_metric <= -threshold)
   {
      mult = CfgHTFNetPushCounterMult();
      double dir_scale = (direction < 0) ? InpHTFNetPushSellCounterScale : InpHTFNetPushBuyCounterScale;
      mult *= dir_scale;
   }
   else
   {
      double dir_scale = (direction < 0) ? InpHTFNetPushSellNeutralScale : InpHTFNetPushBuyNeutralScale;
      mult *= dir_scale;
   }

   if(mult <= 0)
      return -1.0;
   return pos_mult * mult;
}

bool PassOBReentryCooldown(const OBZone &zone)
{
   int max_entries = CfgMaxEntriesPerOB();
   if(max_entries > 0 && zone.entry_count >= max_entries)
      return false;

   if(CfgOBReentryCooldownMin() <= 0 || zone.last_entry_time == 0)
      return true;
   return (TimeCurrent() - zone.last_entry_time >= CfgOBReentryCooldownMin() * 60);
}

double ApplyReentryPositionMultiplier(const OBZone &zone, double pos_mult)
{
   if(zone.entry_count <= 0 || InpReentryPosMult == 1.0)
      return pos_mult;
   if(InpReentryPosMult <= 0)
      return -1.0;
   return pos_mult * InpReentryPosMult;
}

double ApplyContinuationPositionMultiplier(const OBZone &zone, double pos_mult)
{
   if(!zone.is_continuation || CfgContinuationPosMult() == 1.0)
      return pos_mult;
   if(CfgContinuationPosMult() <= 0)
      return -1.0;
   return pos_mult * CfgContinuationPosMult();
}

bool PassContinuationAgeFilter(const OBZone &zone, const EAState &state, bool deep_entry)
{
   if(CfgFilterContAgeMaxBars() <= 0)
      return true;
   if(CfgFilterContAgeMaxBars() < CfgFilterContAgeMinBars())
      return true;
   if(!zone.is_continuation)
      return true;

   int age = state.bar_count - zone.created_bar;
   if(age < CfgFilterContAgeMinBars() || age > CfgFilterContAgeMaxBars())
      return true;
   if(CfgFilterContNonDeepOnly() && deep_entry)
      return true;

   return false;
}

double ApplyBuyNoH1PositionFilter(const OBZone &zone, int direction, double pos_mult)
{
   if(InpFilterBuyNoH1MaxPosMult <= 0 || InpFilterBuyNoH1PosMult == 1.0)
      return pos_mult;
   if(direction != OB_BUY || zone.is_1h_aligned)
      return pos_mult;

   double min_mult = MathMax(0.0, InpFilterBuyNoH1MinPosMult);
   if(pos_mult < min_mult || pos_mult > InpFilterBuyNoH1MaxPosMult)
      return pos_mult;
   if(InpFilterBuyNoH1PosMult <= 0)
      return -1.0;

   return pos_mult * InpFilterBuyNoH1PosMult;
}

double CalcEntryLot(string symbol, double risk_pct, double risk_price, double pos_mult)
{
   double base_lot;
   if(InpFixedLotSize > 0)
      base_lot = InpFixedLotSize;
   else
      base_lot = CalcLotSize(symbol, risk_pct, risk_price);
   return base_lot * pos_mult;
}

bool FinalizeEntryEngineSignal(string symbol, const OBZone &zone, const EAState &state,
                               TradeSignal &signal)
{
   if(zone.expired || zone.used)
   {
      if(InpEnableEntryDebug) Print("FINAL_DIAG z=", signal.ob_index, " dir=", signal.direction, " skip=expired/used");
      return false;
   }

   if(!PassOBReentryCooldown(zone))
   {
      if(InpEnableEntryDebug) Print("FINAL_DIAG z=", signal.ob_index, " dir=", signal.direction, " skip=cooldown");
      return false;
   }

   if(!PassDirectionEntryHours(signal.direction, TimeCurrent()))
   {
      if(InpEnableEntryDebug) Print("FINAL_DIAG z=", signal.ob_index, " dir=", signal.direction, " skip=entry_hours");
      return false;
   }

   if(!PassMonthlyEntryGuard())
      return false;

   if(!PassEntryMomentumFilter(signal.direction))
   {
      if(InpEnableEntryDebug) Print("FINAL_DIAG z=", signal.ob_index, " dir=", signal.direction, " skip=momentum");
      return false;
   }

   double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
   double spread = GetSpread(symbol);

   double entry = (signal.direction == OB_BUY) ? ask : bid;
   double risk_price = MathAbs(entry - signal.sl);
   if(risk_price <= 0)
   {
      if(InpEnableEntryDebug) Print("FINAL_DIAG z=", signal.ob_index, " dir=", signal.direction, " skip=risk_price_zero");
      return false;
   }

   double confirm_entry = signal.entry;
   if(confirm_entry <= 0)
      confirm_entry = (signal.direction == OB_BUY) ? zone.high : zone.low;
   if(CfgMaxEntryOffsetR() > 0 && MathAbs(entry - confirm_entry) / risk_price > CfgMaxEntryOffsetR())
   {
      if(InpEnableEntryDebug) Print("FINAL_DIAG z=", signal.ob_index, " dir=", signal.direction, " skip=offset_r offset=", MathAbs(entry - confirm_entry) / risk_price, " max=", CfgMaxEntryOffsetR());
      return false;
   }

   if(!PassSpreadRatio(risk_price, spread))
   {
      if(InpEnableEntryDebug) Print("FINAL_DIAG z=", signal.ob_index, " dir=", signal.direction, " skip=spread_ratio risk=", risk_price, " spread=", spread);
      return false;
   }

   // EntryEngine确认后用真实可成交价重新过8-Gap，避免监控阶段和执行阶段口径漂移。
   double min_strength = GetDirectionMinStrength(signal.direction);
   if(min_strength > 0 && zone.strength < min_strength)
   {
      if(InpEnableEntryDebug) Print("FINAL_DIAG z=", signal.ob_index, " dir=", signal.direction, " skip=min_strength strength=", zone.strength, " min=", min_strength);
      return false;
   }

   if(InpMaxRiskATR > 0 && state.atr_value > 0 && risk_price > state.atr_value * InpMaxRiskATR)
   {
      if(InpEnableEntryDebug) Print("FINAL_DIAG z=", signal.ob_index, " dir=", signal.direction, " skip=max_risk_atr risk=", risk_price, " max=", state.atr_value * InpMaxRiskATR);
      return false;
   }

   if(InpMaxCounterRiskATR > 0 && state.atr_value > 0 &&
      zone.is_1h_aligned == false && risk_price > state.atr_value * InpMaxCounterRiskATR)
   {
      if(InpEnableEntryDebug) Print("FINAL_DIAG z=", signal.ob_index, " dir=", signal.direction, " skip=counter_risk_atr risk=", risk_price, " max=", state.atr_value * InpMaxCounterRiskATR);
      return false;
   }

   if(ShouldApplyContextReverse(signal.direction, entry, risk_price))
   {
      int rev_dir = (signal.direction == OB_BUY) ? OB_SELL : OB_BUY;
      double rev_entry = (rev_dir == OB_BUY) ? ask : bid;
      double rev_risk = risk_price * MathMax(InpContextReverseRiskMult, 0.1);
      signal.direction = rev_dir;
      signal.sl = (rev_dir == OB_BUY) ? rev_entry - rev_risk : rev_entry + rev_risk;
      signal.tp = (InpContextReverseTPR > 0) ?
         RToPrice(InpContextReverseTPR, rev_entry, rev_risk, rev_dir) : 0.0;
      entry = rev_entry;
      risk_price = rev_risk;
   }

   double pos_mult = signal.pos_mult;
   if(CfgEnableScoring())
   {
      double proximity_distance = MathAbs(bid - entry);
      double tp_est = CalcLiquiditySweepTP(zone, entry);
      if(tp_est == 0.0)
         tp_est = CalcHTFPullbackTP(zone, entry);
      if(tp_est == 0.0)
         tp_est = CalcOBHeightTP(zone, entry);
      if(tp_est == 0.0 && CfgDTPTriggerR() <= 0 && CfgFixedTPR() > 0)
         tp_est = RToPrice(CfgFixedTPR(), entry, risk_price, signal.direction);
      else if(tp_est == 0.0 && CfgEnableStateFilter() && state.market_state == 0 && state.target_price > 0)
         tp_est = state.target_price;
      else if(tp_est == 0.0)
         tp_est = RToPrice(2.0, entry, risk_price, signal.direction);
      double target_distance = MathAbs(tp_est - entry);
      int score = CalcSignalScore(zone, state, state.market_state,
                                  proximity_distance, risk_price, target_distance);
      if(CfgMinScore() > 0 && score < CfgMinScore())
      {
         if(InpEnableEntryDebug) Print("FINAL_DIAG z=", signal.ob_index, " dir=", signal.direction, " skip=score score=", score, " min=", CfgMinScore());
         return false;
      }
      pos_mult = ScoreToMultiplier(score);
      if(pos_mult < 0)
      {
         if(InpEnableEntryDebug) Print("FINAL_DIAG z=", signal.ob_index, " dir=", signal.direction, " skip=pos_mult_neg score=", score);
         return false;
      }
   }
   else
   {
      pos_mult = InpEnablePosMult ? CalcPositionMultiplier(zone) : 1.0;
   }
   if(signal.deep_entry && InpDeepEntryBoost > 1.0)
      pos_mult *= InpDeepEntryBoost;
   pos_mult = ApplySignalTypePositionMultiplier(zone, pos_mult);
   pos_mult = ApplyDirectionPosMult(signal.direction, pos_mult);
   pos_mult = ApplyHourPositionMultiplier(pos_mult);
   pos_mult = ApplyContextFilterPositionMultiplier(signal.direction, pos_mult);
   pos_mult = ApplyEntryQualityPositionMultiplier(signal, risk_price, pos_mult);
   pos_mult = ApplyBadClusterPositionMultiplier(zone, signal, risk_price, pos_mult);
   pos_mult = ApplyStartupBadClusterPositionMultiplier(zone, signal, risk_price, pos_mult);
   pos_mult = ApplySweepContextPositionMultiplier(zone, state, signal, risk_price, pos_mult);
   pos_mult = ApplyHTFPullbackContextPositionMultiplier(zone, signal, risk_price, pos_mult);
   pos_mult = ApplyOBContextPositionMultiplier(zone, pos_mult);
   pos_mult = ApplyReentryPositionMultiplier(zone, pos_mult);
   pos_mult = ApplyContinuationPositionMultiplier(zone, pos_mult);
   if(pos_mult < 0)
      return false;
   pos_mult = ApplyHTFNetPushPositionMultiplier(signal.direction, pos_mult);
   pos_mult = ApplyBalancePositionMultiplier(pos_mult);
   pos_mult = ApplyMonthlyPositionMultiplier(pos_mult);
   pos_mult = ApplyPositionMultiplierCap(pos_mult);
   if(!PassContinuationAgeFilter(zone, state, signal.deep_entry))
   {
      if(InpEnableEntryDebug) Print("FINAL_DIAG z=", signal.ob_index, " dir=", signal.direction, " skip=continuation_age");
      return false;
   }
   pos_mult = ApplyBuyNoH1PositionFilter(zone, signal.direction, pos_mult);
   if(pos_mult < 0)
   {
      if(InpEnableEntryDebug) Print("FINAL_DIAG z=", signal.ob_index, " dir=", signal.direction, " skip=buy_no_h1 pos_mult=", pos_mult);
      return false;
   }

   double final_lot = CalcEntryLot(symbol, CfgRiskPercent(), risk_price, pos_mult);
   final_lot = ApplyLotCap(final_lot);
   final_lot = ApplySignalTypeLotCap(zone, final_lot);
   final_lot = ApplyBalanceLotCap(final_lot);
   if(!PassMinRisk(final_lot, risk_price, symbol))
   {
      if(InpEnableEntryDebug) Print("FINAL_DIAG z=", signal.ob_index, " dir=", signal.direction, " skip=min_risk lot=", final_lot, " risk=", risk_price);
      return false;
   }

   double margin_required = 0;
   ENUM_ORDER_TYPE order_type = (signal.direction == OB_BUY) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   if(!OrderCalcMargin(order_type, symbol, final_lot, entry, margin_required))
   {
      if(InpEnableEntryDebug) Print("FINAL_DIAG z=", signal.ob_index, " dir=", signal.direction, " skip=margin_calc");
      return false;
   }

   double free_margin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   if(margin_required > free_margin)
   {
      if(free_margin <= 0)
      {
         if(InpEnableEntryDebug) Print("FINAL_DIAG z=", signal.ob_index, " dir=", signal.direction, " skip=free_margin_zero");
         return false;
      }
      final_lot = final_lot * (free_margin / margin_required) * 0.95;
      final_lot = ApplyLotCap(final_lot);
      final_lot = ApplySignalTypeLotCap(zone, final_lot);
      final_lot = ApplyBalanceLotCap(final_lot);
   }

   double lot_min = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double lot_max = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double lot_step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   if(lot_step <= 0)
   {
      if(InpEnableEntryDebug) Print("FINAL_DIAG z=", signal.ob_index, " dir=", signal.direction, " skip=lot_step_zero");
      return false;
   }

   final_lot = MathFloor(final_lot / lot_step) * lot_step;
   if(final_lot < lot_min)
   {
      if(InpForceMinLot)
         final_lot = lot_min;
      else
      {
         if(InpEnableEntryDebug) Print("FINAL_DIAG z=", signal.ob_index, " dir=", signal.direction, " skip=lot_min final_lot=", final_lot, " min=", lot_min);
         return false;
      }
   }
   if(final_lot > lot_max)
      final_lot = lot_max;

   // v11: 入场时按状态决定TP模式
   double tp = 0.0;
   if(zone.is_htf_pullback)
   {
      tp = CalcHTFPullbackTP(zone, entry);
      if(tp == 0.0 && CfgDTPTriggerR() <= 0 && CfgFixedTPR() > 0)
         tp = RToPrice(CfgFixedTPR(), entry, risk_price, signal.direction);
   }
   else if(zone.is_liquidity_sweep)
   {
      tp = CalcLiquiditySweepTP(zone, entry);
      if(tp == 0.0 && CfgDTPTriggerR() <= 0 && CfgFixedTPR() > 0)
         tp = RToPrice(CfgFixedTPR(), entry, risk_price, signal.direction);
   }
   else if(CfgEnableStateFilter() && state.market_state == 0)
   {
      // 震荡态: OBHeight TP优先，其次swing目标，最后固定TP
      tp = CalcOBHeightTP(zone, entry);
      if(tp == 0.0 && state.target_price > 0)
      {
         double swing_dist = MathAbs(state.target_price - entry);
         if(swing_dist > risk_price)
            tp = state.target_price;
      }
      if(tp == 0.0 && CfgFixedTPR() > 0)
         tp = RToPrice(CfgFixedTPR(), entry, risk_price, signal.direction);
   }
   else
   {
      // 趋势态: tp=0让DTP接管，除非没有DTP则用固定TP兜底
      if(CfgDTPTriggerR() <= 0 && CfgFixedTPR() > 0)
         tp = RToPrice(CfgFixedTPR(), entry, risk_price, signal.direction);
   }

   signal.entry = entry;
   signal.risk_price = risk_price;
   signal.lot = NormalizeDouble(final_lot, 2);
   signal.pos_mult = pos_mult;
   signal.tp = tp;
   signal.htf_target = false;
   signal.htf_partial_r = 0;
   signal.htf_partial_pct = 0;
   ApplyHTFTarget(symbol, entry, risk_price, signal);
   PrintEntryDebug("entry_engine", zone, state, signal, entry, risk_price, spread, pos_mult,
                   CfgEnableScoring() ? CalcSignalScore(zone, state, state.market_state,
                                                      MathAbs(bid - entry), risk_price,
                                                      MathAbs(RToPrice(2.0, entry, risk_price, signal.direction) - entry))
                                    : -1);
   signal.comment = "WT " + InpVersion + " " + (signal.direction > 0 ? "B" : "S") +
                    (zone.is_range_breakout ? " RB" : "") +
                    (zone.is_htf_pullback ? " HTFPB" : "") +
                    (IsLooseSweepZone(zone) ? " LSWP" : "") +
                    (zone.is_liquidity_sweep ? " SWP" : "") +
                    " x" + DoubleToString(pos_mult, 1);

   if(InpEnableEntryDebug) Print("FINAL_DIAG z=", signal.ob_index, " dir=", signal.direction, " status=PASS lot=", final_lot, " entry=", entry, " sl=", signal.sl);
   return true;
}

int ScanSignals(string symbol, const OBZone &zones[], int zone_count,
                const EAState &state, TradeSignal &signals[], int max_signals)
{
   // H4高波动屏蔽：使用H4时间框架的标准ATR与M5 ATR比较
   // 当H4 ATR（14周期）> M5 ATR × 阈值 → 市场高波动，停止M5 OB开仓
   if(InpEnableHTFVolBlock && state.atr_value > 0)
   {
      ENUM_TIMEFRAMES htfTF = MinutesToTF(InpHTFVolBlockTF);
      MqlRates htfRates[];
      int needed = InpHTFVolBlockPeriod + 2;
      if(CopyRates(symbol, htfTF, 1, needed, htfRates) >= needed)  // shift=1 跳过未完成bar
      {
         int cnt = ArraySize(htfRates);
         double htf_atr = 0;
         for(int _i = 1; _i < cnt; _i++)
         {
            double tr = htfRates[_i].high - htfRates[_i].low;
            double tr2 = MathAbs(htfRates[_i].high - htfRates[_i-1].close);
            double tr3 = MathAbs(htfRates[_i].low  - htfRates[_i-1].close);
            if(tr2 > tr) tr = tr2;
            if(tr3 > tr) tr = tr3;
            htf_atr += tr;
         }
         htf_atr /= (cnt - 1);
         // H4 ATR与M5 ATR的比值：正常市场约4-8x，高波动时>10x
         if(htf_atr > InpHTFVolBlockATRMult * state.atr_value)
            return 0;  // 高波动期，暂停M5 OB新开仓
      }
   }
   int count = 0;
   int best_idx = -1;
   double best_strength = 0;

   for(int i = 0; i < zone_count && count < max_signals; i++)
   {
      if(zones[i].expired || zones[i].used)
         continue;

      TradeSignal sig;
      if(CheckEntryConditions(symbol, zones[i], i, state, sig))
      {
         if(sig.pos_mult > best_strength)
         {
            best_strength = sig.pos_mult;
            best_idx = count;
         }
         signals[count] = sig;
         count++;
      }
   }

   if(count > 1 && best_idx > 0)
   {
      TradeSignal tmp = signals[0];
      signals[0] = signals[best_idx];
      signals[best_idx] = tmp;
   }

   return count;
}

bool CheckEntryConditions(string symbol, const OBZone &zone, int zone_idx,
                          const EAState &state, TradeSignal &signal)
{
   if(IsInCooldown(state))
      return false;

   if(CountPositions() >= CfgMaxConcurrent())
      return false;

   if(!PassOBReentryCooldown(zone))
      return false;

   if(!PassDirectionEntryHours(zone.direction, TimeCurrent()))
      return false;

   if(!PassMonthlyEntryGuard())
      return false;

   if(!PassEntryMomentumFilter(zone.direction))
      return false;

   double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
   double spread = GetSpread(symbol);

   if(!IsZoneTouched(zone, bid, ask))
      return false;

   if(!zone.is_range_breakout && !PassDoubleTouchFilter(zone))
      return false;

   // v9.8 态过滤: 趋势态硬过滤逆势
   if(CfgEnableStateFilter() && state.market_state != 0 && state.market_state != zone.direction)
      return false;

   double sl = 0;
   if(zone.direction == OB_BUY)
   {
      // 引线锚点：ob_bottom存储OB K线完整低点（含下引线），比实体底更低更真实
      double sl_base = (zone.ob_bottom > 0 && zone.ob_bottom < zone.low) ? zone.ob_bottom : zone.low;
      sl = sl_base - state.atr_value * CfgSLBufferATR();
   }
   else
   {
      // 引线锚点：ob_top存储OB K线完整高点（含上引线），比实体顶更高更真实
      double sl_base = (zone.ob_top > 0 && zone.ob_top > zone.high) ? zone.ob_top : zone.high;
      sl = sl_base + state.atr_value * CfgSLBufferATR();
   }

   double entry = (zone.direction == OB_BUY) ? ask : bid;
   double risk_price = MathAbs(entry - sl);

   if(risk_price <= 0)
      return false;

   if(!zone.is_range_breakout && !PassOffsetGuard(entry, risk_price, zone.direction, zone.mid, CfgMaxEntryOffsetR()))
      return false;

   if(!PassSpreadRatio(risk_price, spread))
      return false;

   // Gap5: 信号质量门槛
   double min_strength = GetDirectionMinStrength(zone.direction);
   if(min_strength > 0 && zone.strength < min_strength)
      return false;

   // Gap7: risk不能太大
   if(InpMaxRiskATR > 0 && state.atr_value > 0 && risk_price > state.atr_value * InpMaxRiskATR)
      return false;

   // Gap8: 逆势 + risk大 → 丢弃
   if(InpMaxCounterRiskATR > 0 && state.atr_value > 0 &&
      zone.is_1h_aligned == false && risk_price > state.atr_value * InpMaxCounterRiskATR)
      return false;

   // v9.8 评分系统
   double pos_mult = 1.0;
   int score = -1;
   if(CfgEnableScoring())
   {
      double proximity_distance = MathAbs(bid - entry);
      double tp_est = CalcLiquiditySweepTP(zone, entry);
      if(tp_est == 0.0)
         tp_est = CalcHTFPullbackTP(zone, entry);
      if(tp_est == 0.0)
         tp_est = CalcOBHeightTP(zone, entry);
      if(tp_est == 0.0 && CfgDTPTriggerR() <= 0 && CfgFixedTPR() > 0)
         tp_est = RToPrice(CfgFixedTPR(), entry, risk_price, zone.direction);
      else if(tp_est == 0.0 && CfgEnableStateFilter() && state.market_state == 0 && state.target_price > 0)
         tp_est = state.target_price;
      else if(tp_est == 0.0)
         tp_est = RToPrice(2.0, entry, risk_price, zone.direction);
      double target_distance = MathAbs(tp_est - entry);
      score = CalcSignalScore(zone, state, state.market_state,
                              proximity_distance, risk_price, target_distance);
      if(CfgMinScore() > 0 && score < CfgMinScore())
         return false;
      pos_mult = ScoreToMultiplier(score);
      if(pos_mult < 0)
         return false;
   }
   else
   {
      pos_mult = InpEnablePosMult ? CalcPositionMultiplier(zone) : 1.0;
   }
   double entry_depth_pct = GetEffectiveEntryDepthPct();
   bool deep_entry = (entry_depth_pct > 0);
   if(entry_depth_pct > 0 && InpDeepEntryBoost > 1.0)
      pos_mult *= InpDeepEntryBoost;
   pos_mult = ApplySignalTypePositionMultiplier(zone, pos_mult);
   signal.bounce_seconds = 0;
   signal.bounce_ob_pct = 0.0;
   pos_mult = ApplyDirectionPosMult(zone.direction, pos_mult);
   pos_mult = ApplyHourPositionMultiplier(pos_mult);
   pos_mult = ApplyContextFilterPositionMultiplier(zone.direction, pos_mult);
   pos_mult = ApplyEntryQualityPositionMultiplier(signal, risk_price, pos_mult);
   pos_mult = ApplyBadClusterPositionMultiplier(zone, signal, risk_price, pos_mult);
   pos_mult = ApplyStartupBadClusterPositionMultiplier(zone, signal, risk_price, pos_mult);
   pos_mult = ApplySweepContextPositionMultiplier(zone, state, signal, risk_price, pos_mult);
   pos_mult = ApplyHTFPullbackContextPositionMultiplier(zone, signal, risk_price, pos_mult);
   pos_mult = ApplyOBContextPositionMultiplier(zone, pos_mult);
   pos_mult = ApplyReentryPositionMultiplier(zone, pos_mult);
   pos_mult = ApplyContinuationPositionMultiplier(zone, pos_mult);
   if(pos_mult < 0)
      return false;
   pos_mult = ApplyHTFNetPushPositionMultiplier(zone.direction, pos_mult);
   pos_mult = ApplyBalancePositionMultiplier(pos_mult);
   pos_mult = ApplyMonthlyPositionMultiplier(pos_mult);
   pos_mult = ApplyPositionMultiplierCap(pos_mult);
   if(!PassContinuationAgeFilter(zone, state, deep_entry))
      return false;
   pos_mult = ApplyBuyNoH1PositionFilter(zone, zone.direction, pos_mult);
   if(pos_mult < 0)
      return false;
   double final_lot = CalcEntryLot(symbol, CfgRiskPercent(), risk_price, pos_mult);
   final_lot = ApplyLotCap(final_lot);
   final_lot = ApplySignalTypeLotCap(zone, final_lot);
   final_lot = ApplyBalanceLotCap(final_lot);

   if(!PassMinRisk(final_lot, risk_price, symbol))
      return false;

   double margin_required = 0;
   ENUM_ORDER_TYPE order_type = (zone.direction == OB_BUY) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   if(!OrderCalcMargin(order_type, symbol, final_lot, entry, margin_required))
      return false;

   double free_margin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   if(margin_required > free_margin)
   {
      if(free_margin <= 0)
         return false;
      final_lot = final_lot * (free_margin / margin_required) * 0.95;
      final_lot = ApplyLotCap(final_lot);
      final_lot = ApplySignalTypeLotCap(zone, final_lot);
      final_lot = ApplyBalanceLotCap(final_lot);
      double lot_min = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
      double lot_step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
      final_lot = MathFloor(final_lot / lot_step) * lot_step;
      if(final_lot < lot_min)
         return false;
   }

   double lot_min = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double lot_max = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double lot_step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   final_lot = MathFloor(final_lot / lot_step) * lot_step;
   if(final_lot < lot_min) final_lot = lot_min;
   if(final_lot > lot_max) final_lot = lot_max;

   // v11: 入场时按状态决定TP模式（直接入场路径）
   double tp = 0.0;
   if(zone.is_htf_pullback && InpHTFPullbackTPMult > 0 && zone.range_height > 0)
      tp = CalcHTFPullbackTP(zone, entry);
   else if(zone.is_range_breakout && InpRangeBreakoutTPMult > 0 && zone.range_height > 0)
      tp = entry + zone.direction * zone.range_height * InpRangeBreakoutTPMult;
   else if(zone.is_liquidity_sweep)
   {
      tp = CalcLiquiditySweepTP(zone, entry);
      if(tp == 0.0 && CfgDTPTriggerR() <= 0 && CfgFixedTPR() > 0)
         tp = RToPrice(CfgFixedTPR(), entry, risk_price, zone.direction);
   }
   else if(CfgEnableStateFilter() && state.market_state == 0)
   {
      tp = CalcOBHeightTP(zone, entry);
      if(tp == 0.0 && state.target_price > 0)
      {
         double swing_dist = MathAbs(state.target_price - entry);
         if(swing_dist > risk_price)
            tp = state.target_price;
      }
      if(tp == 0.0 && CfgFixedTPR() > 0)
         tp = RToPrice(CfgFixedTPR(), entry, risk_price, zone.direction);
   }
   else
   {
      if(CfgDTPTriggerR() <= 0 && CfgFixedTPR() > 0)
         tp = RToPrice(CfgFixedTPR(), entry, risk_price, zone.direction);
   }

   signal.direction = zone.direction;
   signal.entry = entry;
   signal.sl = sl;
   signal.tp = tp;
   signal.risk_price = risk_price;
   signal.lot = final_lot;
   signal.pos_mult = pos_mult;
   signal.ob_index = zone_idx;
   signal.deep_entry = deep_entry;
   signal.touch_price = entry;
   signal.confirm_price = entry;
   signal.bounce_seconds = 0;
   signal.bounce_ob_pct = 0.0;
   signal.confirm_ob_pos = 0.0;
   signal.htf_target = false;
   signal.htf_partial_r = 0;
   signal.htf_partial_pct = 0;
   ApplyHTFTarget(symbol, entry, risk_price, signal);
   PrintEntryDebug("direct", zone, state, signal, entry, risk_price, spread, pos_mult, score);
   signal.comment = "WT " + InpVersion + " " + (zone.direction > 0 ? "B" : "S") +
                    (zone.is_range_breakout ? " RB" : "") +
                    (zone.is_htf_pullback ? " HTFPB" : "") +
                    (IsLooseSweepZone(zone) ? " LSWP" : "") +
                    (zone.is_liquidity_sweep ? " SWP" : "") +
                    " x" + DoubleToString(pos_mult, 1);

   return true;
}

double CalcPositionMultiplier(const OBZone &zone)
{
   double base = zone.strength;
   double fresh_mult = zone.is_fresh ? 1.5 : 1.0;
   double cont_mult = zone.is_continuation ? 1.3 : 1.0;
   double boost_1h = zone.is_1h_aligned ? CfgBoostIn1HOB() : 1.0;
   double ds = InpDSWeight ? zone.ds_weight : 1.0;

   return base * fresh_mult * cont_mult * boost_1h * ds;
}

bool IsInCooldown(const EAState &state)
{
   if(CfgCooldownBars() <= 0)
      return false;
   return (state.bar_count - state.last_entry_bar) < CfgCooldownBars();
}

#endif
