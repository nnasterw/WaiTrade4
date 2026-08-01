#ifndef __WAITRADE_OB_DETECTOR_MQH__
#define __WAITRADE_OB_DETECTOR_MQH__

#include "Types.mqh"
#include "Config.mqh"
#include "Utils.mqh"

bool IsImpulse(const MqlRates &rates[], int count, int start_idx, int direction, double atr)
{
   if(atr <= 0) return false;
   int look = InpImpulseLookback;
   if(look < 1) look = 3;
   double move = 0.0;

   if(direction == OB_BUY)
   {
      double high_max = rates[start_idx].high;
      for(int i = start_idx + 1; i < start_idx + look && i < count; i++)
         if(rates[i].high > high_max) high_max = rates[i].high;
      move = high_max - rates[start_idx].low;
   }
   else
   {
      double low_min = rates[start_idx].low;
      for(int i = start_idx + 1; i < start_idx + look && i < count; i++)
         if(rates[i].low < low_min) low_min = rates[i].low;
      move = rates[start_idx].high - low_min;
   }

   double threshold = InpImpulseATRMult > 0 ? InpImpulseATRMult : 1.5;
   return (move > atr * threshold);
}

bool IsInNoOBWindow(int hour)
{
   if(CfgNoOBStartHour() < 0 || CfgNoOBEndHour() < 0)
      return false;

   int start_hour = CfgNoOBStartHour() % 24;
   int end_hour = CfgNoOBEndHour() % 24;

   if(start_hour == end_hour)
      return true;

   if(start_hour < end_hour)
      return (hour >= start_hour && hour < end_hour);

   return (hour >= start_hour || hour < end_hour);
}

bool PassOBBodyPct(const MqlRates &bar)
{
   if(InpMinOBBodyPct <= 0)
      return true;

   double body = MathAbs(bar.open - bar.close);
   double range = bar.high - bar.low;
   if(range <= 0)
      return false;

   return (body / range * 100.0 >= InpMinOBBodyPct);
}

double CalcBodyPct(const MqlRates &bar)
{
   double range = bar.high - bar.low;
   if(range <= 0)
      return 0.0;
   return MathAbs(bar.open - bar.close) / range * 100.0;
}

double CalcVolumeRatio(const MqlRates &rates[], int idx, int lookback)
{
   if(lookback <= 0)
      lookback = 30;
   int start = MathMax(0, idx - lookback);
   int count = 0;
   double sum = 0.0;
   for(int i = start; i < idx; i++)
   {
      sum += (double)rates[i].tick_volume;
      count++;
   }
   if(count <= 0)
      return 1.0;
   double avg = sum / count;
   if(avg < 1.0)
      avg = 1.0;
   return (double)rates[idx].tick_volume / avg;
}

bool PassImpulseQuality(const MqlRates &rates[], int idx)
{
   if(InpMinImpulseBodyPct > 0 && CalcBodyPct(rates[idx]) < InpMinImpulseBodyPct)
      return false;

   if(InpMinImpulseVolRatio > 0 && CalcVolumeRatio(rates, idx, 30) < InpMinImpulseVolRatio)
      return false;

   return true;
}

bool PassStrictStructureBreak(const MqlRates &rates[], int count, int ob_idx, int impulse_idx,
                              int direction, double atr)
{
   if(InpRequireImpulseCandleDir)
   {
      if(direction == OB_BUY && rates[impulse_idx].close <= rates[impulse_idx].open)
         return false;
      if(direction == OB_SELL && rates[impulse_idx].close >= rates[impulse_idx].open)
         return false;
   }

   if(InpStructureBreakBars <= 0)
      return true;
   if(impulse_idx <= 0 || impulse_idx >= count)
      return false;

   int lookback = InpStructureBreakBars;
   double extra = (atr > 0 && InpStructureBreakATR > 0) ? atr * InpStructureBreakATR : 0.0;
   int start = MathMax(0, impulse_idx - lookback);
   int end = impulse_idx - 1;
   if(start > end)
      return false;

   if(direction == OB_BUY)
   {
      double prior_high = rates[start].high;
      for(int p = start + 1; p <= end; p++)
         if(rates[p].high > prior_high) prior_high = rates[p].high;
      return (rates[impulse_idx].close > prior_high + extra);
   }

   double prior_low = rates[start].low;
   for(int p = start + 1; p <= end; p++)
      if(rates[p].low < prior_low) prior_low = rates[p].low;
   return (rates[impulse_idx].close < prior_low - extra);
}

