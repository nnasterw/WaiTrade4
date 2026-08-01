#ifndef __WAITRADE_POSITION_MANAGER_MQH__
#define __WAITRADE_POSITION_MANAGER_MQH__

#include "Types.mqh"
#include "Config.mqh"
#include "Utils.mqh"
#include "MarketState.mqh"
#include "DecayDetector.mqh"

void RegisterPosition(ulong ticket, int direction, double entry, double sl, double risk_price,
                      bool deep_entry,
                      bool htf_target, double htf_partial_r, int htf_partial_pct,
                      bool failure_reverse,
                      PosTrack &tracks[], int &track_count);
bool IsPositionStrong(const PosTrack &track, const EAState &state);
bool PassMonthlyEntryGuard();
bool CheckMonthlyLossStop(bool lock_stop);
bool CheckMonthlyProfitLockStop(bool lock_stop);
void MarkCloseAttemptFailed(PosTrack &track);

bool CloseAllForMonthlyReason(PosTrack &tracks[], int &track_count, const string reason)
{
    bool closed_any = false;
    for(int i = track_count - 1; i >= 0; i--)
    {
        if(tracks[i].ticket == 0) continue;
        if(!PositionSelectByTicket(tracks[i].ticket))
            continue;

        if(ClosePosition(tracks[i].ticket, reason))
            closed_any = true;
        else
            MarkCloseAttemptFailed(tracks[i]);
    }
    return closed_any;
}

bool CloseAllForMonthlyStop(PosTrack &tracks[], int &track_count)
{
    return CloseAllForMonthlyReason(tracks, track_count, "monthly_stop");
}

bool OpenStrongAddOn(PosTrack &track, const EAState &state,
                     PosTrack &tracks[], int &track_count)
{
    if(!InpEnableStrongAddOn) return false;
    if(!PassMonthlyEntryGuard()) return false;
    if(InpStrongAddOnMaxCount <= 0) return false;
    if(track.failure_reverse || track.strong_addon) return false;
    if(track.addon_count >= InpStrongAddOnMaxCount) return false;
    if(track_count >= MAX_POSITIONS) return false;
    if(CountPositions() >= CfgMaxConcurrent()) return false;
    if(!PositionSelectByTicket(track.ticket)) return false;
    if(!IsPositionStrong(track, state)) return false;

    double current_price = PositionGetDouble(POSITION_PRICE_CURRENT);
    double current_r = PriceToR(current_price, track.entry_price, track.risk_price, track.direction);
    double trigger_r = InpStrongAddOnTriggerR + track.addon_count * InpStrongAddOnStepR;
    if(current_r < trigger_r)
        return false;

    string symbol = _Symbol;
    double spread = GetSpread(symbol);
    double risk = track.risk_price * MathMax(InpStrongAddOnRiskMult, 0.1);
    if(risk <= 0)
        return false;
    if(spread > 0 && risk / spread < InpStrongAddOnMinSpreadRatio)
        return false;

    double source_volume = PositionGetDouble(POSITION_VOLUME);
    double lot = source_volume * MathMax(InpStrongAddOnLotMult, 0.1);
    double lot_step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
    double lot_min = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
    double lot_max = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
    if(lot_step <= 0)
        return false;
    lot = MathFloor(lot / lot_step) * lot_step;
    if(lot < lot_min)
        return false;
    if(CfgMaxLotSize() > 0 && lot > CfgMaxLotSize())
        lot = CfgMaxLotSize();
    if(lot > lot_max)
        lot = lot_max;

    double order_price = (track.direction > 0) ? SymbolInfoDouble(symbol, SYMBOL_ASK)
                                               : SymbolInfoDouble(symbol, SYMBOL_BID);
    double sl = (track.direction > 0) ? order_price - risk : order_price + risk;
    double current_sl = PositionGetDouble(POSITION_SL);
    double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
    if(current_sl > 0)
    {
        if(track.direction > 0 && current_sl > sl && current_sl < order_price - point)
            sl = current_sl;
        else if(track.direction < 0 && current_sl < sl && current_sl > order_price + point)
            sl = current_sl;
    }
    risk = MathAbs(order_price - sl);
    if(risk <= 0)
        return false;

    MqlTradeRequest request = {};
    MqlTradeResult result = {};
    request.action = TRADE_ACTION_DEAL;
    request.symbol = symbol;
    request.volume = lot;
    request.type = (track.direction > 0) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
    request.price = order_price;
    request.sl = BrokerStopFromVirtualSL(sl, order_price, risk, track.direction);
    request.tp = 0.0;
    request.magic = InpMagicNumber;
    request.comment = "WT " + InpVersion + " ADD";
    request.deviation = 20;
    request.type_filling = ORDER_FILLING_IOC;
    request.type_time = ORDER_TIME_GTC;

    if(!OrderSend(request, result))
        return false;
    if(result.retcode != TRADE_RETCODE_DONE)
        return false;

    double fill_price = result.price > 0 ? result.price : order_price;
    RegisterPosition(result.order, track.direction, fill_price, sl, risk,
                     track.deep_entry, track.htf_target, track.htf_partial_r, track.htf_partial_pct,
                     false, tracks, track_count);
    if(track_count > 0)
    {
        tracks[track_count - 1].open_bar = state.bar_count;
        tracks[track_count - 1].strong_addon = true;
    }
    track.addon_count++;
    Print("寮哄娍寤剁画鍔犱粨: source=", track.ticket,
          " addon=", result.order,
          " r=", DoubleToString(current_r, 2),
          " lot=", DoubleToString(lot, 2));
    return true;
}

