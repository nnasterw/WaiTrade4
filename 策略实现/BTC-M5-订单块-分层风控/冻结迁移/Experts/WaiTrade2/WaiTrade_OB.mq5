#property copyright "WaiTrade2"
#property version   "98.01"
#property strict

#include <WaiTrade2/Config.mqh>
#include <WaiTrade2/Types.mqh>
#include <WaiTrade2/Utils.mqh>
#include <WaiTrade2/MarketState.mqh>
#include <WaiTrade2/ScoreEngine.mqh>
#include <WaiTrade2/DecayDetector.mqh>
#include <WaiTrade2/OBDetector.mqh>
#include <WaiTrade2/SignalEngine.mqh>
#include <WaiTrade2/EntryEngine.mqh>
#include <WaiTrade2/PositionManager.mqh>

OBZone      g_zones[MAX_OB_ZONES];
OBZone      g_htf_zones[MAX_OB_ZONES];
PosTrack    g_tracks[MAX_POSITIONS];
EAState     g_state;
TradeSignal g_signals[10];
int         g_track_count = 0;
int         g_htf_zone_count = 0;

// v9.8a EntryEngine
EntryMonitor g_monitors[MAX_MONITORS];
EntryMonitor g_htf_monitors[MAX_MONITORS];
int          g_monitor_count = 0;
int          g_htf_monitor_count = 0;
datetime     g_last_entry_attempt = 0;

// 鍙寊one閫氶亾锛歁3鎸崱鑵跨嫭绔媧one缂撳瓨锛堝缁堢淮鎶わ紝涓嶅彈瓒嬪娍妯″紡鍒囨崲褰卞搷锛?
OBZone      g_zones_osc[MAX_OB_ZONES];
EAState     g_state_osc;
EntryMonitor g_monitors_osc[MAX_MONITORS];
int          g_monitor_count_osc = 0;
bool         g_osc_active = false; // 褰撳墠tick鏄惁浣跨敤鎸崱閫氶亾

// 鈹€鈹€ OB鍔ㄦ€佸勾榫勭鐞嗭細瓒呴緞zone鑷姩鏍囪涓篹xpired 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
void ExpireOldZones(OBZone& zones[], int ob_count, int bar_count)
{
    if(InpMaxOBAgeBarsTF <= 0) return;
    for(int z = 0; z < ob_count; z++)
    {
        if(zones[z].expired) continue;
        if(bar_count - zones[z].created_bar > InpMaxOBAgeBarsTF)
            zones[z].expired = true;
    }
}

// 鈹€鈹€ 鍙岄€氶亾杈呭姪鍑芥暟锛氭敞鍐屾椿璺僌B涓虹洃瑙嗗櫒 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
void RegisterChannelMonitors(OBZone& zones[], EAState& state,
                              EntryMonitor& mons[], int& mon_count,
                              bool new_active_bar, string symbol)
{
    if(!new_active_bar) return;
    double spread = GetSpread(symbol);
    for(int z = 0; z < state.ob_count; z++)
    {
        if(zones[z].expired || zones[z].used) continue;
        if(!PassOBReentryCooldown(zones[z])) continue;
        if(CfgEnableStateFilter() && state.market_state != 0
           && state.market_state != zones[z].direction) continue;

        double risk_dist = (zones[z].direction == OB_BUY)
            ? ((zones[z].high + zones[z].low) / 2.0) - (zones[z].low - state.atr_value * CfgSLBufferATR())
            : (zones[z].high + state.atr_value * CfgSLBufferATR()) - ((zones[z].high + zones[z].low) / 2.0);
        if(spread > 0 && risk_dist / spread < CfgMinRiskSpreadRatio()) continue;

        TradeSignal tmp;
        ZeroMemory(tmp);
        tmp.direction  = zones[z].direction;
        tmp.sl         = (zones[z].direction == OB_BUY)
            ? zones[z].low  - state.atr_value * CfgSLBufferATR()
            : zones[z].high + state.atr_value * CfgSLBufferATR();
        tmp.risk_price = MathAbs(((zones[z].high + zones[z].low) / 2.0) - tmp.sl);
        tmp.ob_index   = z;
        tmp.pos_mult   = 1.0;

        if(CfgEnableScoring())
        {
            double prox = (state.atr_m15 > 0) ? state.atr_m15 : state.atr_value * 5;
            int score   = CalcSignalScore(zones[z], state, state.market_state, prox, tmp.risk_price, 0);
            if(score < CfgMinScore()) continue;
            double mult = ScoreToMultiplier(score);
            if(mult < 0) continue;
            tmp.pos_mult = mult;
        }
        AddEntryMonitor(tmp, zones[z], mons, mon_count);
    }
}

// 鈹€鈹€ 鍙岄€氶亾杈呭姪鍑芥暟锛氭墽琛屽凡纭鐨勫叆鍦?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
void ExecuteChannelConfirmed(OBZone& zones[], EAState& state,
                              EntryMonitor& mons[], int& mon_count,
                              double bid, double ask, string symbol)
{
    TradeSignal confirmed[10];
    int conf_count = UpdateEntryMonitors(bid, ask, TimeCurrent(), mons, mon_count, confirmed, 10);
    for(int i = 0; i < conf_count; i++)
    {
        if(state.pos_count >= CfgMaxConcurrent()) break;
        if(confirmed[i].ob_index < 0 || confirmed[i].ob_index >= state.ob_count) continue;
        if(!FinalizeEntryEngineSignal(symbol, zones[confirmed[i].ob_index], state, confirmed[i])) continue;
        if(ExecuteSignal(confirmed[i]))
        {
            state.last_entry_bar = state.bar_count;
            state.pos_count++;
        }
    }
}