double CalcOBStrength(const MqlRates &rates[], int ob_idx, int impulse_end, double atr, int direction)
{
   if(atr <= 0) return 1.0;

   double impulse_size = 0.0;
   if(direction == OB_BUY)
   {
      double high_max = rates[ob_idx + 1].high;
      for(int i = ob_idx + 1; i <= impulse_end; i++)
         if(rates[i].high > high_max) high_max = rates[i].high;
      impulse_size = high_max - rates[ob_idx].low;
   }
   else
   {
      double low_min = rates[ob_idx + 1].low;
      for(int i = ob_idx + 1; i <= impulse_end; i++)
         if(rates[i].low < low_min) low_min = rates[i].low;
      impulse_size = rates[ob_idx].high - low_min;
   }

   double ratio = impulse_size / atr;
   double score_impulse = MathMin(ratio - 1.0, 2.0);
   if(score_impulse < 0) score_impulse = 0;

   double ob_range = rates[ob_idx].high - rates[ob_idx].low;
   double score_width = 0.0;
   if(ob_range > 0 && ob_range < atr * 0.5)
      score_width = 1.0;
   else if(ob_range <= atr)
      score_width = 0.5;

   double score_fresh = 1.0;

   double score_position = 0.0;
   double body = MathAbs(rates[ob_idx].close - rates[ob_idx].open);
   if(ob_range > 0 && body / ob_range > 0.6)
      score_position = 1.0;
   else if(ob_range > 0 && body / ob_range > 0.4)
      score_position = 0.5;

   double total = 1.0 + score_impulse + score_width + score_fresh + score_position;
   if(total > 5.0) total = 5.0;
   if(total < 1.0) total = 1.0;
   return total;
}

double CalcDSWeight(const MqlRates &rates[], int count, int ob_idx)
{
   int look_back = 10;
   int start = ob_idx - look_back;
   if(start < 0) start = 0;

   double bull_power = 0.0;
   double bear_power = 0.0;

   for(int i = start; i < ob_idx; i++)
   {
      double body = rates[i].close - rates[i].open;
      double range = rates[i].high - rates[i].low;
      if(range <= 0) continue;

      if(body > 0)
         bull_power += body / range * (rates[i].high - rates[i].low);
      else
         bear_power += MathAbs(body) / range * (rates[i].high - rates[i].low);
   }

   double total = bull_power + bear_power;
   if(total <= 0) return 1.0;

   double imbalance = MathAbs(bull_power - bear_power) / total;
   double weight = 0.5 + imbalance * 2.0;
   if(weight > 2.5) weight = 2.5;
   if(weight < 0.5) weight = 0.5;
   return weight;
}

void UpdateOBStatus(OBZone &zones[], int &zone_count, double bid, double ask, const EAState &state)
{
   datetime now = TimeCurrent();

   for(int i = zone_count - 1; i >= 0; i--)
   {
      if(zones[i].expired) continue;

      if(zones[i].used)
      {
         zones[i].expired = true;
         continue;
      }

      int bars_alive = state.bar_count - zones[i].created_bar;
      if(bars_alive > InpBars)
      {
         zones[i].expired = true;
         continue;
      }

      long minutes_alive = (long)(now - zones[i].created) / 60;
      // Gap6: 动态TTL — 高strength OB活更久, 低strength快过期
      int ttl_minutes = CfgTimeoutMin();
      if(zones[i].strength >= 2.0) ttl_minutes = (int)(CfgTimeoutMin() * 1.5);
      else if(zones[i].strength < 1.0) ttl_minutes = (int)(CfgTimeoutMin() * 0.5);
      if(minutes_alive > ttl_minutes)
      {
         zones[i].expired = true;
         continue;
      }

      bool touched = false;
      if(zones[i].is_range_breakout)
      {
         if(zones[i].direction == OB_BUY && bid >= zones[i].high)
            touched = true;
         else if(zones[i].direction == OB_SELL && ask <= zones[i].low)
            touched = true;
      }
      else
      {
         if(zones[i].direction == OB_BUY && bid <= zones[i].high)
            touched = true;
         else if(zones[i].direction == OB_SELL && ask >= zones[i].low)
            touched = true;
      }

      if(touched)
      {
         zones[i].touch_count++;
         zones[i].last_touch = now;
         if(zones[i].first_touch == 0)
            zones[i].first_touch = now;
         zones[i].is_fresh = false;
      }
   }
}