bool OpenFailureReverse(const PosTrack &track, const string reason,
                        double source_volume, int open_bar,
                        PosTrack &tracks[], int &track_count)
{
    if(!InpEnableFailureReverse) return false;
    if(!PassMonthlyEntryGuard()) return false;
    if(track.failure_reverse && !InpFailureReverseAllowChain) return false;
    if(reason == "early_loss" && !InpReverseOnEarlyLoss) return false;
    if(reason == "mfe_fail" && !InpReverseOnMFEFail) return false;
    if(reason == "no_mfe" && !InpReverseOnNoMFE) return false;
    if(track_count >= MAX_POSITIONS) return false;
    if(CountPositions() >= CfgMaxConcurrent()) return false;

    string symbol = _Symbol;
    int rev_dir = -track.direction;
    double risk = track.risk_price * MathMax(InpFailureReverseRiskMult, 0.1);
    if(risk <= 0) return false;

    double lot = source_volume * MathMax(InpFailureReverseLotMult, 0.1);
    double lot_step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
    double lot_min = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
    double lot_max = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
    if(lot_step <= 0) return false;
    lot = MathFloor(lot / lot_step) * lot_step;
    if(lot < lot_min) return false;
    if(CfgMaxLotSize() > 0 && lot > CfgMaxLotSize())
        lot = CfgMaxLotSize();
    if(lot > lot_max) lot = lot_max;

    double order_price = (rev_dir > 0) ? SymbolInfoDouble(symbol, SYMBOL_ASK)
                                      : SymbolInfoDouble(symbol, SYMBOL_BID);
    double sl = (rev_dir > 0) ? order_price - risk : order_price + risk;
    double tp = 0.0;
    if(InpFailureReverseTPR > 0)
        tp = RToPrice(InpFailureReverseTPR, order_price, risk, rev_dir);
    else if(CfgDTPTriggerR() <= 0 && CfgFixedTPR() > 0)
        tp = RToPrice(CfgFixedTPR(), order_price, risk, rev_dir);

    MqlTradeRequest request = {};
    MqlTradeResult result = {};
    request.action = TRADE_ACTION_DEAL;
    request.symbol = symbol;
    request.volume = lot;
    request.type = (rev_dir > 0) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
    request.price = order_price;
    request.sl = BrokerStopFromVirtualSL(sl, order_price, risk, rev_dir);
    request.tp = tp;
    request.magic = InpMagicNumber;
    request.comment = "WT " + InpVersion + " REV " + reason;
    request.deviation = 20;
    request.type_filling = ORDER_FILLING_IOC;
    request.type_time = ORDER_TIME_GTC;

    if(!OrderSend(request, result))
        return false;
    if(result.retcode != TRADE_RETCODE_DONE)
        return false;

    double fill_price = result.price > 0 ? result.price : order_price;
    RegisterPosition(result.order, rev_dir, fill_price, sl, risk,
                     false, false, 0, 0, true, tracks, track_count);
    if(track_count > 0)
        tracks[track_count - 1].open_bar = open_bar;
    return true;
}

double CurrentR(const PosTrack &track)
{
    if(!PositionSelectByTicket(track.ticket)) return 0;
    double current_price = PositionGetDouble(POSITION_PRICE_CURRENT);
    return PriceToR(current_price, track.entry_price, track.risk_price, track.direction);
}

bool IsSLImprovement(const PosTrack &track, double new_sl)
{
    if(!PositionSelectByTicket(track.ticket)) return false;
    double current_sl = PositionGetDouble(POSITION_SL);
    double base_sl = UseVirtualSLMode() && track.virtual_sl > 0 ? track.virtual_sl : current_sl;
    if(base_sl <= 0)
        base_sl = track.sl_initial;
    return (track.direction > 0) ? (new_sl > base_sl) : (new_sl < base_sl);
}