int OnInit()
{
    ZeroMemory(g_state);
    ZeroMemory(g_zones);
    ZeroMemory(g_htf_zones);
    ZeroMemory(g_tracks);
    g_track_count = 0;
    g_htf_zone_count = 0;
    g_monitor_count = 0;
    g_htf_monitor_count = 0;
    ZeroMemory(g_state_osc);
    ZeroMemory(g_zones_osc);
    ZeroMemory(g_monitors_osc);
    g_monitor_count_osc = 0;
    g_last_entry_attempt = 0;

    if(CfgRiskPercent() <= 0 || CfgRiskPercent() > 50)
    {
        Print("鍙傛暟閿欒: RiskPercent=", CfgRiskPercent());
        return INIT_PARAMETERS_INCORRECT;
    }

    SymbolSelect(_Symbol, true);
    SyncMonthlyRiskState();
    Print("WaiTrade2 ", InpVersion, " 宸插姞杞?| ", _Symbol, " | Magic=", InpMagicNumber);
    return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
    Print("WaiTrade2 ", InpVersion, " 宸插嵏杞?| 鍘熷洜=", reason);
}

void OnTick()
{
    string symbol = _Symbol;
    ENUM_TIMEFRAMES tf = GetWorkTF();

    // 鏈堝垵OB zone閲嶇疆锛堟秷闄ゅ鏈堢姸鎬佸欢缁淇″彿璐ㄩ噺鐨勫奖鍝嶏級
    if(InpMonthlyZoneReset)
    {
        static int s_prev_month = 0;
        MqlDateTime dt;
        TimeToStruct(TimeCurrent(), dt);
        int cur_month = dt.year * 100 + dt.mon;
        if(s_prev_month != 0 && cur_month != s_prev_month)
        {
            ZeroMemory(g_zones);
            ZeroMemory(g_htf_zones);
            g_state.ob_count = 0;
            g_htf_zone_count = 0;
            g_monitor_count = 0;
            g_htf_monitor_count = 0;
            g_state.last_entry_bar = 0;
            // 鍚屾娓呴櫎鎸崱閫氶亾
            ZeroMemory(g_zones_osc);
            g_state_osc.ob_count = 0;
            g_monitor_count_osc = 0;
            g_state_osc.last_entry_bar = 0;
            Print("鏈堝垵Zone閲嶇疆 ", dt.year, ".", StringFormat("%02d", dt.mon));
        }
        s_prev_month = cur_month;
    }

    // 鍙岄€氶亾妯″紡锛歁3鎸崱閫氶亾鐙珛缁存姢锛屾棤鍒囨崲娓呴櫎
    // 鍗曢€氶亾妯″紡锛堝厹搴曪級锛氬垏鎹㈡椂娓呴櫎锛岄槻姝F涓嶅悓鐨凮B鐩镐簰姹℃煋
    bool s_dual = InpEnableDualZoneChannel && InpEnableXAUTrendProfile;
    if(InpEnableXAUTrendProfile && !s_dual)
    {
        static bool s_last_trend_profile = false;
        bool cur_trend = UseXAUTrendProfile();
        if(cur_trend != s_last_trend_profile)
        {
            ZeroMemory(g_zones);
            ZeroMemory(g_htf_zones);
            g_state.ob_count = 0;
            g_htf_zone_count = 0;
            g_monitor_count = 0;
            g_htf_monitor_count = 0;
            s_last_trend_profile = cur_trend;
            Print("Profile鍒囨崲zone娓呴櫎(鍗曢€氶亾): ", cur_trend ? "鈫扵rend" : "鈫扚AGE");
        }
    }

    // 1. 鍔犺浇K绾挎暟鎹?
    // 鍙岄€氶亾妯″紡锛氫富閫氶亾鍥哄畾鐢∕1锛堣秼鍔块€氶亾锛夛紱鍙︽湁M3鎸崱閫氶亾鐙珛鏇存柊
    ENUM_TIMEFRAMES act_tf = s_dual ? (ENUM_TIMEFRAMES)CfgMinutesToTF(InpXAUTrendBarTF) : tf;
    MqlRates rates[];
    int copied = CopyRates(symbol, act_tf, 0, InpBars, rates);
    if(copied < 100) {
        static datetime s_last_copy_fail = 0;
        if(TimeCurrent() - s_last_copy_fail >= 300) {
            s_last_copy_fail = TimeCurrent();
            Print("CopyRates澶辫触: symbol=", symbol, " tf=", act_tf, " copied=", copied);
        }
        return;
    }

    g_state.atr_value = CalcATR(rates, copied, InpATRPeriod);

    // 2. 鏂癰ar澶勭悊锛堣秼鍔块€氶亾 / 鍗曢€氶亾涓婚€氶亾锛?
    bool new_bar = IsNewBar(symbol, act_tf);
    if(new_bar)
    {
        g_state.bar_count++;

        DetectOrderBlocks(rates, copied, g_zones, g_state.ob_count, g_state);
        if(InpConsolidateOB) ConsolidateOBs(g_zones, g_state.ob_count);
        ExpireOldZones(g_zones, g_state.ob_count, g_state.bar_count);
        if(InpEnableHTFPullback && !InpHTFPullbackOnly)
        {
            CompactZones(g_htf_zones, g_htf_zone_count);
            DetectHTFPullbacks(g_htf_zones, g_htf_zone_count, g_state, GetSpread(symbol));
        }

        MqlRates rates_h1[];
        int h1_count = CopyRates(symbol, PERIOD_H1, 0, 100, rates_h1);
        if(h1_count > InpATRPeriod)
            g_state.atr_1h = CalcATR(rates_h1, h1_count, InpATRPeriod);

        int h1_dir = Detect1HOBDirection(symbol);
        Update1HAlignment(g_zones, g_state.ob_count, h1_dir);
        if(InpEnableHTFPullback && !InpHTFPullbackOnly)
            Update1HAlignment(g_htf_zones, g_htf_zone_count, h1_dir);

        if(CfgEnableStateFilter() || CfgEnableScoring())
        {
            double target = 0;
            g_state.market_state = (int)DetectMarketState(symbol, target);
            g_state.target_price = target;

            MqlRates rates_m15[];
            int m15_count = CopyRates(symbol, PERIOD_M15, 0, CfgTrendLookback(), rates_m15);
            if(m15_count > 14)
                g_state.atr_m15 = CalcATR(rates_m15, m15_count, InpATRPeriod);
        }
    }

    // 鍙岄€氶亾锛歁3鎸崱閫氶亾濮嬬粓鐙珛鏇存柊锛坣ew_osc_bar_tick 鎻愬崌浣滅敤鍩熶緵淇″彿鎵弿浣跨敤锛?
    bool new_osc_bar_tick = false;
    if(s_dual)
    {
        ENUM_TIMEFRAMES osc_tf = (ENUM_TIMEFRAMES)CfgMinutesToTF(InpBarTF);
        MqlRates osc_rates[];
        int osc_copied = CopyRates(symbol, osc_tf, 0, InpBars, osc_rates);
        if(osc_copied >= 100)
        {
            g_state_osc.atr_value = CalcATR(osc_rates, osc_copied, InpATRPeriod);
            bool new_osc = IsNewBar(symbol, osc_tf);
            new_osc_bar_tick = new_osc;
            if(new_osc)
            {
                g_state_osc.bar_count++;
                DetectOrderBlocks(osc_rates, osc_copied, g_zones_osc, g_state_osc.ob_count, g_state_osc);
                if(InpConsolidateOB) ConsolidateOBs(g_zones_osc, g_state_osc.ob_count);
                ExpireOldZones(g_zones_osc, g_state_osc.ob_count, g_state_osc.bar_count);

                MqlRates osc_h1[];
                int osc_h1c = CopyRates(symbol, PERIOD_H1, 0, 100, osc_h1);
                if(osc_h1c > InpATRPeriod)
                    g_state_osc.atr_1h = CalcATR(osc_h1, osc_h1c, InpATRPeriod);
                int osc_h1dir = Detect1HOBDirection(symbol);
                Update1HAlignment(g_zones_osc, g_state_osc.ob_count, osc_h1dir);

                if(CfgEnableStateFilter() || CfgEnableScoring())
                {
                    double osc_target = 0;
                    g_state_osc.market_state = (int)DetectMarketState(symbol, osc_target);
                    g_state_osc.target_price = osc_target;
                    MqlRates osc_m15[];
                    int osc_m15c = CopyRates(symbol, PERIOD_M15, 0, CfgTrendLookback(), osc_m15);
                    if(osc_m15c > 14)
                        g_state_osc.atr_m15 = CalcATR(osc_m15, osc_m15c, InpATRPeriod);
                }
            }
        }
    }

    // 3. 鏇存柊OB鐘舵€?姣弔ick) + 閫夋嫨娲昏穬閫氶亾
    g_osc_active = s_dual && !UseXAUTrendProfile();
    double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
    double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
    UpdateOBStatus(g_zones, g_state.ob_count, bid, ask, g_state);
    if(s_dual)
        UpdateOBStatus(g_zones_osc, g_state_osc.ob_count, bid, ask, g_state_osc);
    else if(InpEnableHTFPullback && !InpHTFPullbackOnly)
        UpdateOBStatus(g_htf_zones, g_htf_zone_count, bid, ask, g_state);
    // 4. 鎵弿鍏ュ満淇″彿锛堝弻閫氶亾锛氭尟鑽＄敤M3 osc閫氶亾锛岃秼鍔跨敤M1涓婚€氶亾锛?
    bool new_active_bar = g_osc_active ? new_osc_bar_tick : new_bar;

    if(g_osc_active)
        g_state_osc.pos_count = CountActivePositions();
    else
        g_state.pos_count = CountActivePositions();

    if(InpEnableEntryEngine)
    {
        // 娉ㄥ唽娲昏穬閫氶亾鐨凮B鐩戣鍣?
        if(g_osc_active)
            RegisterChannelMonitors(g_zones_osc, g_state_osc, g_monitors_osc, g_monitor_count_osc, new_active_bar, symbol);
        else
            RegisterChannelMonitors(g_zones, g_state, g_monitors, g_monitor_count, new_active_bar, symbol);

        // HTF pullback锛堜粎鍗曢€氶亾鎴栬秼鍔块€氶亾妯″紡锛?
        if(!g_osc_active && new_bar && InpEnableHTFPullback && !InpHTFPullbackOnly)
        {
            for(int z = 0; z < g_htf_zone_count; z++)
            {
                if(g_htf_zones[z].expired || g_htf_zones[z].used) continue;
                if(!PassOBReentryCooldown(g_htf_zones[z])) continue;
                if(CfgEnableStateFilter() && g_state.market_state != 0 &&
                   g_state.market_state != g_htf_zones[z].direction) continue;

                TradeSignal tmp;
                ZeroMemory(tmp);
                tmp.direction  = g_htf_zones[z].direction;
                tmp.sl         = (g_htf_zones[z].direction == OB_BUY)
                    ? g_htf_zones[z].low  - g_state.atr_value * CfgSLBufferATR()
                    : g_htf_zones[z].high + g_state.atr_value * CfgSLBufferATR();
                tmp.risk_price = MathAbs(((g_htf_zones[z].high + g_htf_zones[z].low) / 2.0) - tmp.sl);
                tmp.ob_index   = z;
                tmp.pos_mult   = 1.0;
                AddEntryMonitor(tmp, g_htf_zones[z], g_htf_monitors, g_htf_monitor_count);
            }
        }

        // 5. 鎵ц纭鐨勫叆鍦?
        if(g_osc_active)
            ExecuteChannelConfirmed(g_zones_osc, g_state_osc, g_monitors_osc, g_monitor_count_osc, bid, ask, symbol);
        else
            ExecuteChannelConfirmed(g_zones, g_state, g_monitors, g_monitor_count, bid, ask, symbol);

        if(!g_osc_active && InpEnableHTFPullback && !InpHTFPullbackOnly)
        {
            TradeSignal htf_confirmed[10];
            int htf_conf_count = UpdateEntryMonitors(bid, ask, TimeCurrent(), g_htf_monitors, g_htf_monitor_count, htf_confirmed, 10);
            for(int i = 0; i < htf_conf_count; i++)
            {
                if(g_state.pos_count >= CfgMaxConcurrent()) break;
                if(htf_confirmed[i].ob_index < 0 || htf_confirmed[i].ob_index >= g_htf_zone_count) continue;
                if(!FinalizeEntryEngineSignal(symbol, g_htf_zones[htf_confirmed[i].ob_index], g_state, htf_confirmed[i])) continue;
                if(ExecuteSignalFromZone(htf_confirmed[i], g_htf_zones, g_htf_zone_count, false))
                {
                    g_state.last_entry_bar = g_state.bar_count;
                    g_state.pos_count++;
                }
            }
        }
    }
    else
    {
        // 鍘熷妯″紡: 鐩存帴鍏ュ満锛堜娇鐢ㄦ椿璺冮€氶亾锛?
        int sig_count;
        if(g_osc_active)
        {
            sig_count = ScanSignals(symbol, g_zones_osc, g_state_osc.ob_count, g_state_osc, g_signals, 10);
            for(int i = 0; i < sig_count; i++)
            {
                if(g_state_osc.pos_count >= CfgMaxConcurrent()) break;
                if(ExecuteSignal(g_signals[i])) { g_state_osc.last_entry_bar = g_state_osc.bar_count; g_state_osc.pos_count++; }
            }
        }
        else
        {
            sig_count = ScanSignals(symbol, g_zones, g_state.ob_count, g_state, g_signals, 10);
            for(int i = 0; i < sig_count; i++)
            {
                if(g_state.pos_count >= CfgMaxConcurrent()) break;
                if(ExecuteSignal(g_signals[i])) { g_state.last_entry_bar = g_state.bar_count; g_state.pos_count++; }
            }
        }
    }

    // 5b. H4瓒嬪娍杩藉崟锛堢嫭绔嬩簬OB绯荤粺锛岀敤浜嶣TC鐗涘競鏈堥『鍔垮叆鍦猴級
    TryH4TrendEntry(symbol, new_bar);

    // 5c. ATR閫氶亾鍧囧€煎洖褰掑叆鍦猴紙BTC楂樹綅鎸崱鏈堜笓鐢級
    TryATRChannelEntry(symbol, new_bar);

    // 5d. 鍔ㄩ噺杩借釜鍏ュ満锛堣繛缁悓鍚慔1 K绾胯拷鍗曪紝鍗曞悜瓒嬪娍鏈堜笓鐢級
    TryMomentumEntry(symbol, new_bar);
    TryEMATrendEntry(symbol, new_bar);

    // 6. 姣忓皬鏃跺瓨娲绘棩蹇?
    {
        static datetime s_last_hb = 0;
        datetime now_t = TimeCurrent();
        if(now_t - s_last_hb >= 3600)
        {
            s_last_hb = now_t;
            double spread = (double)(SymbolInfoInteger(symbol, SYMBOL_SPREAD));
            Print("HEARTBEAT ", InpVersion, " | ", symbol, " ", EnumToString(tf),
                  " | bar=", g_state.bar_count,
                  " | ob=", g_state.ob_count,
                  " | pos=", g_state.pos_count,
                  " | atr=", DoubleToString(g_state.atr_value, _Digits),
                  " | spread=", spread,
                  " | state=", g_state.market_state);
        }
    }

    // 7. 鎸佷粨绠＄悊
    SyncPositions(g_tracks, g_track_count);
    ManagePositions(g_tracks, g_track_count, g_state);
}