void ConsolidateOBs(OBZone &zones[], int &zone_count)
{
   for(int i = 0; i < zone_count - 1; i++)
   {
      if(zones[i].expired) continue;

      for(int j = i + 1; j < zone_count; j++)
      {
         if(zones[j].expired) continue;
         if(zones[i].direction != zones[j].direction) continue;
         if(zones[i].is_range_breakout || zones[j].is_range_breakout) continue;
         if(zones[i].is_liquidity_sweep || zones[j].is_liquidity_sweep) continue;
         if(zones[i].is_htf_pullback || zones[j].is_htf_pullback) continue;

         bool overlap = (zones[i].low <= zones[j].high && zones[i].high >= zones[j].low);
         if(!overlap) continue;

         zones[i].high = MathMax(zones[i].high, zones[j].high);
         zones[i].low = MathMin(zones[i].low, zones[j].low);
         zones[i].mid = (zones[i].high + zones[i].low) / 2.0;
         if(zones[j].strength > zones[i].strength)
            zones[i].strength = zones[j].strength;
         if(zones[j].ds_weight > zones[i].ds_weight)
            zones[i].ds_weight = zones[j].ds_weight;

         zones[j].expired = true;
      }
   }
}

int Detect1HOBDirection(string symbol)
{
   MqlRates rates_1h[];
   int copied = CopyRates(symbol, PERIOD_H1, 0, 50, rates_1h);
   if(copied < 20) return 0;

   double atr_1h = CalcATR(rates_1h, copied, InpATRPeriod);
   if(atr_1h <= 0) return 0;

   int look = InpImpulseLookback > 0 ? InpImpulseLookback : 3;
   for(int i = copied - (look + 1); i >= 1; i--)
   {
      if(rates_1h[i].close < rates_1h[i].open)
      {
         if(IsImpulse(rates_1h, copied, i + 1, OB_BUY, atr_1h))
            return OB_BUY;
      }

      if(rates_1h[i].close > rates_1h[i].open)
      {
         if(IsImpulse(rates_1h, copied, i + 1, OB_SELL, atr_1h))
            return OB_SELL;
      }
   }
   return 0;
}

void MarkZoneUsed(OBZone &zones[], int index)
{
    if(index >= 0 && index < MAX_OB_ZONES)
    {
        int max_entries = CfgMaxEntriesPerOB();
        if(max_entries < 1)
            max_entries = 1;

        zones[index].entry_count++;
        zones[index].last_entry_time = TimeCurrent();
        if(zones[index].entry_count >= max_entries)
            zones[index].used = true;
    }
}

void Update1HAlignment(OBZone &zones[], int zone_count, int h1_direction)
{
    for(int i = 0; i < zone_count; i++)
    {
        if(!zones[i].expired && !zones[i].used)
            zones[i].is_1h_aligned = (zones[i].direction == h1_direction);
    }
}

void CompactZones(OBZone &zones[], int &zone_count)
{
   int write = 0;
   for(int read = 0; read < zone_count; read++)
   {
      if(!zones[read].expired)
      {
         if(write != read)
            zones[write] = zones[read];
         write++;
      }
   }
   zone_count = write;
}

bool DetectContinuation(const MqlRates &rates[], int count, int ob_idx, int direction)
{
   int ma_period = 20;
   if(ob_idx < ma_period) return false;

   double sum = 0;
   for(int i = ob_idx - ma_period; i < ob_idx; i++)
      sum += rates[i].close;
   double ma = sum / ma_period;

   if(direction == OB_BUY)
      return (rates[ob_idx].close > ma);
   else
      return (rates[ob_idx].close < ma);
}