bool ApplyProtectiveSL(PosTrack &track, double new_sl, const string reason, double current_r)
{
    if(!PositionSelectByTicket(track.ticket)) return false;
    if(!IsSLImprovement(track, new_sl)) return true;

    if(UseVirtualSLMode())
    {
        double broker_sl = BrokerStopFromVirtualSL(new_sl, track.entry_price, track.risk_price, track.direction);
        if(!ModifySL(track.ticket, broker_sl))
            return false;
        track.virtual_sl = new_sl;
        track.virtual_sl_reason = reason;
        track.last_sl_reason = reason + "_virtual";
        PrintSLDebug(track.last_sl_reason, track, current_r, new_sl);
        return true;
    }

    if(!ModifySL(track.ticket, new_sl))
        return false;
    track.last_sl_reason = reason;
    PrintSLDebug(reason, track, current_r, new_sl);
    return true;
}

bool CheckVirtualSL(PosTrack &track, const EAState &state)
{
    if(!UseVirtualSLMode()) return false;
    if(track.virtual_sl <= 0) return false;
    if(state.bar_count <= track.open_bar) return false;
    if(!PositionSelectByTicket(track.ticket)) return false;

    int bars_needed = CfgVirtualSLConfirmBars();
    if(bars_needed <= 0) return false;
    int tf_min = CfgVirtualSLConfirmTF() > 0 ? CfgVirtualSLConfirmTF() : CfgBarTF();
    ENUM_TIMEFRAMES tf = MinutesToTF(tf_min);
    MqlRates rates[];
    int count = CopyRates(_Symbol, tf, 1, bars_needed, rates);
    if(count < bars_needed)
        return false;

    double buffer = state.atr_value * CfgVirtualSLCloseBufferATR();
    for(int i = 0; i < bars_needed; i++)
    {
        if(track.direction > 0)
        {
            if(rates[i].close > track.virtual_sl - buffer)
                return false;
        }
        else
        {
            if(rates[i].close < track.virtual_sl + buffer)
                return false;
        }
    }

    double current_r = CurrentR(track);
    PrintExitDebug("virtual_sl", track, current_r, state);
    if(ClosePosition(track.ticket, "virtual_sl"))
        return true;
    MarkCloseAttemptFailed(track);
    return false;
}

void PrintExitDebug(string reason, const PosTrack &track, double current_r, const EAState &state)
{
    if(!InpEnableExitDebug) return;
    double peak_r = MathMax(track.peak_profit_r, track.dtp_peak_r);
    double giveback_r = peak_r - current_r;
    Print("EXIT_DIAG reason=", reason,
          " ticket=", track.ticket,
          " dir=", track.direction,
          " entry=", DoubleToString(track.entry_price, _Digits),
          " current_r=", DoubleToString(current_r, 2),
          " peak_r=", DoubleToString(peak_r, 2),
          " dtp_peak_r=", DoubleToString(track.dtp_peak_r, 2),
          " giveback_r=", DoubleToString(giveback_r, 2),
          " bars_held=", state.bar_count - track.open_bar,
          " last_sl=", track.last_sl_reason);
}

void PrintSLDebug(string reason, const PosTrack &track, double current_r, double new_sl)
{
    if(!InpEnableExitDebug) return;
    Print("SL_DIAG reason=", reason,
          " ticket=", track.ticket,
          " current_r=", DoubleToString(current_r, 2),
          " peak_r=", DoubleToString(track.peak_profit_r, 2),
          " new_sl=", DoubleToString(new_sl, _Digits));
}

void PrintPositionGoneDebug(const PosTrack &track)
{
    if(!InpEnableExitDebug) return;
    double peak_r = MathMax(track.peak_profit_r, track.dtp_peak_r);
    Print("POSITION_GONE_DIAG",
          " ticket=", track.ticket,
          " dir=", track.direction,
          " entry=", DoubleToString(track.entry_price, _Digits),
          " sl_initial=", DoubleToString(track.sl_initial, _Digits),
          " peak_r=", DoubleToString(peak_r, 2),
          " raw_peak_r=", DoubleToString(track.peak_profit_r, 2),
          " dtp_peak_r=", DoubleToString(track.dtp_peak_r, 2),
          " open_bar=", track.open_bar,
          " last_sl=", track.last_sl_reason,
          " be=", track.be_applied,
          " trail=", track.trail_level,
          " partial=", track.partial_closed,
          " dtp_partial=", track.dtp_partial_closed,
          " deep=", track.deep_entry,
          " htf=", track.htf_target,
          " rev=", track.failure_reverse,
          " addon=", track.strong_addon);
}

