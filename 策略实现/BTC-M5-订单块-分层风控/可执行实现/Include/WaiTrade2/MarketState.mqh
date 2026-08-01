#ifndef __WAITRADE_MARKET_STATE_MQH__
#define __WAITRADE_MARKET_STATE_MQH__

#include "Config.mqh"
#include "Types.mqh"
#include "MathUtils.mqh"

enum MARKET_STATE { STATE_BULLISH=1, STATE_BEARISH=-1, STATE_RANGE=0 };

struct SwingPoint {
    double price;
    int    bar_index;
    int    type; // 1=high, -1=low
};

bool IsSwingHigh(const MqlRates &rates[], int idx, int strength, int total)
{
    if(idx - strength < 0 || idx + strength >= total)
        return false;
    double hi = rates[idx].high;
    for(int j = 1; j <= strength; j++)
    {
        if(rates[idx - j].high >= hi) return false;
        if(rates[idx + j].high >= hi) return false;
    }
    return true;
}

bool IsSwingLow(const MqlRates &rates[], int idx, int strength, int total)
{
    if(idx - strength < 0 || idx + strength >= total)
        return false;
    double lo = rates[idx].low;
    for(int j = 1; j <= strength; j++)
    {
        if(rates[idx - j].low <= lo) return false;
        if(rates[idx + j].low <= lo) return false;
    }
    return true;
}

MARKET_STATE DetectMarketState(string symbol, double &target_price)
{
    MqlRates rates[];
    int swing_strength = CfgSwingStrength();
    int count = CopyRates(symbol, PERIOD_M15, 0, CfgTrendLookback(), rates);
    if(count < swing_strength * 2 + 5)
        return STATE_RANGE;

    SwingPoint highs[];
    SwingPoint lows[];
    ArrayResize(highs, 32);
    ArrayResize(lows, 32);
    int nh = 0, nl = 0;

    for(int i = swing_strength; i < count - swing_strength; i++)
    {
        if(IsSwingHigh(rates, i, swing_strength, count))
        {
            if(nh >= ArraySize(highs)) ArrayResize(highs, nh * 2);
            highs[nh].price     = rates[i].high;
            highs[nh].bar_index = i;
            highs[nh].type      = 1;
            nh++;
        }
        if(IsSwingLow(rates, i, swing_strength, count))
        {
            if(nl >= ArraySize(lows)) ArrayResize(lows, nl * 2);
            lows[nl].price     = rates[i].low;
            lows[nl].bar_index = i;
            lows[nl].type      = -1;
            nl++;
        }
    }

    if(nh < 2 || nl < 2)
    {
        target_price = 0;
        return STATE_RANGE;
    }

    double sh1 = highs[nh - 1].price;
    double sh2 = highs[nh - 2].price;
    double sl1 = lows[nl - 1].price;
    double sl2 = lows[nl - 2].price;

    bool hh = (sh1 > sh2);
    bool hl = (sl1 > sl2);
    bool lh = (sh1 < sh2);
    bool ll = (sl1 < sl2);

    MARKET_STATE state = STATE_RANGE;
    if(hh && hl) state = STATE_BULLISH;
    if(lh && ll) state = STATE_BEARISH;

    if(state == STATE_RANGE)
    {
        target_price = (sh1 > sl1) ? sh1 : sl1;
        double alt   = (sh1 > sl1) ? sl1 : sh1;
        if(MathAbs(target_price) < MathAbs(alt))
            target_price = alt;
    }
    else if(state == STATE_BULLISH)
    {
        target_price = sh1;
    }
    else
    {
        target_price = sl1;
    }

    return state;
}

bool FindRecentSwingTarget(string symbol, ENUM_TIMEFRAMES tf, int direction, double entry,
                           double &target_price)
{
    target_price = 0;

    int lookback = MathMax(InpHTFTargetLookback, InpHTFSwingStrength * 2 + 10);
    MqlRates rates[];
    int count = CopyRates(symbol, tf, 0, lookback, rates);
    if(count < InpHTFSwingStrength * 2 + 5)
        return false;

    for(int i = count - InpHTFSwingStrength - 2; i >= InpHTFSwingStrength; i--)
    {
        if(direction == OB_BUY && IsSwingHigh(rates, i, InpHTFSwingStrength, count))
        {
            if(rates[i].high > entry)
            {
                target_price = rates[i].high;
                return true;
            }
        }
        else if(direction == OB_SELL && IsSwingLow(rates, i, InpHTFSwingStrength, count))
        {
            if(rates[i].low < entry)
            {
                target_price = rates[i].low;
                return true;
            }
        }
    }

    return false;
}

bool CalcHTFTargetPrice(string symbol, int direction, double entry, double risk_price,
                        double &target_price)
{
    target_price = 0;
    if(!InpEnableHTFTarget || risk_price <= 0)
        return false;

    ENUM_TIMEFRAMES tf = MinutesToTF(InpHTFTargetTF);
    double htf_target = 0;
    MARKET_STATE htf_state = DetectMarketState(symbol, htf_target);
    if(InpHTFRequireAligned && htf_state != direction)
        return false;

    bool found = FindRecentSwingTarget(symbol, tf, direction, entry, target_price);
    if(!found || PriceToR(target_price, entry, risk_price, direction) < InpHTFMinTargetR)
    {
        if(InpHTFMeasuredMoveR <= 0)
            return false;
        target_price = RToPrice(InpHTFMeasuredMoveR, entry, risk_price, direction);
    }

    double target_r = PriceToR(target_price, entry, risk_price, direction);
    if(target_r < InpHTFMinTargetR)
        return false;

    if(InpHTFMaxTargetR > 0 && target_r > InpHTFMaxTargetR)
        target_price = RToPrice(InpHTFMaxTargetR, entry, risk_price, direction);

    return true;
}

#endif // __WAITRADE_MARKET_STATE_MQH__