void DetectRangeBreakouts(const MqlRates &rates[], int count, OBZone &zones[], int &zone_count,
                          const EAState &state, double atr, double spread)
{
   if(!InpEnableRangeBreakout)
      return;
   if(zone_count >= MAX_OB_ZONES)
      return;

   int range_bars = InpRangeBreakoutBars;
   if(range_bars < 3)
      range_bars = 3;

   int breakout_idx = count - 2; // new bar 后，上一根K线已收盘
   int range_end = breakout_idx - 1;
   int range_start = range_end - range_bars + 1;
   if(range_start < 0 || breakout_idx <= 0)
      return;

   MqlDateTime dt;
   TimeToStruct(rates[breakout_idx].time, dt);
   if(IsInNoOBWindow(dt.hour))
      return;

   double range_high = rates[range_start].high;
   double range_low = rates[range_start].low;
   for(int i = range_start + 1; i <= range_end; i++)
   {
      if(rates[i].high > range_high) range_high = rates[i].high;
      if(rates[i].low < range_low) range_low = rates[i].low;
   }

   double range_height = range_high - range_low;
   if(range_height <= 0)
      return;
   if(InpRangeBreakoutMaxATR > 0 && atr > 0 && range_height > atr * InpRangeBreakoutMaxATR)
      return;
   if(InpRangeBreakoutMinSpreadMult > 0 && spread > 0 &&
      range_height < spread * InpRangeBreakoutMinSpreadMult)
      return;

   double extra = (atr > 0 && InpRangeBreakoutATR > 0) ? atr * InpRangeBreakoutATR : 0.0;
   int direction = 0;
   if(rates[breakout_idx].close > range_high + extra)
      direction = OB_BUY;
   else if(rates[breakout_idx].close < range_low - extra)
      direction = OB_SELL;
   else
      return;

   if(InpRangeBreakoutBodyDir)
   {
      if(direction == OB_BUY && rates[breakout_idx].close <= rates[breakout_idx].open)
         return;
      if(direction == OB_SELL && rates[breakout_idx].close >= rates[breakout_idx].open)
         return;
   }

   for(int z = 0; z < zone_count; z++)
   {
      if(zones[z].expired) continue;
      if(!zones[z].is_range_breakout) continue;
      if(zones[z].direction != direction) continue;
      if(MathAbs(zones[z].high - range_high) < atr * 0.2 &&
         MathAbs(zones[z].low - range_low) < atr * 0.2)
         return;
   }

   OBZone zone = {};
   zone.high = range_high;
   zone.low = range_low;
   zone.mid = (zone.high + zone.low) / 2.0;
   zone.ob_top = zone.high;
   zone.ob_bottom = zone.low;
   zone.direction = direction;
   zone.created = rates[breakout_idx].time;
   zone.created_bar = state.bar_count;
   zone.touch_count = range_bars;
   zone.first_touch = rates[range_start].time;
   zone.last_touch = rates[range_end].time;
   zone.strength = MathMin(5.0, 1.0 + (double)range_bars / 6.0 + MathAbs(rates[breakout_idx].close - rates[breakout_idx].open) / atr);
   zone.is_fresh = false;
   zone.is_continuation = true;
   zone.is_1h_aligned = false;
   zone.ds_weight = 1.0;
   zone.entry_count = 0;
   zone.last_entry_time = 0;
   zone.used = false;
   zone.expired = false;
   zone.is_range_breakout = true;
   zone.range_height = range_height;

   zones[zone_count] = zone;
   zone_count++;
}

bool IsLooseSweepZoneForCapacity(const OBZone &zone)
{
   return zone.is_liquidity_sweep && zone.is_loose_sweep;
}

bool IsSupplementalZoneForCapacity(const OBZone &zone)
{
   return IsLooseSweepZoneForCapacity(zone) || zone.is_htf_pullback;
}

int CountLooseSweepZones(const OBZone &zones[], int zone_count)
{
   int count = 0;
   for(int i = 0; i < zone_count; i++)
   {
      if(!zones[i].expired && IsLooseSweepZoneForCapacity(zones[i]))
         count++;
   }
   return count;
}

void RemoveZoneAt(OBZone &zones[], int &zone_count, int index)
{
   for(int i = index; i < zone_count - 1; i++)
      zones[i] = zones[i + 1];
   zone_count--;
}

void PruneLooseSweepsForPrimaryCapacity(OBZone &zones[], int &zone_count)
{
   while(zone_count >= MAX_OB_ZONES)
   {
      int remove_idx = -1;
      for(int i = 0; i < zone_count; i++)
      {
         if(IsSupplementalZoneForCapacity(zones[i]))
         {
            remove_idx = i;
            break;
         }
      }
      if(remove_idx < 0)
         return;
      RemoveZoneAt(zones, zone_count, remove_idx);
   }
}