bool ShouldSkipCloseAttempt(PosTrack &track)
{
    if(CfgCloseRetryCooldownSec() <= 0)
        return false;

    datetime now = TimeCurrent();
    return (track.last_close_attempt > 0 &&
            now - track.last_close_attempt < CfgCloseRetryCooldownSec());
}

void MarkCloseAttemptFailed(PosTrack &track)
{
    if(CfgCloseRetryCooldownSec() <= 0)
        return;
    datetime now = TimeCurrent();
    track.last_close_attempt = now;
}

void ManagePositions(PosTrack &tracks[], int &track_count, const EAState &state)
{
    if(CheckMonthlyLossStop(true))
    {
        CloseAllForMonthlyStop(tracks, track_count);
        return;
    }
    if(CheckMonthlyProfitLockStop(true))
    {
        CloseAllForMonthlyReason(tracks, track_count, "monthly_profit_lock");
        return;
    }

    for(int i = track_count - 1; i >= 0; i--)
    {
        if(tracks[i].ticket == 0) continue;

        if(!PositionSelectByTicket(tracks[i].ticket))
        {
            PrintPositionGoneDebug(tracks[i]);
            for(int j = i; j < track_count - 1; j++)
                tracks[j] = tracks[j + 1];
            track_count--;
            continue;
        }

        if(CheckVirtualSL(tracks[i], state))
            continue;

        CheckEarlyLossCut(tracks[i], state, tracks, track_count);
        CheckMFEFailExit(tracks[i], state, tracks, track_count);
        CheckNoMFEExit(tracks[i], state, tracks, track_count);
        CheckPartialClose(tracks[i], state);
        CheckBreakeven(tracks[i], state);
        OpenStrongAddOn(tracks[i], state, tracks, track_count);
        if(!(tracks[i].htf_target && InpHTFSkipTrail))
            CheckTrailing(tracks[i]);
        if(!(tracks[i].htf_target && InpHTFSkipDTP))
            CheckDTP(tracks[i], state);
        CheckTimeExit(tracks[i], state);
        CheckDecay(tracks[i], state);
    }
}

void SyncPositions(PosTrack &tracks[], int &track_count)
{
    for(int i = track_count - 1; i >= 0; i--)
    {
        bool found = false;
        for(int p = PositionsTotal() - 1; p >= 0; p--)
        {
            ulong ticket = PositionGetTicket(p);
            if(ticket == tracks[i].ticket)
            {
                found = true;
                break;
            }
        }
        if(!found)
        {
            PrintPositionGoneDebug(tracks[i]);
            for(int j = i; j < track_count - 1; j++)
                tracks[j] = tracks[j + 1];
            track_count--;
        }
    }
}

void CheckMFEFailExit(PosTrack &track, const EAState &state,
                      PosTrack &tracks[], int &track_count)
{
    if(CfgMFEFailMinR() <= 0) return;
    if(track.be_applied || track.trail_level > 0 || track.dtp_active || track.partial_closed || track.dtp_partial_closed)
        return;
    if(!PositionSelectByTicket(track.ticket)) return;

    double current_price = PositionGetDouble(POSITION_PRICE_CURRENT);
    double current_r = PriceToR(current_price, track.entry_price, track.risk_price, track.direction);
    track.peak_profit_r = MathMax(track.peak_profit_r, current_r);

    if(track.peak_profit_r < CfgMFEFailMinR())
        return;
    if(current_r > CfgMFEFailExitR())
        return;
    if(ShouldSkipCloseAttempt(track))
        return;

    double source_volume = PositionGetDouble(POSITION_VOLUME);
    PrintExitDebug("mfe_fail", track, current_r, state);
    if(ClosePosition(track.ticket, "mfe_fail"))
        OpenFailureReverse(track, "mfe_fail", source_volume, state.bar_count, tracks, track_count);
    else
        MarkCloseAttemptFailed(track);
}

void CheckEarlyLossCut(PosTrack &track, const EAState &state,
                       PosTrack &tracks[], int &track_count)
{
    if(InpEarlyLossCutR <= 0) return;
    if(track.be_applied || track.trail_level > 0 || track.dtp_active || track.partial_closed || track.dtp_partial_closed)
        return;
    if(!PositionSelectByTicket(track.ticket)) return;

    double current_price = PositionGetDouble(POSITION_PRICE_CURRENT);
    double current_r = PriceToR(current_price, track.entry_price, track.risk_price, track.direction);
    if(current_r > -InpEarlyLossCutR)
        return;
    if(ShouldSkipCloseAttempt(track))
        return;

    double source_volume = PositionGetDouble(POSITION_VOLUME);
    if(ClosePosition(track.ticket, "early_loss"))
        OpenFailureReverse(track, "early_loss", source_volume, state.bar_count, tracks, track_count);
    else
        MarkCloseAttemptFailed(track);
}