int CountActivePositions()
{
    if(CfgFreeRunMinR() <= 0)
        return CountPositions();
    int count = 0;
    for(int i = 0; i < g_track_count; i++)
    {
        if(g_tracks[i].ticket == 0) continue;
        if(g_tracks[i].peak_profit_r >= CfgFreeRunMinR())
            continue;
        count++;
    }
    return count;
}

bool ShouldSkipEntryAttempt()
{
    if(CfgCloseRetryCooldownSec() <= 0)
        return false;

    datetime now = TimeCurrent();
    return (g_last_entry_attempt > 0 &&
            now - g_last_entry_attempt < CfgCloseRetryCooldownSec());
}

void MarkEntryAttemptFailed()
{
    if(CfgCloseRetryCooldownSec() <= 0)
        return;
    datetime now = TimeCurrent();
    g_last_entry_attempt = now;
}

bool ExecuteLayeredOrders(const TradeSignal &sig, double base_price)
{
    if(InpLayeredEntryCount < 2) return false;
    if(sig.ob_index < 0 || sig.ob_index >= g_state.ob_count) return false;

    double ob_h = g_zones[sig.ob_index].high - g_zones[sig.ob_index].low;
    if(ob_h <= 0) return false;

    double spacing = ob_h * InpLayeredSpacingPct;
    int layers = MathMin(InpLayeredEntryCount - 1, 3);

    for(int i = 1; i <= layers; i++)
    {
        double offset = spacing * i;
        double limit_price = (sig.direction > 0) ? base_price - offset : base_price + offset;

        double lot_mult = 1.0 + (InpLayeredLotMult - 1.0) * i / layers;
        double layer_lot = NormalizeDouble(sig.lot * lot_mult, 2);
        double lot_min = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
        if(layer_lot < lot_min) layer_lot = lot_min;

        MqlTradeRequest req = {};
        MqlTradeResult  res = {};
        req.action = TRADE_ACTION_PENDING;
        req.symbol = _Symbol;
        req.volume = layer_lot;
        req.type   = (sig.direction > 0) ? ORDER_TYPE_BUY_LIMIT : ORDER_TYPE_SELL_LIMIT;
        req.price  = NormalizeDouble(limit_price, _Digits);
        req.sl     = BrokerStopFromVirtualSL(sig.sl, req.price, sig.risk_price, sig.direction);
        req.tp     = sig.tp;
        req.magic  = InpMagicNumber;
        req.comment = sig.comment + "_L" + IntegerToString(i+1);
        req.deviation = 20;
        req.type_filling = ORDER_FILLING_RETURN;
        req.type_time = ORDER_TIME_GTC;

        if(OrderSend(req, res))
        {
            if(res.retcode == TRADE_RETCODE_DONE || res.retcode == TRADE_RETCODE_PLACED)
                Print("鍒嗗眰鎸傚崟L", i+1, ": price=", req.price, " lot=", layer_lot);
        }
    }
    return true;
}