void DetectLiquiditySweepWithParams(const MqlRates &rates[], int count, OBZone &zones[], int &zone_count,
                           const EAState &state, double atr, double spread,
                           int input_lookback, double max_range_atr,
                           double min_range_spread_mult, double min_penetration_atr,
                           double min_wick_pct, bool loose_sweep)
{
   if(!CfgEnableLiquiditySweep())
      return;
   if(!loose_sweep)
      PruneLooseSweepsForPrimaryCapacity(zones, zone_count);
   if(zone_count >= MAX_OB_ZONES)
      return;
   if(loose_sweep && InpLooseSweepMaxActiveZones > 0 &&
      CountLooseSweepZones(zones, zone_count) >= InpLooseSweepMaxActiveZones)
      return;

   int lookback = input_lookback;
   if(lookback < 3)
      lookback = 3;

   int sweep_idx = count - 2; // new bar 后，上一根K线已收盘
   int range_end = sweep_idx - 1;
   int range_start = range_end - lookback + 1;
   if(range_start < 0 || sweep_idx <= 0 || atr <= 0)
      return;

   MqlDateTime dt;
   TimeToStruct(rates[sweep_idx].time, dt);
   if(IsInNoOBWindow(dt.hour))
      return;

   double range_high = rates[range_start].high;
   double range_low = rates[range_start].low;
   for(int i = range_start + 1; i <= range_end; i++)
   {
      if(rates[i].high > range_high) range_high = rates[i].high;
      if(rates[i].low < range_low) range_low = rates[i].low;
   }

   double range_height = range_high - range_low;
   if(range_height <= 0)
      return;
   if(max_range_atr > 0 && range_height > atr * max_range_atr)
      return;
   if(min_range_spread_mult > 0 && spread > 0 &&
      range_height < spread * min_range_spread_mult)
      return;

   double extra = atr * MathMax(0.0, min_penetration_atr);
   double body_high = MathMax(rates[sweep_idx].open, rates[sweep_idx].close);
   double body_low = MathMin(rates[sweep_idx].open, rates[sweep_idx].close);
   double candle_range = rates[sweep_idx].high - rates[sweep_idx].low;
   if(candle_range <= 0)
      return;

   int direction = 0;
   double zone_high = 0.0;
   double zone_low = 0.0;
   double wick_pct = 0.0;

   bool swept_low = (rates[sweep_idx].low < range_low - extra && rates[sweep_idx].close > range_low);
   bool swept_high = (rates[sweep_idx].high > range_high + extra && rates[sweep_idx].close < range_high);

   if(swept_low)
   {
      double lower_wick = body_low - rates[sweep_idx].low;
      wick_pct = lower_wick / candle_range * 100.0;
      if(wick_pct < min_wick_pct)
         return;
      direction = OB_BUY;
      zone_high = range_low;
      zone_low = rates[sweep_idx].low;
   }
   else if(swept_high)
   {
      double upper_wick = rates[sweep_idx].high - body_high;
      wick_pct = upper_wick / candle_range * 100.0;
      if(wick_pct < min_wick_pct)
         return;
      direction = OB_SELL;
      zone_high = rates[sweep_idx].high;
      zone_low = range_high;
   }
   else
      return;

   if(zone_high <= zone_low)
      return;

   double sweep_height = zone_high - zone_low;
   if(spread > 0 && sweep_height < spread * InpMinOBSpreadMult)
      return;

   for(int z = 0; z < zone_count; z++)
   {
      if(zones[z].expired) continue;
      if(!zones[z].is_liquidity_sweep) continue;
      if(zones[z].direction != direction) continue;
      if(MathAbs(zones[z].high - zone_high) < atr * 0.2 &&
         MathAbs(zones[z].low - zone_low) < atr * 0.2)
         return;
   }

   OBZone zone = {};
   zone.high = zone_high;
   zone.low = zone_low;
   zone.mid = (zone.high + zone.low) / 2.0;
   zone.ob_top = zone.high;
   zone.ob_bottom = zone.low;
   zone.direction = direction;
   zone.created = rates[sweep_idx].time;
   zone.created_bar = state.bar_count;
   zone.touch_count = 0;
   zone.first_touch = 0;
   zone.last_touch = 0;
   zone.strength = MathMin(5.0, 1.0 + wick_pct / 25.0 + range_height / atr);
   zone.is_fresh = true;
   zone.is_continuation = false;
   zone.is_1h_aligned = false;
   zone.ds_weight = 1.0;
   zone.entry_count = 0;
   zone.last_entry_time = 0;
   zone.used = false;
   zone.expired = false;
   zone.is_range_breakout = false;
   zone.is_liquidity_sweep = true;
   zone.is_loose_sweep = loose_sweep;
   zone.range_height = range_height;

   zones[zone_count] = zone;
   zone_count++;
}