void CheckNoMFEExit(PosTrack &track, const EAState &state,
                    PosTrack &tracks[], int &track_count)
{
    if(CfgNoMFEExitBars() <= 0) return;
    if(track.be_applied || track.trail_level > 0 || track.dtp_active || track.partial_closed || track.dtp_partial_closed)
        return;
    if(!PositionSelectByTicket(track.ticket)) return;

    double current_price = PositionGetDouble(POSITION_PRICE_CURRENT);
    double current_r = PriceToR(current_price, track.entry_price, track.risk_price, track.direction);
    track.peak_profit_r = MathMax(track.peak_profit_r, current_r);

    int bars_held = state.bar_count - track.open_bar;
    if(bars_held < CfgNoMFEExitBars())
        return;
    if(track.peak_profit_r >= CfgNoMFEMinPeakR())
        return;
    if(current_r > CfgNoMFEExitR())
        return;
    if(ShouldSkipCloseAttempt(track))
        return;

    double source_volume = PositionGetDouble(POSITION_VOLUME);
    PrintExitDebug("no_mfe", track, current_r, state);
    if(ClosePosition(track.ticket, "no_mfe"))
        OpenFailureReverse(track, "no_mfe", source_volume, state.bar_count, tracks, track_count);
    else
        MarkCloseAttemptFailed(track);
}

void CheckPartialClose(PosTrack &track, const EAState &state)
{
    double partial_r = InpPartialCloseR;
    int partial_pct = InpPartialClosePct;
    if(track.htf_target && track.htf_partial_r > 0)
    {
        partial_r = track.htf_partial_r;
        partial_pct = track.htf_partial_pct;
    }

    if(partial_r <= 0) return;
    if(track.partial_closed) return;
    if(InpPartialOnlyDeep && !track.deep_entry) return;

    if(!PositionSelectByTicket(track.ticket)) return;

    double current_price = PositionGetDouble(POSITION_PRICE_CURRENT);
    double current_r = PriceToR(current_price, track.entry_price, track.risk_price, track.direction);

    if(current_r >= partial_r)
    {
        if(ShouldSkipCloseAttempt(track))
            return;

        if(PartialClose(track.ticket, partial_pct))
        {
            track.partial_closed = true;
            if(InpPartialPostLockR > 0)
            {
                double new_sl = RToPrice(InpPartialPostLockR, track.entry_price, track.risk_price, track.direction);
                ApplyProtectiveSL(track, new_sl, "partial_lock", current_r);
            }
            PrintSLDebug("partial", track, current_r, 0);
        }
        else
            MarkCloseAttemptFailed(track);
    }
}

void CheckBreakeven(PosTrack &track, const EAState &state)
{
    if(track.be_applied) return;

    double be_r = CfgBreakevenR();
    double be_lock_r = CfgBreakevenLockR();

    if(track.direction > 0)
    {
        if(InpBuyBE_R > 0) be_r = InpBuyBE_R;
        if(InpBuyBE_Lock > 0) be_lock_r = InpBuyBE_Lock;
    }
    else if(track.direction < 0)
    {
        if(InpSellBE_R > 0) be_r = InpSellBE_R;
        if(InpSellBE_Lock > 0) be_lock_r = InpSellBE_Lock;
    }

    // v11: 鐢ㄥ叆鍦烘椂閿佸畾鐨勫競鍦虹姸鎬?
    if(CfgEnableStateFilter())
    {
        if(track.entry_market_state == 0 && CfgRangeBE_R() > 0)
            be_r = CfgRangeBE_R();
        else if(track.entry_market_state != 0)
        {
            if(CfgTrendBE_R() > 0) be_r = CfgTrendBE_R();
            if(CfgTrendBE_Lock() > 0) be_lock_r = CfgTrendBE_Lock();
        }
    }

    if(!UseBTCProfile() && InpContextBER > 0 && InpContextBEMinPrice > 0)
    {
        bool context_be = (track.entry_price >= InpContextBEMinPrice);
        if(context_be && InpContextBEMaxPrice > 0 && track.entry_price > InpContextBEMaxPrice)
            context_be = false;
        if(context_be && InpContextBEMaxMonthStartBalance > 0)
        {
            SyncMonthlyRiskState();
            if(g_monthly_start_balance <= 0 ||
               g_monthly_start_balance > InpContextBEMaxMonthStartBalance)
                context_be = false;
        }
        if(context_be)
        {
            be_r = InpContextBER;
            be_lock_r = InpContextBELockR;
        }
    }

    if(be_r <= 0) return;

    if(!PositionSelectByTicket(track.ticket)) return;

    double current_price = PositionGetDouble(POSITION_PRICE_CURRENT);
    double current_r = PriceToR(current_price, track.entry_price, track.risk_price, track.direction);

    if(current_r >= be_r)
    {
        double new_sl = RToPrice(be_lock_r, track.entry_price, track.risk_price, track.direction);
        if(ShouldSkipCloseAttempt(track))
            return;

        if(ApplyProtectiveSL(track, new_sl, "be", current_r))
        {
            track.be_applied = true;
        }
        else
            MarkCloseAttemptFailed(track);
    }
}