bool ExecuteMicroEntryOrders(const TradeSignal &sig)
{
    if(InpMicroEntryCount <= 0 || InpMicroEntryLotMult <= 0)
        return false;

    int count = MathMin(InpMicroEntryCount, 5);
    double lot_min = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
    if(InpMicroEntryMaxLotSize > 0 && InpMicroEntryMaxLotSize < lot_min)
        return false;

    double micro_lot = sig.lot * InpMicroEntryLotMult;
    if(InpMicroEntryMaxLotSize > 0 && micro_lot > InpMicroEntryMaxLotSize)
        micro_lot = InpMicroEntryMaxLotSize;
    micro_lot = NormalizeDouble(micro_lot, 2);
    if(micro_lot < lot_min)
        micro_lot = lot_min;

    bool placed = false;
    for(int i = 1; i <= count; i++)
    {
        MqlTradeRequest req = {};
        MqlTradeResult  res = {};
        req.action    = TRADE_ACTION_DEAL;
        req.symbol    = _Symbol;
        req.volume    = micro_lot;
        req.type      = sig.direction > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
        req.price     = sig.direction > 0 ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                                          : SymbolInfoDouble(_Symbol, SYMBOL_BID);
        req.sl     = BrokerStopFromVirtualSL(sig.sl, req.price, sig.risk_price, sig.direction);
        req.tp        = sig.tp;
        req.magic     = InpMagicNumber;
        req.comment   = sig.comment + "_M" + IntegerToString(i);
        req.deviation = 20;
        req.type_filling = ORDER_FILLING_IOC;
        req.type_time    = ORDER_TIME_GTC;

        if(!OrderSend(req, res) || res.retcode != TRADE_RETCODE_DONE)
            continue;

        placed = true;
        Print("寰粨鍓崟鎴愬姛 ", req.comment, " ticket=", res.order,
              " price=", res.price, " lot=", micro_lot);
        RecordMonthlyEntry();
        RegisterPosition(res.order, sig.direction, res.price, sig.sl, sig.risk_price,
                         sig.deep_entry,
                         sig.htf_target, sig.htf_partial_r, sig.htf_partial_pct,
                         sig.failure_reverse,
                         g_tracks, g_track_count);
        if(g_track_count > 0)
        {
            g_tracks[g_track_count - 1].open_bar = g_state.bar_count;
            g_tracks[g_track_count - 1].entry_market_state = g_state.market_state;
        }
    }

    return placed;
}