void DetectHTFPullbacks(OBZone &zones[], int &zone_count, const EAState &state, double spread)
{
   if(!InpEnableHTFPullback)
      return;
   if(zone_count >= MAX_OB_ZONES)
      return;

   int bars = MathMax(InpHTFPullbackBars, 1);
   ENUM_TIMEFRAMES tf = MinutesToTF(InpHTFPullbackTF);
   MqlRates htf[];
   int copied = CopyRates(Symbol(), tf, 1, bars + InpATRPeriod + 1, htf);
   if(copied < bars + InpATRPeriod + 1)
      return;

   double htf_atr = CalcATR(htf, copied, InpATRPeriod);
   if(htf_atr <= 0)
      return;

   int first = copied - bars;
   int last = copied - 1;
   double net = htf[last].close - htf[first].open;
   double net_atr = net / htf_atr;
   int direction = 0;
   if(net_atr >= InpHTFPullbackMinATR)
      direction = OB_BUY;
   else if(net_atr <= -InpHTFPullbackMinATR)
      direction = OB_SELL;
   else
      return;

   MqlDateTime dt;
   TimeToStruct(htf[last].time, dt);
   if(IsInNoOBWindow(dt.hour))
      return;

   double zone_height = htf_atr * InpHTFPullbackZoneATR;
   double offset = htf_atr * InpHTFPullbackOffsetATR;
   if(zone_height <= 0)
      return;
   if(spread > 0 && zone_height < spread * InpMinOBSpreadMult)
      return;

   double zone_high = 0.0;
   double zone_low = 0.0;
   if(direction == OB_BUY)
   {
      zone_high = htf[last].close - offset;
      zone_low = zone_high - zone_height;
   }
   else
   {
      zone_low = htf[last].close + offset;
      zone_high = zone_low + zone_height;
   }
   if(zone_high <= zone_low)
      return;

   for(int z = 0; z < zone_count; z++)
   {
      if(zones[z].expired) continue;
      if(!zones[z].is_htf_pullback) continue;
      if(zones[z].direction != direction) continue;
      if(MathAbs(zones[z].high - zone_high) < htf_atr * 0.2 &&
         MathAbs(zones[z].low - zone_low) < htf_atr * 0.2)
         return;
   }

   OBZone zone = {};
   zone.high = zone_high;
   zone.low = zone_low;
   zone.mid = (zone.high + zone.low) / 2.0;
   zone.ob_top = zone.high;
   zone.ob_bottom = zone.low;
   zone.direction = direction;
   zone.created = htf[last].time;
   zone.created_bar = state.bar_count;
   zone.touch_count = 0;
   zone.first_touch = 0;
   zone.last_touch = 0;
   zone.strength = MathMin(5.0, 1.0 + MathAbs(net_atr));
   zone.is_fresh = true;
   zone.is_continuation = true;
   zone.is_1h_aligned = false;
   zone.ds_weight = 1.0;
   zone.entry_count = 0;
   zone.last_entry_time = 0;
   zone.used = false;
   zone.expired = false;
   zone.is_range_breakout = false;
   zone.is_liquidity_sweep = false;
   zone.is_loose_sweep = false;
   zone.is_htf_pullback = true;
   zone.range_height = zone_height;

   zones[zone_count] = zone;
   zone_count++;
}