void CheckTrailing(PosTrack &track)
{
    if(!PositionSelectByTicket(track.ticket)) return;

    double current_price = PositionGetDouble(POSITION_PRICE_CURRENT);
    double current_sl    = PositionGetDouble(POSITION_SL);
    double current_r = PriceToR(current_price, track.entry_price, track.risk_price, track.direction);

    track.peak_profit_r = MathMax(track.peak_profit_r, current_r);

    // 浠庢渶楂樼骇鍒悜涓嬫鏌ワ紝閬垮厤鍚屼竴tick澶氭ModifySL
    // Level 3 鍗囩骇
    if(InpTrail3TriggerR > 0 && current_r >= InpTrail3TriggerR && track.trail_level < 3)
    {
        double lock_r = InpTrail3LockR > 0 ? InpTrail3LockR : track.peak_profit_r * InpTrail3LockMult;
        double new_sl = RToPrice(lock_r, track.entry_price, track.risk_price, track.direction);
        if(ShouldSkipCloseAttempt(track))
            return;

        if(ApplyProtectiveSL(track, new_sl, "trail3", current_r))
        {
            track.trail_level = 3;
        }
        else
            MarkCloseAttemptFailed(track);
        return;
    }
    // Level 2 鍗囩骇
    else if(InpTrail2TriggerR > 0 && current_r >= InpTrail2TriggerR && track.trail_level < 2)
    {
        double lock_r = InpTrail2LockR > 0 ? InpTrail2LockR : track.peak_profit_r * InpTrail2LockMult;
        double new_sl = RToPrice(lock_r, track.entry_price, track.risk_price, track.direction);
        if(ShouldSkipCloseAttempt(track))
            return;

        if(ApplyProtectiveSL(track, new_sl, "trail2", current_r))
        {
            track.trail_level = 2;
        }
        else
            MarkCloseAttemptFailed(track);
        return;
    }
    // Level 1 鍗囩骇
    else if(InpTrail1TriggerR > 0 && current_r >= InpTrail1TriggerR && track.trail_level < 1)
    {
        double new_sl = RToPrice(InpTrail1LockR, track.entry_price, track.risk_price, track.direction);
        if(ShouldSkipCloseAttempt(track))
            return;

        if(ApplyProtectiveSL(track, new_sl, "trail1", current_r))
        {
            track.trail_level = 1;
        }
        else
            MarkCloseAttemptFailed(track);
        return;
    }

    // 鍔ㄦ€佹帹杩? 褰撳墠绾у埆鐨凩ockMult > 0鏃讹紝闅弍eak澧為暱鎸佺画鎺ㄨ繘SL
    double lock_mult = 0;
    if(track.trail_level == 3 && InpTrail3LockMult > 0)
        lock_mult = InpTrail3LockMult;
    else if(track.trail_level == 2 && InpTrail2LockMult > 0)
        lock_mult = InpTrail2LockMult;

    if(lock_mult > 0)
    {
        double lock_r = track.peak_profit_r * lock_mult;
        double new_sl = RToPrice(lock_r, track.entry_price, track.risk_price, track.direction);
        if((track.direction > 0 && new_sl > current_sl) ||
           (track.direction < 0 && new_sl < current_sl))
        {
            if(ShouldSkipCloseAttempt(track))
                return;

            if(ApplyProtectiveSL(track, new_sl, "trail_dyn", current_r))
            {
            }
            else
                MarkCloseAttemptFailed(track);
        }
    }
}