bool ExecuteSignal(const TradeSignal &sig)
{
    return ExecuteSignalFromZone(sig, g_zones, g_state.ob_count, true);
}

// H4杩炵画寮烘定杩藉崟锛歂鏍笻4姣忔牴娑ㄥ箙>X%鏃堕『鍔垮叆鍦?
void TryH4TrendEntry(string symbol, bool new_m5_bar)
{
    if(!InpEnableH4Trend || !new_m5_bar) return;
    if(g_state.pos_count >= CfgMaxConcurrent()) return;

    static int s_h4_cooldown = 0;
    if(s_h4_cooldown > 0) { s_h4_cooldown--; return; }

    MqlRates h4[];
    int n = MathMax(InpH4TrendBars + 1, 3);
    if(CopyRates(symbol, PERIOD_H4, 1, n, h4) < n) return;

    // 妫€鏌ユ渶杩?InpH4TrendBars 鏍瑰凡鏀剁洏H4 (h4[0]鏄渶鏃х殑锛宧4[n-1]鏄渶鏂板凡鏀剁洏)
    for(int i = 0; i < InpH4TrendBars; i++)
    {
        int idx = n - InpH4TrendBars + i;  // 浠庢渶鏃у埌鏈€鏂?
        double pct = 0;
        if(h4[idx].open > 0)
            pct = (h4[idx].close - h4[idx].open) / h4[idx].open * 100.0;
        if(pct < InpH4TrendMinPctPerBar) return;  // 浠讳竴鏍规湭杈炬爣锛屼笉杩藉崟
    }

    // 鎵€鏈塇4鍧囪揪鏍囷紝鏋勯€犺拷鍗?
    // SL = 鏈€杩?InpH4TrendSLBars 鏍笻4鐨勬渶浣庣偣
    double sl_low = h4[n-1].low;
    for(int i = 0; i < (int)InpH4TrendSLBars && i < n; i++)
        sl_low = MathMin(sl_low, h4[n-1-i].low);

    double sl = sl_low - g_state.atr_value * InpH4TrendSLBufferATR;
    double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
    if(sl >= ask) return;  // SL鏃犳晥

    TradeSignal sig;
    ZeroMemory(sig);
    sig.direction  = OB_BUY;
    sig.sl         = sl;
    sig.tp         = 0.0;
    sig.risk_price = ask - sl;
    sig.lot        = InpH4TrendLot;
    sig.pos_mult   = 1.0;
    sig.ob_index   = -1;
    sig.comment    = "H4TREND";

    if(ExecuteSignalFromZone(sig, g_zones, g_state.ob_count, false))
    {
        g_state.pos_count++;
        s_h4_cooldown = (int)InpH4TrendCooldownBars;
        Print("H4TREND鍏ュ満 sl=", DoubleToString(sl, _Digits), " lot=", InpH4TrendLot);
    }
}