void DetectLiquiditySweeps(const MqlRates &rates[], int count, OBZone &zones[], int &zone_count,
                           const EAState &state, double atr, double spread)
{
   DetectLiquiditySweepWithParams(rates, count, zones, zone_count, state, atr, spread,
      CfgSweepLookbackBars(), CfgSweepMaxRangeATR(), CfgSweepMinRangeSpreadMult(),
      CfgSweepMinPenetrationATR(), CfgSweepMinWickPct(), false);

   if(!InpEnableLooseSweep)
      return;

   DetectLiquiditySweepWithParams(rates, count, zones, zone_count, state, atr, spread,
      InpLooseSweepLookbackBars, InpLooseSweepMaxRangeATR, InpLooseSweepMinRangeSpreadMult,
      InpLooseSweepMinPenetrationATR, InpLooseSweepMinWickPct, true);
}

void DetectOrderBlocks(const MqlRates &rates[], int count, OBZone &zones[], int &zone_count, const EAState &state)
{
   CompactZones(zones, zone_count);

   double atr = state.atr_value;
   if(atr <= 0) atr = CalcATR(rates, count, InpATRPeriod);
   if(atr <= 0) return;

   string symbol = Symbol();
   double spread = GetSpread(symbol);
   if(InpSpreadFloor > 0 && spread < InpSpreadFloor)
      spread = InpSpreadFloor;
   double min_ob_range = spread * InpMinOBSpreadMult;

   DetectRangeBreakouts(rates, count, zones, zone_count, state, atr, spread);
   if(InpHTFPullbackOnly)
   {
      DetectHTFPullbacks(zones, zone_count, state, spread);
      return;
   }
   DetectLiquiditySweeps(rates, count, zones, zone_count, state, atr, spread);
   if(CfgLiquiditySweepOnly())
      return;
   if(InpRangeBreakoutOnly)
      return;

   int scan_start = count - (InpImpulseLookback + 1);
   int scan_end = 1;
   if(InpOBScanDepth > 0 && count > InpOBScanDepth + 4)
      scan_end = count - 4 - InpOBScanDepth;

   for(int i = scan_start; i >= scan_end; i--)
   {
      if(zone_count >= MAX_OB_ZONES) break;

      // Bullish OB: bearish candle followed by up impulse
      if(rates[i].close < rates[i].open)
      {
         if(i + InpImpulseLookback < count && IsImpulse(rates, count, i + 1, OB_BUY, atr))
         {
            if(!PassImpulseQuality(rates, i + 1))
               continue;
            if(!PassStrictStructureBreak(rates, count, i, i + 1, OB_BUY, atr))
               continue;

            double ob_range = MathAbs(rates[i].open - rates[i].close);  // Gap1: 实体大小
            if(ob_range < min_ob_range) continue;

            double impulse_high = rates[i + 1].high;
            for(int k = i + 1; k <= i + InpImpulseLookback && k < count; k++)
               if(rates[k].high > impulse_high) impulse_high = rates[k].high;

            double bounce = (impulse_high - rates[i].high) / ob_range;
            if(bounce < CfgBouncePct()) continue;

            bool duplicate = false;
            for(int z = 0; z < zone_count; z++)
            {
               if(zones[z].expired) continue;
               if(zones[z].is_htf_pullback) continue;
               if(zones[z].direction == OB_BUY &&
                  MathAbs(zones[z].high - rates[i].open) < atr * 0.1 &&
                  MathAbs(zones[z].low - rates[i].close) < atr * 0.1)
               {
                  duplicate = true;
                  break;
               }
            }
            if(duplicate) continue;

            // Gap2: Displacement确认 — impulse bar close必须突破前3根最高点
            double prior_high = rates[i].high;
            for(int p = MathMax(0, i-3); p < i; p++)
               if(rates[p].high > prior_high) prior_high = rates[p].high;
            if(rates[i+1].close <= prior_high)
               continue;

            // Gap3: K线质量 — 实体占比达标
            if(!PassOBBodyPct(rates[i]))
               continue;

            // Gap4: 高噪音时段过滤
            MqlDateTime dt_bull;
            TimeToStruct(rates[i].time, dt_bull);
            if(IsInNoOBWindow(dt_bull.hour))
               continue;

            OBZone zone = {};
            zone.high = rates[i].open;   // Gap1: bearish candle的open是实体高点
            zone.low = rates[i].close;   // Gap1: bearish candle的close是实体低点（区间匹配用）
            zone.ob_bottom = rates[i].low; // 引线低点（SL锚点）：含下引线的真实支撑位
            zone.mid = (zone.high + zone.low) / 2.0;
            zone.direction = OB_BUY;
            zone.created = rates[i].time;
            zone.created_bar = state.bar_count - (count - 1 - i);
            zone.touch_count = 0;
            zone.first_touch = 0;
            zone.last_touch = 0;
            zone.strength = CalcOBStrength(rates, i, MathMin(i + InpImpulseLookback, count - 1), atr, OB_BUY);
            zone.is_fresh = true;
            zone.is_continuation = DetectContinuation(rates, count, i, zone.direction);
            zone.is_1h_aligned = false;
            zone.ds_weight = InpDSWeight ? CalcDSWeight(rates, count, i) : 1.0;
            zone.entry_count = 0;
            zone.last_entry_time = 0;
            zone.used = false;
            zone.expired = false;

            zones[zone_count] = zone;
            zone_count++;
         }
      }

      // Bearish OB: bullish candle followed by down impulse
      if(rates[i].close > rates[i].open)
      {
         if(i + InpImpulseLookback < count && IsImpulse(rates, count, i + 1, OB_SELL, atr))
         {
            if(!PassImpulseQuality(rates, i + 1))
               continue;
            if(!PassStrictStructureBreak(rates, count, i, i + 1, OB_SELL, atr))
               continue;

            double ob_range = MathAbs(rates[i].open - rates[i].close);  // Gap1: 实体大小
            if(ob_range < min_ob_range) continue;

            double impulse_low = rates[i + 1].low;
            for(int k = i + 1; k <= i + InpImpulseLookback && k < count; k++)
               if(rates[k].low < impulse_low) impulse_low = rates[k].low;

            double bounce = (rates[i].low - impulse_low) / ob_range;
            if(bounce < CfgBouncePct()) continue;

            bool duplicate = false;
            for(int z = 0; z < zone_count; z++)
            {
               if(zones[z].expired) continue;
               if(zones[z].is_htf_pullback) continue;
               if(zones[z].direction == OB_SELL &&
                  MathAbs(zones[z].high - rates[i].close) < atr * 0.1 &&
                  MathAbs(zones[z].low - rates[i].open) < atr * 0.1)
               {
                  duplicate = true;
                  break;
               }
            }
            if(duplicate) continue;

            // Gap2: Displacement确认 — impulse bar close必须突破前3根最低点
            double prior_low = rates[i].low;
            for(int p = MathMax(0, i-3); p < i; p++)
               if(rates[p].low < prior_low) prior_low = rates[p].low;
            if(rates[i+1].close >= prior_low)
               continue;

            // Gap3: K线质量 — 实体占比达标
            if(!PassOBBodyPct(rates[i]))
               continue;

            // Gap4: 高噪音时段过滤
            MqlDateTime dt_bear;
            TimeToStruct(rates[i].time, dt_bear);
            if(IsInNoOBWindow(dt_bear.hour))
               continue;

            OBZone zone = {};
            zone.high = rates[i].close;  // Gap1: bullish candle的close是实体高点（区间匹配用）
            zone.low = rates[i].open;    // Gap1: bullish candle的open是实体低点
            zone.ob_top = rates[i].high; // 引线高点（SL锚点）：含上引线的真实阻力位
            zone.mid = (zone.high + zone.low) / 2.0;
            zone.direction = OB_SELL;
            zone.created = rates[i].time;
            zone.created_bar = state.bar_count - (count - 1 - i);
            zone.touch_count = 0;
            zone.first_touch = 0;
            zone.last_touch = 0;
            zone.strength = CalcOBStrength(rates, i, MathMin(i + InpImpulseLookback, count - 1), atr, OB_SELL);
            zone.is_fresh = true;
            zone.is_continuation = DetectContinuation(rates, count, i, zone.direction);
            zone.is_1h_aligned = false;
            zone.ds_weight = InpDSWeight ? CalcDSWeight(rates, count, i) : 1.0;
            zone.entry_count = 0;
            zone.last_entry_time = 0;
            zone.used = false;
            zone.expired = false;

            zones[zone_count] = zone;
            zone_count++;
         }
      }
   }

   // Non-HTFPullbackOnly mode uses an independent HTFPB lane in the EA,
   // so supplemental zones cannot alter the primary OB/sweep path.
}

#endif