double GetDTPRetrace(const PosTrack &track, const EAState &state)
{
    double dtp_retrace = CfgDTPRetrace();
    if(track.direction > 0 && InpBuyDTPRetrace > 0)
        dtp_retrace = InpBuyDTPRetrace;
    else if(track.direction < 0 && InpSellDTPRetrace > 0)
        dtp_retrace = InpSellDTPRetrace;
    if(track.htf_target && InpHTFDTPRetrace > 0)
        dtp_retrace = InpHTFDTPRetrace;
    if(CfgEnableStateFilter() && track.entry_market_state != 0 && CfgTrendDTPRetrace() > 0)
        dtp_retrace = CfgTrendDTPRetrace() / 100.0;
    if(InpDTPStage2TriggerR > 0 && InpDTPStage2Retrace > 0 && track.dtp_peak_r >= InpDTPStage2TriggerR)
        dtp_retrace = InpDTPStage2Retrace;
    if(InpDTPStage3TriggerR > 0 && InpDTPStage3Retrace > 0 && track.dtp_peak_r >= InpDTPStage3TriggerR)
        dtp_retrace = InpDTPStage3Retrace;
    if(track.dtp_partial_closed && CfgDTPPostPartialRetrace() > 0)
        dtp_retrace = CfgDTPPostPartialRetrace();
    if(track.htf_target && track.dtp_partial_closed && InpHTFDTPPostPartialRetrace > 0)
        dtp_retrace = InpHTFDTPPostPartialRetrace;
    if(InpEnableMomentumRegime && InpStrongDTPRetraceMult > 0 && IsPositionStrong(track, state))
        dtp_retrace *= InpStrongDTPRetraceMult;
    return dtp_retrace;
}

void ApplyDTPPostPartialLock(PosTrack &track, double current_r)
{
    if(CfgDTPPostPartialLockR() <= 0) return;
    if(current_r <= CfgDTPPostPartialLockR()) return;
    if(!PositionSelectByTicket(track.ticket)) return;

    double current_price = PositionGetDouble(POSITION_PRICE_CURRENT);
    double current_sl = PositionGetDouble(POSITION_SL);
    double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
    double new_sl = RToPrice(CfgDTPPostPartialLockR(), track.entry_price, track.risk_price, track.direction);

    if(track.direction > 0)
    {
        if(new_sl <= current_sl || new_sl >= current_price - point)
            return;
    }
    else
    {
        if(new_sl >= current_sl || new_sl <= current_price + point)
            return;
    }

    if(ShouldSkipCloseAttempt(track))
        return;

    if(!ApplyProtectiveSL(track, new_sl, "dtp_part_lock", current_r))
        MarkCloseAttemptFailed(track);
}

void CheckDTP(PosTrack &track, const EAState &state)
{
    double dtp_trigger_r = CfgDTPTriggerR();
    if(track.direction > 0 && InpBuyDTPTriggerR > 0)
        dtp_trigger_r = InpBuyDTPTriggerR;
    else if(track.direction < 0 && InpSellDTPTriggerR > 0)
        dtp_trigger_r = InpSellDTPTriggerR;
    if(track.htf_target && InpHTFDTPTriggerR > 0)
        dtp_trigger_r = InpHTFDTPTriggerR;
    if(dtp_trigger_r <= 0) return;
    if(!PositionSelectByTicket(track.ticket)) return;

    double current_price = PositionGetDouble(POSITION_PRICE_CURRENT);
    double current_r = PriceToR(current_price, track.entry_price, track.risk_price, track.direction);

    if(!track.dtp_active && current_r >= dtp_trigger_r)
    {
        track.dtp_active = true;
        track.dtp_peak_r = current_r;
    }

    if(track.dtp_active)
    {
        track.dtp_peak_r = MathMax(track.dtp_peak_r, current_r);
        double dtp_retrace = GetDTPRetrace(track, state);
        double retrace = track.dtp_peak_r - current_r;
        double threshold = InpAdaptiveDTP ? track.dtp_peak_r * dtp_retrace
                                          : dtp_trigger_r * dtp_retrace;
        if(retrace >= threshold)
        {
            if(ShouldSkipCloseAttempt(track))
                return;

            if(InpDTPExitMode == 1 && !track.dtp_partial_closed)
            {
                if(PartialClose(track.ticket, InpDTPPartialPct))
                {
                    track.dtp_partial_closed = true;
                    ApplyDTPPostPartialLock(track, current_r);
                    PrintExitDebug("dtp_partial", track, current_r, state);
                    if(CfgDTPResetPeakAfterPartial())
                        track.dtp_peak_r = current_r;
                    return;
                }
            }
            PrintExitDebug(track.dtp_partial_closed ? "dtp2" : "dtp", track, current_r, state);
            if(!ClosePosition(track.ticket, track.dtp_partial_closed ? "dtp2" : "dtp"))
                MarkCloseAttemptFailed(track);
        }
    }
}

bool IsPositionStrong(const PosTrack &track, const EAState &state)
{
    if(!InpEnableMomentumRegime && !InpEnableStrongAddOn)
        return false;

    MqlRates rates[];
    int need = MathMax(InpStrongMomentumBars, 4) + 2;
    int count = CopyRates(_Symbol, GetWorkTF(), 0, need, rates);
    if(count < need)
        return false;

    return CheckStrongMomentum(_Symbol, track.direction, rates, count);
}