// ATR閫氶亾鍧囧€煎洖褰掞細浠锋牸瑙︾閫氶亾杈圭晫鏃堕€嗗悜鍏ュ満
void TryATRChannelEntry(string symbol, bool new_bar)
{
    if(!InpEnableATRChannel || !new_bar) return;
    if(g_state.pos_count >= CfgMaxConcurrent()) return;

    static int s_atr_cooldown = 0;
    if(s_atr_cooldown > 0) { s_atr_cooldown--; return; }

    ENUM_TIMEFRAMES tf = MinutesToTF(InpATRChannelTF);
    int n = InpATRChannelBars;
    MqlRates rates[];
    if(CopyRates(symbol, tf, 1, n + InpATRPeriod + 1, rates) < n + 1) return;
    int cnt = ArraySize(rates);

    // 璁＄畻涓灑(鏈€杩憂鏍筀鐨勫钩鍧囨敹鐩樹环)鍜孉TR
    double atr = CalcATR(rates, cnt, InpATRPeriod);
    if(atr <= 0) return;

    double sum = 0;
    for(int i = cnt - n; i < cnt; i++) sum += rates[i].close;
    double mid = sum / n;

    double upper = mid + InpATRChannelMult * atr;
    double lower = mid - InpATRChannelMult * atr;

    double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
    double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);

    // 瑙︾涓嬭竟鐣屽仛澶氾紝瑙︾涓婅竟鐣屽仛绌?
    int direction = 0;
    if(bid <= lower * InpATRChannelEntryBand + upper * (1.0 - InpATRChannelEntryBand))
        direction = OB_BUY;
    else if(ask >= upper * InpATRChannelEntryBand + lower * (1.0 - InpATRChannelEntryBand))
        direction = OB_SELL;
    if(direction == 0) return;

    // 绠€鍖栧叆鍦烘潯浠讹細浠锋牸瑙﹀強閫氶亾杈圭晫渚?
    double entry_threshold = (direction == OB_BUY) ? lower : upper;
    if(direction == OB_BUY && bid > entry_threshold) return;
    if(direction == OB_SELL && ask < entry_threshold) return;

    double sl = (direction == OB_BUY)
        ? lower - InpATRChannelSLMult * atr
        : upper + InpATRChannelSLMult * atr;

    TradeSignal sig;
    ZeroMemory(sig);
    sig.direction  = direction;
    sig.sl         = sl;
    sig.tp         = 0.0;
    sig.risk_price = MathAbs(((direction == OB_BUY) ? ask : bid) - sl);
    sig.lot        = (InpATRChannelLot > 0) ? InpATRChannelLot : 0.01;
    sig.pos_mult   = 1.0;
    sig.ob_index   = -1;
    sig.comment    = "ATRCHAN";

    if(ExecuteSignalFromZone(sig, g_zones, g_state.ob_count, false))
    {
        g_state.pos_count++;
        s_atr_cooldown = InpATRChannelCooldown;
        Print("ATRCHAN鍏ュ満 dir=", direction, " mid=", DoubleToString(mid, _Digits),
              " upper=", DoubleToString(upper, _Digits), " lower=", DoubleToString(lower, _Digits));
    }
}

