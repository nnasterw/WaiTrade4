#ifndef __WAITRADE_SCORE_ENGINE_MQH__
#define __WAITRADE_SCORE_ENGINE_MQH__

#include "Config.mqh"
#include "Types.mqh"
#include "MarketState.mqh"

double ScoreToMultiplier(int score)
{
    if(score <= 1) return -1.0;
    if(score == 2) return 0.5;
    if(score == 3) return 1.0;
    if(score == 4) return 1.5;
    return 2.0; // 5-6
}

int CalcSignalScore(const OBZone &zone, const EAState &state, int mkt_state,
                    double proximity_distance, double risk_distance, double target_distance)
{
    int score = 0;

    // 1. 动能强: zone.strength > 1.5
    if(zone.strength > 1.5)
        score++;

    // 2. 行情初期: touch_count <= 1 (fresh)
    if(zone.touch_count <= 1)
        score++;

    // 3. 空间足够: target_distance / risk_distance >= 1.5
    if(risk_distance > 0 && target_distance / risk_distance >= 1.5)
        score++;

    // 4. 多周期共振: market_state == zone.direction
    if(mkt_state == zone.direction)
        score++;

    // 5. 关键位接近: proximity_distance < CfgProximityATR() * ATR(M15)
    if(state.atr_m15 > 0 && proximity_distance < CfgProximityATR() * state.atr_m15)
        score++;

    // 6. 二次确认: touch_count >= 2
    if(zone.touch_count >= 2)
        score++;

    return score;
}

#endif // __WAITRADE_SCORE_ENGINE_MQH__