void CheckDecay(PosTrack &track, const EAState &state)
{
    if(!CfgEnableDecayExit() && !InpEnableMomentumRegime) return;

    // DTP婵€娲诲悗绂佺敤琛板噺妫€娴嬶紝璁╁ぇ璧㈠崟鑷敱璺?
    if(track.dtp_active) return;

    // 缂撳瓨 M1 rates锛氬悓涓€ bar 鍐呭彧 CopyRates 涓€娆★紙bar绾фā寮忥紝tick绾ф鏌ユ棤鎰忎箟锛?
    static int    s_decay_bar = 0;
    static MqlRates s_m1_rates[];
    static int    s_m1_count = 0;

    if(state.bar_count != s_decay_bar)
    {
        s_decay_bar = state.bar_count;
        s_m1_count = CopyRates(_Symbol, PERIOD_M1, 0, CfgDecayBars() + 5, s_m1_rates);
    }
    if(s_m1_count < CfgDecayBars() + 2) return;

    if(!PositionSelectByTicket(track.ticket)) return;

    double current_price = PositionGetDouble(POSITION_PRICE_CURRENT);
    double current_r = PriceToR(current_price, track.entry_price, track.risk_price, track.direction);

    // 闇囪崱鎬佸叆鍦哄崟琛板噺闂ㄦ鏇翠綆(0.5R)锛岃秼鍔挎€佺敤涓诲弬鏁?
    double effective_decay_min = CfgDecayMinR();
    if(track.entry_market_state == 0 && CfgDecayMinR() > 0.5)
        effective_decay_min = 0.5;

    bool decay = CfgEnableDecayExit() && current_r >= effective_decay_min &&
                 CheckMomentumDecay(_Symbol, track.direction, s_m1_rates, s_m1_count);
    bool weak = InpEnableMomentumRegime && current_r >= InpWeakExitMinR &&
                CheckMomentumWeakness(_Symbol, track.direction, s_m1_rates, s_m1_count);
    if(decay || weak)
    {
        if(ShouldSkipCloseAttempt(track))
            return;

        string reason = weak ? "momentum_weak" : "decay";
        PrintExitDebug(reason, track, current_r, state);
        if(!ClosePosition(track.ticket, reason))
            MarkCloseAttemptFailed(track);
    }
}

void CheckTimeExit(PosTrack &track, const EAState &state)
{
    int time_exit_bars = CfgTimeExitBars();

    // v11: 鐢ㄥ叆鍦烘椂閿佸畾鐨勫競鍦虹姸鎬佸垽鏂秴鏃?
    if(CfgEnableStateFilter() && track.entry_market_state == 0 && CfgRangeTimeExit() < 999)
        time_exit_bars = CfgRangeTimeExit();

    if(time_exit_bars >= 999) return;

    int bars_held = state.bar_count - track.open_bar;
    if(bars_held >= time_exit_bars)
    {
        if(ShouldSkipCloseAttempt(track))
            return;

        double current_r = CurrentR(track);
        PrintExitDebug("time", track, current_r, state);
        if(!ClosePosition(track.ticket, "time"))
            MarkCloseAttemptFailed(track);
    }
}

void RegisterPosition(ulong ticket, int direction, double entry, double sl, double risk_price,
                      bool deep_entry,
                      bool htf_target, double htf_partial_r, int htf_partial_pct,
                      bool failure_reverse,
                      PosTrack &tracks[], int &track_count)
{
    if(track_count >= MAX_POSITIONS)
    {
        Print("璺熻釜鏁扮粍宸叉弧, 鏃犳硶娉ㄥ唽 ticket=", ticket);
        return;
    }

    PosTrack t;
    ZeroMemory(t);
    t.ticket       = ticket;
    t.direction    = direction;
    t.entry_price  = entry;
    t.sl_initial   = sl;
    t.virtual_sl = sl;
    t.virtual_sl_reason = "initial";
    t.risk_price   = risk_price;
    t.peak_profit_r = 0;
    t.open_bar     = 0;  // 鐢辫皟鐢ㄨ€呭湪娉ㄥ唽鍚庤缃?鎴栫洿鎺ョ敤state.bar_count
    t.be_applied   = false;
    t.trail_level  = 0;
    t.dtp_active   = false;
    t.dtp_peak_r   = 0;
    t.partial_closed = false;
    t.dtp_partial_closed = false;
    t.deep_entry = deep_entry;
    t.htf_target = htf_target;
    t.htf_partial_r = htf_partial_r;
    t.htf_partial_pct = htf_partial_pct;
    t.failure_reverse = failure_reverse;
    t.addon_count = 0;
    t.strong_addon = false;
    t.last_close_attempt = 0;
    t.last_sl_reason = "";
    t.entry_market_state = 0;

    tracks[track_count] = t;
    track_count++;
}

#endif