// 鍔ㄩ噺杩借釜锛氳繛缁璑鏍瑰悓鍚慘绾垮悗杩藉叆
void TryMomentumEntry(string symbol, bool new_bar)
{
    if(!InpEnableMomentum || !new_bar) return;
    if(g_state.pos_count >= CfgMaxConcurrent()) return;

    static int s_mom_cooldown = 0;
    if(s_mom_cooldown > 0) { s_mom_cooldown--; return; }

    ENUM_TIMEFRAMES tf = MinutesToTF(InpMomentumTF);
    int n = InpMomentumBars;
    MqlRates rates[];
    if(CopyRates(symbol, tf, 1, n + InpATRPeriod + 1, rates) < n + 1) return;
    int cnt = ArraySize(rates);

    double atr = CalcATR(rates, cnt, InpATRPeriod);
    if(atr <= 0) return;

    // 妫€鏌ユ渶杩憂鏍瑰凡鏀剁洏K绾挎槸鍚﹀悓鍚戜笖姣忔牴娑ㄨ穼骞?=MinPct%
    int direction = 0;
    bool all_up = true, all_dn = true;
    for(int i = cnt - n; i < cnt; i++)
    {
        double pct = 0;
        if(rates[i].open > 0) pct = (rates[i].close - rates[i].open) / rates[i].open * 100.0;
        if(pct < InpMomentumMinPct)  all_up = false;
        if(pct > -InpMomentumMinPct) all_dn = false;
    }
    if(all_up)       direction = OB_BUY;
    else if(all_dn)  direction = OB_SELL;
    if(direction == 0) return;

    // SL = n鏍硅捣濮嬩环澶?N*ATR
    double sl_base = (direction == OB_BUY)
        ? rates[cnt - n].open - InpMomentumSLATRMult * atr
        : rates[cnt - n].open + InpMomentumSLATRMult * atr;

    double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
    double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
    if(direction == OB_BUY && sl_base >= ask)   return;
    if(direction == OB_SELL && sl_base <= bid)  return;

    TradeSignal sig;
    ZeroMemory(sig);
    sig.direction  = direction;
    sig.sl         = sl_base;
    sig.tp         = 0.0;
    sig.risk_price = MathAbs(((direction == OB_BUY) ? ask : bid) - sl_base);
    sig.lot        = InpMomentumLot > 0 ? InpMomentumLot : 0.01;
    sig.pos_mult   = 1.0;
    sig.ob_index   = -1;
    sig.comment    = "MOM";

    if(ExecuteSignalFromZone(sig, g_zones, g_state.ob_count, false))
    {
        g_state.pos_count++;
        s_mom_cooldown = InpMomentumCooldown;
        Print("MOM鍏ュ満 dir=", direction, " n=", n, " pct>=", InpMomentumMinPct, "%");
    }
}

bool ExecuteSignalFromZone(const TradeSignal &sig, OBZone &zones[], int zone_count, bool allow_layered)
{
    if(ShouldSkipEntryAttempt())
        return false;

    MqlTradeRequest request = {};
    MqlTradeResult  result  = {};

    request.action    = TRADE_ACTION_DEAL;
    request.symbol    = _Symbol;
    request.volume    = sig.lot;
    request.type      = sig.direction > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
    request.price     = sig.direction > 0 ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                                          : SymbolInfoDouble(_Symbol, SYMBOL_BID);
    request.sl        = BrokerStopFromVirtualSL(sig.sl, request.price, sig.risk_price, sig.direction);
    request.tp        = sig.tp;
    request.magic     = InpMagicNumber;
    request.comment   = sig.comment;
    request.deviation = 20;
    request.type_filling = ORDER_FILLING_IOC;
    request.type_time    = ORDER_TIME_GTC;

    if(!OrderSend(request, result))
    {
        // INVALID_STOPS(10016): SL璺濈涓嶈冻, 鏍囪OB宸茬敤閬垮厤鍙嶅閲嶈瘯
        if(result.retcode == 10016)
        {
            static int s_invalid_stops_count = 0;
            s_invalid_stops_count++;
            if(s_invalid_stops_count <= 10 || s_invalid_stops_count % 1000 == 0)
                Print("invalid stops skipped count=", s_invalid_stops_count, " comment=", sig.comment);
            if(sig.ob_index >= 0 && sig.ob_index < zone_count)
                zones[sig.ob_index].used = true;
            return false;
        }

        if(result.retcode == TRADE_RETCODE_REQUOTE)
        {
            request.price = sig.direction > 0 ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                                              : SymbolInfoDouble(_Symbol, SYMBOL_BID);
            if(!OrderSend(request, result))
            {
                Print("寮€浠撳け璐?閲嶈瘯): ", result.comment, " retcode=", result.retcode);
                MarkEntryAttemptFailed();
                return false;
            }
        }
        else
        {
            static int s_fail_count = 0;
            s_fail_count++;
            if(s_fail_count <= 10 || s_fail_count % 500 == 0)
                Print("open failed count=", s_fail_count, " comment=", result.comment, " retcode=", result.retcode);
            MarkEntryAttemptFailed();
            return false;
        }
    }

    if(result.retcode == TRADE_RETCODE_DONE)
    {
        Print("寮€浠撴垚鍔? ", sig.comment, " ticket=", result.order,
              " price=", result.price, " lot=", sig.lot,
              " bounce_sec=", sig.bounce_seconds,
              " bounce_ob=", DoubleToString(sig.bounce_ob_pct, 3),
              " confirm_pos=", DoubleToString(sig.confirm_ob_pos, 3),
              " touch=", DoubleToString(sig.touch_price, _Digits),
              " confirm=", DoubleToString(sig.confirm_price, _Digits));

        RecordMonthlyEntry();
        RegisterPosition(result.order, sig.direction, result.price, sig.sl, sig.risk_price,
                         sig.deep_entry,
                         sig.htf_target, sig.htf_partial_r, sig.htf_partial_pct,
                         sig.failure_reverse,
                         g_tracks, g_track_count);

        if(g_track_count > 0)
        {
            g_tracks[g_track_count - 1].open_bar = g_state.bar_count;
            g_tracks[g_track_count - 1].entry_market_state = g_state.market_state;
        }

        if(allow_layered && InpLayeredEntryCount >= 2)
            ExecuteLayeredOrders(sig, result.price);
        ExecuteMicroEntryOrders(sig);

        if(sig.ob_index >= 0 && sig.ob_index < zone_count)
            MarkZoneUsed(zones, sig.ob_index);

        return true;
    }

    return false;
}


