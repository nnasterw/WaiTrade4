#ifndef __WAITRADE_DECAY_DETECTOR_MQH__
#define __WAITRADE_DECAY_DETECTOR_MQH__

#include "Config.mqh"
#include "Types.mqh"
#include "MathUtils.mqh"

bool CheckMomentumDecay(string symbol, int direction, const MqlRates &rates[], int count)
{
    int decay_bars = CfgDecayBars();
    int need = decay_bars + 2;
    if(count < need)
        return false;

    // 条件1: 二推不破
    bool cond1 = false;
    {
        int start = count - decay_bars;
        if(direction > 0)
        {
            double ref_high = rates[start - 1].high;
            bool no_new_high = true;
            for(int i = start; i < count; i++)
            {
                if(rates[i].high > ref_high)
                { no_new_high = false; break; }
            }
            if(no_new_high && decay_bars >= 3)
            {
                int a = count - 3, b = count - 2, c = count - 1;
                if(rates[c].high < rates[b].high && rates[b].high < rates[a].high &&
                   rates[c].low  < rates[b].low  && rates[b].low  < rates[a].low)
                    cond1 = true;
            }
        }
        else
        {
            double ref_low = rates[start - 1].low;
            bool no_new_low = true;
            for(int i = start; i < count; i++)
            {
                if(rates[i].low < ref_low)
                { no_new_low = false; break; }
            }
            if(no_new_low && decay_bars >= 3)
            {
                int a = count - 3, b = count - 2, c = count - 1;
                if(rates[c].high > rates[b].high && rates[b].high > rates[a].high &&
                   rates[c].low  > rates[b].low  && rates[b].low  > rates[a].low)
                    cond1 = true;
            }
        }
    }

    // 条件2: 吞没 + 追随
    bool cond2 = false;
    if(count >= 3)
    {
        int e = count - 2; // 吞没bar
        int f = count - 1; // 追随bar
        int p = count - 3; // 吞没前一根

        if(direction > 0)
        {
            bool engulf = (rates[e].close < rates[p].open);
            double f_body = MathAbs(rates[f].close - rates[f].open);
            double f_range = rates[f].high - rates[f].low;
            bool follow = (rates[f].close < rates[f].open) &&
                          (f_range > 0 && f_body / f_range * 100.0 >= InpEngulfBodyPct);
            if(engulf && follow)
                cond2 = true;
        }
        else
        {
            bool engulf = (rates[e].close > rates[p].open);
            double f_body = MathAbs(rates[f].close - rates[f].open);
            double f_range = rates[f].high - rates[f].low;
            bool follow = (rates[f].close > rates[f].open) &&
                          (f_range > 0 && f_body / f_range * 100.0 >= InpEngulfBodyPct);
            if(engulf && follow)
                cond2 = true;
        }
    }

    return (cond1 || cond2);
}

double CandleBody(const MqlRates &bar)
{
    return MathAbs(bar.close - bar.open);
}

double CandleRange(const MqlRates &bar)
{
    return MathMax(bar.high - bar.low, _Point);
}

bool IsTrendBody(const MqlRates &bar, int direction)
{
    if(direction > 0)
        return bar.close > bar.open;
    return bar.close < bar.open;
}

bool IsWeakReverseBody(const MqlRates &bar, int direction, double max_body_pct)
{
    double body_pct = CandleBody(bar) / CandleRange(bar) * 100.0;
    if(body_pct > max_body_pct)
        return false;
    if(direction > 0)
        return bar.close < bar.open;
    return bar.close > bar.open;
}

bool CheckStrongMomentum(string symbol, int direction, const MqlRates &rates[], int count)
{
    if(count < InpStrongMomentumBars)
        return false;

    int start = count - InpStrongMomentumBars;
    int reverse_count = 0;
    double first_body = CandleBody(rates[start]);
    double last_body = CandleBody(rates[count - 1]);
    double progress = 0;
    double pullback = 0;

    for(int i = start; i < count; i++)
    {
        if(IsTrendBody(rates[i], direction))
            continue;
        if(IsWeakReverseBody(rates[i], direction, InpStrongWeakReverseBodyPct))
            reverse_count++;
        else
            return false;
    }

    if(reverse_count > 1)
        return false;

    if(direction > 0)
    {
        progress = rates[count - 1].close - rates[start].open;
        double highest = rates[start].high;
        for(int i = start; i < count; i++)
            highest = MathMax(highest, rates[i].high);
        pullback = highest - rates[count - 1].low;
    }
    else
    {
        progress = rates[start].open - rates[count - 1].close;
        double lowest = rates[start].low;
        for(int i = start; i < count; i++)
            lowest = MathMin(lowest, rates[i].low);
        pullback = rates[count - 1].high - lowest;
    }

    if(progress <= 0)
        return false;
    if(InpStrongMinBodyGrowth > 0 && first_body > 0 && last_body / first_body < InpStrongMinBodyGrowth)
        return false;
    if(InpStrongMaxPullbackPct > 0 && pullback / progress * 100.0 > InpStrongMaxPullbackPct)
        return false;

    return true;
}

bool CheckMomentumWeakness(string symbol, int direction, const MqlRates &rates[], int count)
{
    if(count < 4)
        return false;

    int a = count - 3, b = count - 2, c = count - 1;
    double body_a = CandleBody(rates[a]);
    double body_b = CandleBody(rates[b]);
    double body_c = CandleBody(rates[c]);

    if(InpWeakBodyShrinkPct > 0 &&
       body_a > 0 && body_b > 0 &&
       body_b <= body_a * InpWeakBodyShrinkPct &&
       body_c <= body_b * InpWeakBodyShrinkPct)
        return true;

    if(direction > 0)
    {
        double upper = rates[c].high - MathMax(rates[c].open, rates[c].close);
        if(InpWeakWickBodyRatio > 0 && body_c > 0 && upper / body_c >= InpWeakWickBodyRatio)
            return true;
        if(rates[c].high > rates[b].high && rates[c].close <= rates[b].high)
            return true;
        if(rates[c].close < rates[c].open && IsTrendBody(rates[b], direction))
            return true;
    }
    else
    {
        double lower = MathMin(rates[c].open, rates[c].close) - rates[c].low;
        if(InpWeakWickBodyRatio > 0 && body_c > 0 && lower / body_c >= InpWeakWickBodyRatio)
            return true;
        if(rates[c].low < rates[b].low && rates[c].close >= rates[b].low)
            return true;
        if(rates[c].close > rates[c].open && IsTrendBody(rates[b], direction))
            return true;
    }

    return false;
}

#endif // __WAITRADE_DECAY_DETECTOR_MQH__