// EMA趋势追踪入场：BTC强牛市月(价格在D1 EMA上方连续N根)顺势BUY
// 覆盖OB策略无法盈利的强单向上涨月（Sep24-Dec24类型）
// EMA趋势确认 + M5高点突破入场：BTC强牛市月（Sep24-Dec24类型）顺势BUY
// 条件：D1 EMA20连续N根上升+收盘在EMA上方，M5价格突破前N根最高点时追涨
void TryEMATrendEntry(string symbol, bool new_bar)
{
    if(!InpEnableEMATrend || !new_bar) return;
    if(g_state.pos_count >= CfgMaxConcurrent()) return;

    static int    s_ema_cooldown = 0;
    static int    s_ema_today_count = 0;
    static datetime s_ema_last_day = 0;

    if(s_ema_cooldown > 0) { s_ema_cooldown--; return; }

    // 每日计数重置
    MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
    datetime today_start = TimeCurrent() - (dt.hour*3600 + dt.min*60 + dt.sec);
    if(s_ema_last_day != today_start) { s_ema_last_day = today_start; s_ema_today_count = 0; }
    if(InpEMATrendMaxPerDay > 0 && s_ema_today_count >= InpEMATrendMaxPerDay) return;

    // === D1 EMA条件检查 ===
    ENUM_TIMEFRAMES d1tf = MinutesToTF(InpEMATrendTF);
    int period = InpEMATrendPeriod;
    int d1needed = InpEMATrendBars + period + 2;
    MqlRates d1[];
    if(CopyRates(symbol, d1tf, 1, d1needed, d1) < d1needed) return;
    int d1cnt = ArraySize(d1);

    // 计算EMA
    double ema[];
    ArrayResize(ema, d1cnt);
    double k = 2.0 / (period + 1.0);
    ema[0] = d1[0].close;
    for(int i = 1; i < d1cnt; i++) ema[i] = d1[i].close * k + ema[i-1] * (1.0 - k);

    // 条件：最近N根D1收盘在EMA上方 + EMA斜率正
    int n = InpEMATrendBars;
    for(int i = d1cnt - n; i < d1cnt; i++)
    {
        if(d1[i].close <= ema[i]) return;  // 收盘低于EMA，取消
        if(i > 0 && ema[i-1] > 0)
        {
            double slope = (ema[i] - ema[i-1]) / ema[i-1] * 100.0;
            if(slope < InpEMATrendMinSlopePct) return;  // 斜率不足
        }
    }

    // === M5突破入场：价格突破前N根M5最高点 ===
    int m5lookback = (int)InpEMATrendPullbackATR;  // 复用参数：突破回看M5根数(整数部分)
    if(m5lookback < 2) m5lookback = 8;
    MqlRates m5[];
    if(CopyRates(symbol, PERIOD_M5, 1, m5lookback + 1, m5) < m5lookback + 1) return;
    int m5cnt = ArraySize(m5);

    // 前N根M5（不含最新未完成bar）的最高/最低价
    double recent_high = m5[0].high;
    double recent_low  = m5[0].low;
    for(int i = 1; i < m5cnt - 1; i++)  // 跳过最新bar(m5[m5cnt-1])
    {
        if(m5[i].high > recent_high) recent_high = m5[i].high;
        if(m5[i].low  < recent_low)  recent_low  = m5[i].low;
    }

    double atr = g_state.atr_value;
    if(atr <= 0) return;

    // 突破条件：当前bar收盘 > 前N根最高点
    double last_close = m5[m5cnt - 1].close;  // 最新已收盘M5
    double breakout_level = recent_high + 0.1 * atr;  // 轻微超越防假突破
    if(last_close <= breakout_level) return;

    // SL = 前N根M5最低点 - buffer
    double sl = recent_low - InpEMATrendSLATR * atr;
    double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
    if(sl >= ask) return;

    double risk_price = ask - sl;
    if(risk_price <= 0) return;

    // 仓位：用 risk_percent（lot=0时）或固定手数
    double lot = (InpEMATrendLot > 0) ? InpEMATrendLot
                 : CalcLotSize(symbol, InpRiskPercent, risk_price);
    if(lot <= 0) lot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);

    TradeSignal sig;
    ZeroMemory(sig);
    sig.direction  = OB_BUY;
    sig.sl         = sl;
    sig.tp         = 0.0;
    sig.risk_price = risk_price;
    sig.lot        = lot;
    sig.pos_mult   = 1.0;
    sig.ob_index   = -1;
    sig.comment    = StringFormat("EMABREAK brk=%.0f ema=%.0f", breakout_level, ema[d1cnt-1]);

    if(ExecuteSignalFromZone(sig, g_zones, g_state.ob_count, false))
    {
        g_state.pos_count++;
        s_ema_cooldown = InpEMATrendCooldown;
        s_ema_today_count++;
        PrintFormat("EMABREAK入场 brk=%.0f ask=%.0f sl=%.0f lot=%.3f",
                    breakout_level, ask, sl, lot);
    }
}